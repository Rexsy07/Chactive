"""Hyper-localized social discovery recommendation pipeline for Kampus.

The pipeline reduces the full post corpus to a personalized, business-compliant
feed:

    Stage 1  Hot Campus Feed (SQL)      -> deterministic localized ranking
    Stage 2  Retrieval (Python)         -> 500 candidates
    Stage 3  Heavy Ranking (PyTorch)    -> DLRM multi-task probabilities
    Stage 4  Guardrails (Python)        -> flair/author/format business filters

Public entry point: :func:`personal_feed`.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    import torch
    from .ranker import CampusMultiTaskRanker
else:
    torch = None
    CampusMultiTaskRanker = None

from .guardrails import apply_feed_guardrails
from .schema import InteractionRecord, PostRow, UserContext, utcnow

__version__ = "1.0.0"

logger = logging.getLogger(__name__)

__all__ = ["__version__", "personal_feed", "get_ranking_strategy"]


def get_ranking_strategy(user: UserContext) -> str:
    """Describe which ranking strategy applies for a request (diagnostics)."""
    if user.follows:
        return "follows+cf+coldstart"
    return "cf+coldstart"


def _heavy():
    """Return (rank_model_cls, retrieval budget) importing heavy deps lazily.

    Raising inside here vs. at import time keeps the lightweight modules
    (schema, guardrails) usable even when scipy/torch are not installed.
    """
    torch_mod = importlib.import_module("torch")
    ranker_mod = importlib.import_module(".ranker", package=__name__)
    retrieval_mod = importlib.import_module(".retrieval", package=__name__)
    return torch_mod, ranker_mod, retrieval_mod


def personal_feed(
    *,
    user: UserContext,
    all_posts: Sequence[PostRow],
    interaction_records: Sequence[InteractionRecord],
    user_interaction_flair_counts: dict[str, int],
    user_history_ids: Sequence[int],
    followed_posts: Sequence[PostRow] | None = None,
    rank_model: CampusMultiTaskRanker | None = None,
    device: torch.device | None = None,
    retrieval_budget: int = 500,
    batch_size: int = 256,
    now=None,
    tie_breaker: Callable[[PostRow], float] | None = None,
) -> list[PostRow]:
    """End-to-end "For You" pipeline: retrieve -> score -> guardrail.

    Args:
        user: the requestor (id/handle/campus/follows).
        all_posts: full corpus scan (or pre-filtered superset of candidates).
        interaction_records: weighted engagement events for collaborative filter.
        user_interaction_flair_counts: flair -> interaction-count for embedding.
        user_history_ids: already-seen post ids (filtered in guardrails).
        followed_posts: the slice of ``all_posts`` relevant to two-step follows
            (posts by followed handles/flairs). Default: all of ``all_posts``.
        rank_model: a trained :class:`CampusMultiTaskRanker`. If ``None``, a
            freshly-initialized model is used (untrained => warm-start ordering
            only; the function still returns a valid ranked list).
        device: compute device. Defaults to CUDA if available else CPU.
        retrieval_budget: number of candidates handed to the heavy ranker.
        batch_size: inference batch size.
        now: current time (timezone aware) for cold-start age math.

    Returns:
        A ``list[PostRow]`` ranked by FinalScore and then passed through the
        business guardrails (deduplicated, re-ordered, business-constrained).
    """
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    now = now or utcnow()

    # ---- STAGE 2: retrieval -------------------------------------------
    # Heavy deps (scipy / torch) are imported on first use so the lightweight
    # modules remain usable in environments where they are not installed.
    torch_mod, ranker_mod, retrieval_mod = _heavy()
    candidates = retrieval_mod.retrieve_candidates(
        user=user,
        all_posts=list(all_posts),
        follows_posts=list(followed_posts) if followed_posts is not None else list(all_posts),
        interaction_records=list(interaction_records),
        budget=retrieval_budget,
        now=now,
    )

    # ---- STAGE 3: heavy ranking ---------------------------------------
    cls = ranker_mod.CampusMultiTaskRanker
    if rank_model is None:
        rank_model = cls()
    rank_model = rank_model.to(device)
    rank_model.eval()

    pref_flair = ranker_mod.prefer_flair_slug(user_interaction_flair_counts)
    # Session activity depth: proxy from the user's recent interaction counts.
    session_depth = _session_depth_estimate(user_interaction_flair_counts)
    session_len = float(len(user_history_ids))

    scored: list[PostRow] = []
    with torch_mod.inference_mode():
        for start in range(0, len(candidates), batch_size):
            chunk = candidates[start : start + batch_size]
            batch = rank_model.encode_batch(
                user_campus=[user.campus] * len(chunk),
                user_flair_pref=[pref_flair] * len(chunk),
                user_dense=[
                    ranker_mod.user_dense_features(session_depth, session_len)
                ] * len(chunk),
                post_flair=[p.flair for p in chunk],
                post_kind=[p.kind for p in chunk],
                post_dense=[
                    ranker_mod.post_dense_features(p.votes, p.comments, p.votes, p.comments)
                    for p in chunk
                ],
                device=device,
            )
            final = rank_model.final_scores(batch)
            for post, s in zip(chunk, final.tolist(), strict=False):
                post.score = float(s)
                scored.append(post)
            del batch

    # Stable fallback ordering for ties: newest first.
    scored.sort(key=lambda p: (p.score, p.created_at.timestamp()), reverse=True)

    # ---- STAGE 4: business guardrails ---------------------------------
    return apply_feed_guardrails(scored, user_history_ids)


def _session_depth_estimate(_counts: dict[str, int]) -> float:
    """Estimated interpretation of 'session activity depth'.

    This is a stand-in for deeper telemetry (dwell time, open depth). In a real
    deployment the caller supplies the actual scalar. We derive a bounded proxy
    from the size of the user's recent interaction counts so the model input is
    always non-negative and stable.
    """
    return float(min(sum(_counts.values()), 50.0))