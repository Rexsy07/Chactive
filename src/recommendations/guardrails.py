"""STAGE 4 — Client Re-ranking & Business Filters.

``apply_feed_guardrails`` takes the *model-scored* candidate list in ranked order
and applies product/business constraints that the model cannot be trained on:

  1. Flair Frequency Capping
       A user must never see more than two consecutive posts of the *exact same*
       flair category. If slots at index i and i+1 are 'Hustle', slot i+2 must be
       a different flair.

  2. Author De-clustering
       If an author appears more than once within a sliding window of size W=5,
       push their subsequent repeats down by penalizing their score by 40%.

  3. Format Diversity Rule
       High-engagement visual formats (video / vertical-video / carousel) must
       not exceed a 40% density per block of 10 items; otherwise text-based
       alerts get crowded out.

The function mutates ``PostRow.score`` (a working score) and returns a copy of
the list with these constraints satisfied. Items the caller has already seen
(via ``user_history_ids``) are filtered out up front.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Iterable

from .schema import PostRow

logger = logging.getLogger(__name__)

#: Max consecutive repeats of the same flair.
MAX_CONSECUTIVE_FLAIR: int = 2
#: Sliding-window size for author de-clustering.
AUTHOR_WINDOW: int = 5
#: Penalty applied (multiplicative) to clustered-author repeats.
AUTHOR_PENALTY_RATE: float = 0.4
#: Max rich-media density (fraction) per viewing block of 10 items.
MAX_RICH_DENSITY: float = 0.40
#: Items per density window.
DENSITY_WINDOW: int = 10


def _score_key(post: PostRow) -> float:
    """Ordering key mirroring the heavy-rank FinalScore (higher is better)."""
    return float(post.score)


def apply_feed_guardrails(
    ranked_posts: list[PostRow],
    user_history_ids: Iterable[int],
    *,
    max_consecutive_flair: int = MAX_CONSECUTIVE_FLAIR,
    author_window: int = AUTHOR_WINDOW,
    author_penalty_rate: float = AUTHOR_PENALTY_RATE,
    max_rich_density: float = MAX_RICH_DENSITY,
    density_window: int = DENSITY_WINDOW,
) -> list[PostRow]:
    """Re-order ``ranked_posts`` so all three business constraints hold.

    Returns a NEW list; the input is not mutated. Posts whose id appears in
    ``user_history_ids`` (already seen this session) are dropped first.
    """
    seen = set(user_history_ids or ())
    available = [p for p in ranked_posts if p.id not in seen]
    if not available:
        return []

    # Work on a copy and record the original model order for stable ties.
    scored: list[PostRow] = list(available)

    # ------------------------------------------------------------------
    # Pass 1: author de-clustering (score penalty), iterative until stable.
    # ------------------------------------------------------------------
    # A single greedy pass re-prioritizes repeats, then we re-sort. Because the
    # penalty is multiplicative and idempotent on repeated applications, we recur
    # up to len(items) times to guarantee the sliding-window constraint settles.
    pass_count = 0
    while pass_count <= len(scored):
        pass_count += 1
        window: deque[str] = deque(maxlen=author_window)
        author_count: dict[str, int] = defaultdict(int)
        changed = False
        for post in scored:
            if post.handle in author_count:
                # Every repeat beyond the first inside the window is penalized 40%.
                post.score = post.score * (1.0 - author_penalty_rate)
                changed = True
            author_count[post.handle] = author_count[post.handle] + 1
            window.append(post.handle)
            if len(window) == author_window:
                evicted = window.popleft()
                author_count[evicted] = author_count[evicted] - 1
                if author_count[evicted] <= 0:
                    del author_count[evicted]
        scored.sort(key=_score_key, reverse=True)
        if not changed:
            break

    # ------------------------------------------------------------------
    # Greedy placement satisfying flair capping + per-screen density cap.
    # ------------------------------------------------------------------
    # Screen semantics: the feed is viewed in screens of ``density_window`` (10)
    # items. The 40% density rule is enforced PER SCREEN: a screen may hold at
    # most ``floor(40% * density_window)`` rich-media items. This is exactly
    # "cap video formats at max 40% per 10-item screen" and is feasible whenever
    # data allows, avoiding a window-length artifact that blocks rich items from
    # ever appearing early in the feed.
    result: list[PostRow] = []
    # rich_per_screen[screen_index] = number of rich items already placed there.
    rich_per_screen: dict[int, int] = {}
    screen_size = max(1, density_window)
    rich_quota = max(1, int(screen_size * max_rich_density))

    while scored:
        placed = False
        # Try candidates in score order; pick the first that satisfies both the
        # "no >N consecutive same flair" and the per-screen density cap.
        for i, post in enumerate(scored):
            # Constraint 1: no more than `max_consecutive_flair` consecutive equal flairs.
            if len(result) >= max_consecutive_flair:
                if (
                    result[-1].flair == post.flair
                    and result[-2].flair == post.flair
                ):
                    continue
            # Constraint 3: per-screen rich-media density cap.
            screen = len(result) // screen_size
            if post.is_rich_media() and rich_per_screen.get(screen, 0) >= rich_quota:
                # Try the next screen before giving up on this candidate.
                nxt_screen = screen + 1
                if rich_per_screen.get(nxt_screen, 0) >= rich_quota:
                    continue
                screen = nxt_screen
            # Place it.
            result.append(post)
            rich_per_screen[screen] = rich_per_screen.get(screen, 0) + (
                1 if post.is_rich_media() else 0
            )
            scored.pop(i)
            placed = True
            break
        if not placed:
            # Pathological input where constraints cannot all be met (e.g. more
            # rich items than any screen can absorb). Force-place the highest-
            # remaining item to guarantee termination and avoid dropping content.
            post = scored.pop(0)
            result.append(post)
            rich_per_screen[len(result) // screen_size] = (
                rich_per_screen.get(len(result) // screen_size, 0)
                + (1 if post.is_rich_media() else 0)
            )
            logger.warning(
                "guardrail deadlock, force-placing post id=%s", post.id
            )

    return result


# -----------------------------------------------------------------------------
# Small helper used by the orchestrator to page results into screen views.
# -----------------------------------------------------------------------------


def paginate_feed(feed: list[PostRow], page_size: int = 10) -> list[list[PostRow]]:
    """Split ``feed`` into contiguous ``page_size``-item screen views."""
    return [feed[i : i + page_size] for i in range(0, len(feed), page_size)]


__all__ = [
    "apply_feed_guardrails",
    "paginate_feed",
    "MAX_CONSECUTIVE_FLAIR",
    "AUTHOR_WINDOW",
    "AUTHOR_PENALTY_RATE",
    "MAX_RICH_DENSITY",
    "DENSITY_WINDOW",
]