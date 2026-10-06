# Kampus Recommendation Pipeline

Hyper-localized social discovery recommendation system for the Kampus Supabase
backend. The pipeline reduces the full post corpus to a personalized feed in four
stages, mirroring the exact `public` Postgres schema.

```
  100k+ posts
      │
      ▼
  ┌───────────────────────────┐
  │ STAGE 1 · SQL             │  get_hot_campus_feed() PL/pgSQL
  │ Hot Campus Feed (decay)   │  HN gravity, campus-scoped
  └───────────────────────────┘
      │
      ▼
  ┌───────────────────────────┐
  │ STAGE 2 · Python          │  retrieve_candidates()  -> 500 candidates
  │ Retrieval                 │  A: follows  B: collaborative filter  C: cold start
  └───────────────────────────┘
      │
      ▼
  ┌───────────────────────────┐
  │ STAGE 3 · PyTorch         │  CampusMultiTaskRanker
  │ Heavy ranking             │  P_upvote / P_comment / P_bookmark
  │                           │  FinalScore = 0.3*Pu + 0.5*Pc + 0.7*Pb
  └───────────────────────────┘
      │
      ▼
  ┌───────────────────────────┐
  │ STAGE 4 · Python          │  apply_feed_guardrails()
  │ Business filters          │  flair cap · author de-cluster · format diversity
  └───────────────────────────┘
      │
      ▼
   Personalized "For You" feed
```

## Files

| Module | Responsibility |
|---|---|
| [`schema.py`](schema.py) | Schema-grounded dataclasses + domain constants |
| [`retrieval.py`](retrieval.py) | Stage 2 retrieval (A/B/C strategies + budget) |
| [`ranker.py`](ranker.py) | Stage 3 `CampusMultiTaskRanker` (PyTorch DLRM-style) |
| [`guardrails.py`](guardrails.py) | Stage 4 `apply_feed_guardrails` + pagination |
| [`__init__.py`](__init__.py) | `personal_feed()` end-to-end orchestrator |

## STAGE 1 — Hot Campus Feed (SQL)

Migration: `supabase/migrations/<timestamp>_hot_campus_feed.sql`

```sql
SELECT * FROM public.get_hot_campus_feed('USER-UUID', 'UNILAG', 20, 0);
```

**Score** = `(NetVotes + Comments×1.5) / (AgeHours + 2)^1.8`

Let the join to `post_votes` / `bookmarks` produce `has_voted`, `vote_value`,
`has_bookmarked` via lateral point-lookups. The denominator is guarded so newly
created (0-hour-old) posts never divide by zero. `p_user_id` may be `NULL` for
anonymous browsing — all flags return `false` (no rows join).

## STAGE 2 — Retrieval

```python
from recommendations.retrieval import retrieve_candidates
candidates = retrieve_candidates(user=user, all_posts=..., interaction_records=...)
```

- **A. Follows** — posts by followed handles or matching followed flairs.
- **B. Collaborative filter** — scipy truncated SVD over a weighted matrix
  (upvote=2, bookmark=5, comment=4) to surface lookalike-cohort posts from other
  campuses.
- **C. Cold start** — 10% exploration budget of fresh (<3h) home-campus,
  low-vote (<5) posts.

De-duplicated and capped at exactly `budget` (default 500).

## STAGE 3 — Heavy Ranking

```python
import torch
from recommendations.ranker import CampusMultiTaskRanker
model = CampusMultiTaskRanker()
out = model.final_scores(batch)   # FinalScore vector
```

Multi-task BCE for training; three sigmoid heads. Categorical vocabularies are
derived from the real `campus` / `flair` / `kind` domains; unknown values fall
back to an `<OOV>` index so live rows never break inference.

## STAGE 4 — Guardrails

```python
from recommendations.guardrails import apply_feed_guardrails
feed = apply_feed_guardrails(ranked_posts, user_history_ids)
```

- Flair frequency capping (max 2 consecutive identical flairs).
- Author de-clustering (40% score penalty for clustered author in a 5-window).
- Format diversity (≤40% rich-media per 10-item screen).

## End-to-end

```python
from recommendations import personal_feed
feed = personal_feed(
    user=user_ctx,
    all_posts=posts,
    interaction_records=records,
    user_interaction_flair_counts={"Hustle": 3, "Campus": 2},
    user_history_ids=[1, 4, 9],
)
```

## Dependencies

`numpy`, `scipy`, `torch` (see [`requirements.txt`](requirements.txt)). The
lightweight modules (`schema.py`, `guardrails.py`) deliberately avoid these
imports so they remain usable in constrained environments; heavy deps are loaded
lazily on first prediction.