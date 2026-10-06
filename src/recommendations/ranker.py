"""STAGE 3 — Heavy Ranking via ``CampusMultiTaskRanker`` (PyTorch).

A deep-learning recommendation model in the DLRM spirit:
  * Categorical features (campus, flair, kind) map to learned embeddings.
  * Interaction bits (user <-> post) are computed via a bilinear/MLP tower
    instead of a flat dot product so the model can capture per-head semantics.
  * Three independent prediction heads emit event probabilities:
        P_upvote, P_comment, P_bookmark
  * The final ordering value combines the heads with the product's hard-coded
    business weights:
        FinalScore = 0.3*P_upvote + 0.5*P_comment + 0.7*P_bookmark

The model is schema-grounded: the categorical vocabularies are derived from the
actual ``campus``, ``flair`` and ``kind`` domains in ``schema.py``, and the
continuous feature side is fed from ``PostRow`` numeric fields (votes, comments,
rolling velocity) plus the user's session-activity depth.

Training objective is multi-task binary cross-entropy summed across the three
heads; labels are the observed interactions for each candidate.
"""

from __future__ import annotations

import math
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from .schema import CAMPUSES, FLAIRS, MEDIA_KINDS

# -----------------------------------------------------------------------------
# Shared public constants
# -----------------------------------------------------------------------------

#: Business weights for the final ordering value (fixed by product requirement).
FINAL_W_UPVOTE: float = 0.3
FINAL_W_COMMENT: float = 0.5
FINAL_W_BOOKMARK: float = 0.7

#: Number of continuous (dense) user/post scalar features fed to the MLP towers.
N_USER_DENSE: int = 2   # session_activity_depth, session_session_len
N_POST_DENSE: int = 4   # log1p(votes), log1p(comments), vote_velocity, comment_velocity


class CampusMultiTaskRanker(nn.Module):
    """DLRM-style multi-task ranker producing three interaction probabilities.

    Feature groups

      User vectors
        emb_campus    : embedding of ``user.campus``
        emb_flair_pref: embedding of the user's top preferred flair (by count)
        user_dense    : session activity depth + session length

      Post vectors
        emb_flair    : embedding of ``post.flair``
        emb_kind     : embedding of ``post.kind``
        post_dense   : log1p(votes), log1p(comments), vote velocity, comment velocity

    Structure
      - embeddings concat(user tower, post tower) -> shared MLP -> multi-head.

    Edge cases handled at the vocabulary level: unknown campus / flair / kind
    fall back to a reserved OOV index (0), so live rows never break inference.
    """

    def __init__(
        self,
        embed_dim: int = 32,
        hidden_dim: int = 128,
        dropout: float = 0.1,
        n_user_dense: int = N_USER_DENSE,
        n_post_dense: int = N_POST_DENSE,
        *,
        vocab_campus: list[str] | None = None,
        vocab_flair: list[str] | None = None,
        vocab_kind: list[str] | None = None,
    ) -> None:
        super().__init__()

        self.vocab_campus = ["<OOV>"] + (vocab_campus or list(CAMPUSES))
        self.vocab_flair = ["<OOV>"] + (vocab_flair or list(FLAIRS))
        self.vocab_kind = ["<OOV>"] + list(vocab_kind or sorted(MEDIA_KINDS))

        self.embed_dim = embed_dim

        # Categorical embeddings (index 0 reserved for OOV).
        self.emb_campus = nn.Embedding(len(self.vocab_campus), embed_dim, padding_idx=0)
        self.emb_flair_pref = nn.Embedding(len(self.vocab_flair), embed_dim, padding_idx=0)
        self.emb_flair = nn.Embedding(len(self.vocab_flair), embed_dim, padding_idx=0)
        self.emb_kind = nn.Embedding(len(self.vocab_kind), embed_dim, padding_idx=0)

        # Interaction coupling (DLRM-style bilinear between user and post towers).
        self.interact = nn.Bilinear(2 * embed_dim, 2 * embed_dim, hidden_dim, bias=False)

        # Continuous feature counters.
        self.n_user_dense = n_user_dense
        self.n_post_dense = n_post_dense

        # Shared head MLPs.
        shared_in = hidden_dim + n_user_dense + n_post_dense
        self.shared_dp = nn.Dropout(dropout)
        self.shared = nn.Sequential(
            nn.LayerNorm(shared_in),
            nn.Linear(shared_in, hidden_dim),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(inplace=True),
        )

        # Three independent prediction heads.
        self.head_upvote = self._head(hidden_dim)
        self.head_comment = self._head(hidden_dim)
        self.head_bookmark = self._head(hidden_dim)

        self._init_weights()

    @staticmethod
    def _head(in_dim: int) -> nn.Sequential:
        return nn.Sequential(
            nn.LayerNorm(in_dim),
            nn.Linear(in_dim, 1),
        )

    def _init_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, 0.0, math.sqrt(1.0 / self.embed_dim))

    # ------------------------------------------------------------------
    # Vocabulary helpers
    # ------------------------------------------------------------------

    def _idx(self, vocab: list[str], key: str) -> int:
        if not key:
            return 0
        try:
            return vocab.index(key)
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        user_campus: torch.Tensor,
        user_flair_pref: torch.Tensor,
        user_dense: torch.Tensor,
        post_flair: torch.Tensor,
        post_kind: torch.Tensor,
        post_dense: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """Forward through the ranker.

        Args are integer-encoded tensors (shape ``(B,)`` for ids, ``(B, D)``
        for dense). Returns a dict with the three sigmoid-logit heads.
        """
        u_campus = self.emb_campus(user_campus)          # (B, E)
        u_flair = self.emb_flair_pref(user_flair_pref)   # (B, E)
        p_flair = self.emb_flair(post_flair)             # (B, E)
        p_kind = self.emb_kind(post_kind)                # (B, E)

        user_vec = torch.cat([u_campus, u_flair], dim=-1)      # (B, 2E)
        post_vec = torch.cat([p_flair, p_kind], dim=-1)        # (B, 2E)

        # DLRM-style interaction between the two 2E towers -> (B, hidden).
        inter = self.interact(user_vec, post_vec)

        base = torch.cat([inter, user_dense, post_dense], dim=-1)
        shared = self.shared_dp(self.shared(base))

        return {
            "p_upvote": self.head_upvote(shared),
            "p_comment": self.head_comment(shared),
            "p_bookmark": self.head_bookmark(shared),
        }

    # ------------------------------------------------------------------
    # Loss / scoring
    # ------------------------------------------------------------------

    def loss(
        self,
        logits: dict[str, torch.Tensor],
        targets: dict[str, torch.Tensor],
    ) -> dict[str, torch.Tensor]:
        """Multi-task BCE summed across the three heads.

        ``logits`` / ``targets`` share the keys ``p_upvote``, ``p_comment``,
        ``p_bookmark``; targets are float ``(B,)`` 0/1 tensors.
        """
        loss = {}
        total = torch.zeros((), device=next(self.parameters()).device)
        for key, logit in logits.items():
            target = targets[key].unsqueeze(-1)
            l = F.binary_cross_entropy_with_logits(logit, target, reduction="mean")
            loss[key] = l
            total = total + l
        loss["total"] = total
        return loss

    @torch.no_grad()
    def predict(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Run forward and apply sigmoid to each head.

        The returned dict contains ``p_upvote``, ``p_comment``, ``p_bookmark`` as
        probabilities in [0, 1] with shape ``(B, 1)``.
        """
        self.eval()
        logits = self.forward(
            batch["user_campus"],
            batch["user_flair_pref"],
            batch["user_dense"],
            batch["post_flair"],
            batch["post_kind"],
            batch["post_dense"],
        )
        return {k: torch.sigmoid(v) for k, v in logits.items()}

    @torch.no_grad()
    def final_scores(self, batch: dict[str, torch.Tensor]) -> torch.Tensor:
        """Compute the product-defined ordering value for a batch.

            FinalScore = 0.3*P_upvote + 0.5*P_comment + 0.7*P_bookmark
        """
        probs = self.predict(batch)
        score = (
            FINAL_W_UPVOTE * probs["p_upvote"]
            + FINAL_W_COMMENT * probs["p_comment"]
            + FINAL_W_BOOKMARK * probs["p_bookmark"]
        )
        return score.squeeze(-1)

    # ------------------------------------------------------------------
    # Convenience: build an encoded user batch from raw strings
    # ------------------------------------------------------------------

    def encode_batch(
        self,
        user_campus: list[str],
        user_flair_pref: list[str],
        user_dense: list[list[float]],
        post_flair: list[str],
        post_kind: list[str],
        post_dense: list[list[float]],
        device: torch.device,
    ) -> dict[str, torch.Tensor]:
        """Encode string features into integer-id / float tensors for forward()."""
        n = len(user_campus)
        return {
            "user_campus": torch.tensor(
                [self._idx(self.vocab_campus, c) for c in user_campus],
                device=device,
                dtype=torch.long,
            ),
            "user_flair_pref": torch.tensor(
                [self._idx(self.vocab_flair, f) for f in user_flair_pref],
                device=device,
                dtype=torch.long,
            ),
            "user_dense": torch.tensor(user_dense, device=device, dtype=torch.float32),
            "post_flair": torch.tensor(
                [self._idx(self.vocab_flair, f) for f in post_flair],
                device=device,
                dtype=torch.long,
            ),
            "post_kind": torch.tensor(
                [self._idx(self.vocab_kind, k) for k in post_kind],
                device=device,
                dtype=torch.long,
            ),
            "post_dense": torch.tensor(post_dense, device=device, dtype=torch.float32),
        }


# -----------------------------------------------------------------------------
# Feature builders (convert raw rows into model inputs)
# -----------------------------------------------------------------------------


def post_dense_features(
    votes: int,
    comments: int,
    vote_velocity: float,
    comment_velocity: float,
) -> list[float]:
    """Continuous post features.

    log1p compresses vote/comment counts; velocities are per-hour rolling rates.
    """
    return [
        math.log1p(max(0, int(votes))),
        math.log1p(max(0, int(comments))),
        max(0.0, float(vote_velocity)),
        max(0.0, float(comment_velocity)),
    ]


def user_dense_features(
    session_activity_depth: float,
    session_length: float,
) -> list[float]:
    """Continuous user features for the current feed session."""
    return [
        max(0.0, float(session_activity_depth)),
        max(0.0, float(session_length)),
    ]


def prefer_flair_slug(user_interaction_flair_counts: dict[str, int]) -> str:
    """Return the most-frequently interacted flair, or the first known flair."""
    if not user_interaction_flair_counts:
        return FLAIRS[0]
    return max(user_interaction_flair_counts, key=user_interaction_flair_counts.get)


__all__ = [
    "CampusMultiTaskRanker",
    "FINAL_W_UPVOTE",
    "FINAL_W_COMMENT",
    "FINAL_W_BOOKMARK",
    "N_USER_DENSE",
    "N_POST_DENSE",
    "post_dense_features",
    "user_dense_features",
    "prefer_flair_slug",
]