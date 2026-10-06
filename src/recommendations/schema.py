"""Schema metadata for the Kampus Supabase-backed Postgres backend.

This module mirrors the *actual* DDL so the recommender is never written against
placeholder column names. Keep field names in lock-step with the migrations.

Relevant tables / columns:

  public.profiles   (id uuid PK, handle text UNIQUE, display_name, campus text)
  public.posts      (id bigint PK, author_id uuid, handle text, campus text,
                     flair text, title text, body text, kind text, media_url,
                     votes int, comments int, created_at timestamptz)
  public.post_votes (user_id uuid, post_id bigint, value smallint IN (-1,1))
  public.bookmarks  (user_id uuid, post_id bigint)
  public.comments   (post_id bigint, author_id uuid, body text)
  public.follows    (user_id uuid, target text)   -- target = handle OR flair slug

Known enum-ish value domains (from seeds / app code):
  campus : UNILAG | UI | OAU | UNN | ABU
  flair  : Alert | Academic | Hustle | Event | Campus | Opportunity | Poll
  kind   : text | file | square | wide | landscape | video | carousel | portrait
           | tall | grid4 | grid3 | grid2 | link | poll | vertical-video | audio
           | four-three
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# -----------------------------------------------------------------------------
# Constants derived from the schema / product rules.
# -----------------------------------------------------------------------------

#: All campuses served by the multi-campus app.
CAMPUSES: tuple[str, ...] = ("UNILAG", "UI", "OAU", "UNN", "ABU")

#: All post flairs as stored in public.posts.flair.
FLAIRS: tuple[str, ...] = (
    "Alert",
    "Academic",
    "Hustle",
    "Event",
    "Campus",
    "Opportunity",
    "Poll",
)

#: All media kind identifiers (subset of public.posts.kind). Mirrors the app
#: constant `mediaKinds` in src/lib/kampus.ts.
MEDIA_KINDS: frozenset[str] = frozenset({
    "square", "four-three", "landscape", "wide", "portrait", "tall",
    "grid2", "grid3", "grid4", "carousel", "video", "vertical-video",
})

#: High-velocity visual formats that must be capped in guardrails.
VIDEO_KINDS: frozenset[str] = frozenset({"video", "vertical-video"})
#: Carousel is highly engaging but counts toward the 40% rich-media cap too.
RICH_MEDIA_KINDS: frozenset[str] = frozenset({
    "video", "vertical-video", "carousel",
})

#: Interaction weights used to build the collaborative-filtering matrix.
WEIGHT_UPVOTE: int = 2
WEIGHT_BOOKMARK: int = 5
WEIGHT_COMMENT: int = 4


def utcnow() -> datetime:
    """Timezone-aware current timestamp (Postgres timestamptz parity)."""
    return datetime.now(timezone.utc)


@dataclass
class ProfileRow:
    """A single row from public.profiles."""

    id: str
    handle: str
    display_name: str
    campus: str
    bio: str = ""


@dataclass
class PostRow:
    """A single row from public.posts (id is a bigint identity)."""

    id: int
    handle: str
    campus: str
    flair: str
    title: str
    body: str = ""
    kind: str = "text"
    media_url: str | None = None
    votes: int = 0
    comments: int = 0
    created_at: datetime = field(default_factory=utcnow)
    author_id: str | None = None
    # Interaction-state flags populated by the retrieval layer / hot feed RPC.
    has_voted: bool = False
    vote_value: int = 0
    has_bookmarked: bool = False
    # Lightweight score attach point (pre-ranking signal or guardrail-adjusted).
    score: float = 0.0
    _guardrail_penalties: list[str] = field(default_factory=list, repr=False)

    def is_rich_media(self) -> bool:
        """True when this post uses a format that crowds out text alerts."""
        return self.kind in RICH_MEDIA_KINDS


@dataclass
class FollowRow:
    """A single row from public.follows.

    `target` is a free string that maps to a profile handle OR a flair slug.
    """

    user_id: str
    target: str


@dataclass
class UserContext:
    """Everything the pipeline needs to know about the requestor."""

    id: str
    handle: str
    campus: str
    follows: list[FollowRow] = field(default_factory=list)

    @property
    def followed_handles(self) -> set[str]:
        return {f.target.lower() for f in self.follows}

    @property
    def followed_flairs(self) -> set[str]:
        # Flair slugs are case-insensitive and derived from the known flair set.
        lowered = {f.target.lower() for f in self.follows}
        return {f for f in FLAIRS if f.lower() in lowered}


@dataclass
class InteractionRecord:
    """A single observed positive engagement event (weighted for CF)."""

    user_id: str
    post_id: int
    #: Raw kind 'upvote' | 'bookmark' | 'comment'. Used to map to weights.
    kind: str


# -----------------------------------------------------------------------------
# Row parsers (defensive against DB drivers, keep column order agnostic).
# -----------------------------------------------------------------------------


def post_from_row(row: dict) -> PostRow:
    """Build a PostRow from a dict-like row, tolerating already-parsed values."""
    created = row.get("created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    return PostRow(
        id=int(row["id"]),
        author_id=row.get("author_id"),
        handle=row["handle"],
        campus=row["campus"],
        flair=row["flair"],
        title=row["title"],
        body=row.get("body") or "",
        kind=row.get("kind") or "text",
        media_url=row.get("media_url"),
        votes=int(row.get("votes") or 0),
        comments=int(row.get("comments") or 0),
        created_at=created or utcnow(),
        has_voted=bool(row.get("has_voted") or False),
        vote_value=int(row.get("vote_value") or 0),
        has_bookmarked=bool(row.get("has_bookmarked") or False),
    )