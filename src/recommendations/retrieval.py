"""STAGE 2 — Personalized Retrieval.

Reduces the candidate pool from the full post corpus (100k+) down to exactly
``retrieval_budget`` = 500 relevant candidates. Strategy:

  Strategy A (In-Network / Follows)  : posts whose author handle is followed, or
                                       whose flair is a followed entity.
  Strategy B (Collaborative Filtering): lookalike-cohort posts from *other*
                                       campuses, weighted (upvote=2, bookmark=5,
                                       comment=4), scipy/numpy implementation.
  Strategy C (Cold-Start Buffer)     : newest (<3h) home-campus posts with <5
                                       votes — an explicit exploration slot to
                                       break engagement feedback loops.

The three streams are unioned and de-duplicated before being capped at the
exact budget. Order at this stage is intentionally cheap; heavy ranking
(STAGE 3) is responsible for final ordering.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import svds

from .schema import (
    WEIGHT_BOOKMARK,
    WEIGHT_COMMENT,
    WEIGHT_UPVOTE,
    InteractionRecord,
    PostRow,
    UserContext,
    utcnow,
)

logger = logging.getLogger(__name__)

#: Hard cap on total candidates handed to the heavy ranker.
DEFAULT_RETRIEVAL_BUDGET: int = 500

#: Sub-budget carved out for cold-start exploration (10% of the budget).
COLD_START_FRACTION: float = 0.10

#: Cold-start definition: age younger than this and fewer than this many votes.
COLD_START_MAX_AGE_HOURS: float = 3.0
COLD_START_MAX_VOTES: int = 5


# -----------------------------------------------------------------------------
# Retrieval primitives
# -----------------------------------------------------------------------------


def _newer_than_hours(post: PostRow, hours: float, now) -> bool:
    """True when ``post`` was created within the last ``hours``."""
    age = (now - post.created_at).total_seconds() / 3600.0
    return age < hours


def strategy_a_follows(
    posts: Iterable[PostRow],
    user: UserContext,
) -> list[PostRow]:
    """In-network candidates: followed handles or followed flairs.

    A followed handle matches ``posts.handle``; a followed flair matches
    ``posts.flair``. Because ``follows`` can hold either, both are tested and a
    post is kept if it satisfies at least one.
    """
    handles = user.followed_handles
    flairs = {f.lower() for f in user.followed_flairs}
    out: list[PostRow] = []
    for post in posts:
        matches_handle = post.handle.lower() in handles
        matches_flair = post.flair.lower() in flairs
        if matches_handle or matches_flair:
            out.append(post)
    return out


def _to_feature_matrix(
    records: list[InteractionRecord],
    users: list[str],
    posts: list[int],
) -> tuple[csr_matrix, dict[str, int], dict[int, int]]:
    """Build the sparse U x P weighted matrix used by collaborative filtering.

    Weighting:
        upvote   -> 2
        bookmark -> 5
        comment  -> 4
    """
    u_idx = {u: i for i, u in enumerate(users)}
    p_idx = {p: i for i, p in enumerate(posts)}
    weight_map = {
        "upvote": WEIGHT_UPVOTE,
        "bookmark": WEIGHT_BOOKMARK,
        "comment": WEIGHT_COMMENT,
    }
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for rec in records:
        if rec.user_id not in u_idx or rec.post_id not in p_idx:
            continue  # interaction outside the current feature space
        w = weight_map.get(rec.kind)
        if w is None:
            continue
        rows.append(u_idx[rec.user_id])
        cols.append(p_idx[rec.post_id])
        data.append(float(w))
    if not rows:
        return csr_matrix((len(users), len(posts))), u_idx, p_idx
    matrix = csr_matrix(
        (data, (rows, cols)),
        shape=(len(users), len(posts)),
        dtype=np.float32,
    )
    return matrix.tocsr(), u_idx, p_idx


def strategy_b_collaborative(
    interaction_records: list[InteractionRecord],
    user: UserContext,
    all_posts: list[PostRow],
    target_size: int,
    home_campus_only_posts: Iterable[PostRow],
    rng: np.random.Generator,
    n_latent: int = 20,
) -> list[PostRow]:
    """Lookalike-cohort candidates via truncated SVD (scipy).

    Signs the top ``k`` latent user vectors to find cohorts similar to the target
    user, scores all posts by the cohort's predicted weight, then returns the
    top ``target_size`` posts that are NOT on the user's home campus.

    Edge cases are handled: no users, no interactions, or the target user absent
    from the matrix all fall back to the (empty) default rather than raising.
    """
    if not interaction_records:
        return []
    users = sorted({r.user_id for r in interaction_records})
    posts = sorted({r.post_id for r in interaction_records})
    matrix, u_idx, p_idx = _to_feature_matrix(interaction_records, users, posts)
    if matrix.nnz == 0 or user.id not in u_idx:
        return []

    k = min(n_latent, matrix.shape[0], matrix.shape[1]) - 1
    if k < 1:
        return []
    row_mean = np.asarray(matrix.mean(axis=1)).ravel()
    centered = matrix - csr_matrix(row_mean).T
    try:
        u, s, vt = svds(centered, k=k)
    except (ValueError, np.linalg.LinAlgError) as exc:  # ARPACK converge guards
        logger.warning("SVD failed (%s); skipping collaborative strategy", exc)
        return []

    # Latent factor of the target user, then its cosine cohort in latent space.
    target_vec = u[u_idx[user.id], :]
    if not np.any(target_vec):
        return []
    sims = u @ target_vec / (
        np.linalg.norm(u, axis=1) * np.linalg.norm(target_vec) + 1e-9
    )
    # Rank users by latent similarity; exclude self and near-negative cohorts.
    order = np.argsort(-sims)
    cohort_rows = [i for i in order if i != u_idx[user.id] and sims[i] > 0.0]
    if not cohort_rows:
        return []

    # Predicted engagement per post = centered dot-prod through latent space.
    cohort_vec = np.asarray(u[cohort_rows, :].mean(axis=0)).ravel()
    post_scores = (cohort_vec @ np.diag(s) @ vt) + float(row_mean.mean())

    # Retrieve full records and rank only posts NOT on the user's home campus.
    home_ids = {p.id for p in home_campus_only_posts}
    by_id = {p.id: p for p in all_posts}
    ranked: list[int] = []
    for i, post_id in enumerate(posts):
        if post_id in home_ids:
            continue
        if post_id not in by_id:
            continue
        ranked.append((post_id, float(post_scores[i])))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [by_id[pid] for pid, _ in ranked[:target_size]]


def strategy_c_cold_start(
    posts: Iterable[PostRow],
    user: UserContext,
    limit: int,
    now,
) -> list[PostRow]:
    """Fresh (<3h), sparsely-voted (<5 votes) home-campus posts.

    These fill the exploration buffer, preventing the model from over-fitting a
    feedback loop on established content.
    """
    out: list[PostRow] = []
    for post in posts:
        if post.campus != user.campus:
            continue
        if post.votes >= COLD_START_MAX_VOTES:
            continue
        if not _newer_than_hours(post, COLD_START_MAX_AGE_HOURS, now):
            continue
        out.append(post)
    out.sort(key=lambda p: p.created_at, reverse=True)
    return out[:limit]


# -----------------------------------------------------------------------------
# Retrieval orchestrator
# -----------------------------------------------------------------------------


def retrieve_candidates(
    *,
    user: UserContext,
    all_posts: list[PostRow],
    follows_posts: list[PostRow],
    interaction_records: list[InteractionRecord],
    budget: int = DEFAULT_RETRIEVAL_BUDGET,
    rng: np.random.Generator | None = None,
    now=None,
) -> list[PostRow]:
    """Merge the three strategies into exactly ``budget`` de-duplicated posts.

    Returns a ``list[PostRow]`` whose order is NOT meaningful (Stage 3 re-ranks).
    """
    rng = rng or np.random.default_rng()
    now = now or utcnow()

    # Strategy A — in-network.
    a_posts = strategy_a_follows(follows_posts, user)
    a_ids = {p.id for p in a_posts}

    # Strategy B — collaborative filtering over other campuses.
    other_campus_posts = [p for p in all_posts if p.campus != user.campus]
    cf_budget = budget - len(a_posts)
    b_posts = strategy_b_collaborative(
        interaction_records=interaction_records,
        user=user,
        all_posts=all_posts,
        target_size=cf_budget,
        home_campus_only_posts=[p for p in all_posts if p.campus == user.campus],
        rng=rng,
    )
    b_ids = {p.id for p in b_posts} - a_ids

    # Strategy C — cold start (10% of full budget, minimum this large).
    cold_budget = max(int(budget * COLD_START_FRACTION), 1)
    c_posts = strategy_c_cold_start(all_posts, user, cold_budget, now)
    c_ids = {p.id for p in c_posts} - a_ids - b_ids

    # Deduplicate and enforce the exact budget, preferring A > B > C.
    selected: list[PostRow] = list(a_posts)
    selected.extend(p for p in b_posts if p.id in b_ids)
    selected.extend(p for p in c_posts if p.id in c_ids)
    if len(selected) > budget:
        selected = selected[:budget]

    # Fill any shortfall that isn't already claimed by feeds.
    seen = {p.id for p in selected}
    shortfall = budget - len(selected)
    if shortfall > 0:
        for post in all_posts:
            if post.id in seen:
                continue
            seen.add(post.id)
            selected.append(post)
            shortfall -= 1
            if shortfall <= 0:
                break

    return selected[:budget]


__all__ = [
    "retrieve_candidates",
    "strategy_a_follows",
    "strategy_b_collaborative",
    "strategy_c_cold_start",
    "DEFAULT_RETRIEVAL_BUDGET",
    "COLD_START_FRACTION",
    "COLD_START_MAX_AGE_HOURS",
    "COLD_START_MAX_VOTES",
]