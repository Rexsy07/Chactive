-- =============================================================================
-- HOT CAMPUS FEED : STAGE 1 PL/pgSQL DECAY RANKER
-- -----------------------------------------------------------------------------
-- Deterministic, localized ranking for the "Hot Campus Feed".
--
-- Scoring model (adapted Hacker News gravity):
--   Score = (NetVotes + (Comments * 1.5)) / (AgeHours + 2) ^ 1.8
--
-- Variable translation vs. the actual schema (public.posts):
--   NetVotes  -> posts.votes            (aggregate maintained by triggers)
--   Comments  -> posts.comments         (count maintained by triggers)
--   AgeHours  -> EXTRACT(EPOCH FROM (now() - posts.created_at)) / 3600
--
-- The query joins public.post_votes and public.bookmarks (LEFT lateral) so the
-- requesting user's local interaction state is returned as booleans without
-- changing row multiplicity.
-- =============================================================================

-- Partial index: only hot-ranked fields are needed for a given campus. Because
-- posts are inserted with monotonically increasing ids and created_at, an index
-- on (campus, created_at DESC) lets the planner satisfy the time filter and the
-- ORDER BY via a single backward index scan plus a top-N heap sort of the score.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND indexname = 'posts_campus_created_idx'
  ) THEN
    CREATE INDEX posts_campus_created_idx
      ON public.posts (campus, created_at DESC);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND indexname = 'post_votes_user_idx'
  ) THEN
    -- Secondary lookup used by <user_id> = p_user_id lateral probes.
    CREATE INDEX post_votes_user_idx ON public.post_votes (user_id, post_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND indexname = 'bookmarks_user_idx'
  ) THEN
    CREATE INDEX bookmarks_user_idx ON public.bookmarks (user_id, post_id);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public.get_hot_campus_feed(
  p_user_id UUID,
  p_campus   TEXT,
  p_limit    INT,
  p_offset   INT
)
RETURNS TABLE (
  id            BIGINT,
  author_id     UUID,
  handle        TEXT,
  campus        TEXT,
  flair         TEXT,
  title         TEXT,
  body          TEXT,
  kind          TEXT,
  media_url     TEXT,
  votes         INT,
  comments      INT,
  created_at    TIMESTAMPTZ,
  score         DOUBLE PRECISION,
  has_voted     BOOLEAN,
  vote_value    SMALLINT,
  has_bookmarked BOOLEAN
)
LANGUAGE plpgsql
VOLATILE
SET search_path = public
SET row_security = off          -- SECURITY INVOKER-grade read; caller must hold SELECT.
AS $$
DECLARE
  v_max_age_hours CONSTANT DOUBLE PRECISION := 24.0 * 365.0; -- ~1 year decay floor.
  v_comment_mult  CONSTANT DOUBLE PRECISION := 1.5;          -- community friction weight.
  v_gravity       CONSTANT DOUBLE PRECISION := 1.8;          -- HN gravity exponent.
  v_age_offset    CONSTANT DOUBLE PRECISION := 2.0;          -- +2 prevents div-by-zero at birth.
BEGIN
  IF p_campus IS NULL OR btrim(p_campus) = '' THEN
    RAISE EXCEPTION 'p_campus must be a non-empty campus identifier';
  END IF;
  IF p_limit <= 0 THEN
    RAISE EXCEPTION 'p_limit must be positive (got %)', p_limit;
  END IF;
  IF p_offset < 0 THEN
    RAISE EXCEPTION 'p_offset cannot be negative (got %)', p_offset;
  END IF;

  RETURN QUERY
  WITH scoped AS (
    -- Localization + time pre-filter. Overly old content has score near zero, so
    -- clipping AgeHours bounds the scan and keeps the index useful.
    SELECT
      p.id,
      p.author_id,
      p.handle,
      p.campus,
      p.flair,
      p.title,
      p.body,
      p.kind,
      p.media_url,
      p.votes,
      p.comments,
      p.created_at,
      p.votes + (p.comments * v_comment_mult)              AS raw_signal,
      LEAST(
        EXTRACT(EPOCH FROM (now() - p.created_at)) / 3600.0,
        v_max_age_hours
      )                                                    AS age_hours
    FROM public.posts p
    WHERE p.campus = p_campus
      AND p.created_at > now() - (v_max_age_hours * interval '1 hour')
  ),
  scored AS (
    SELECT
      s.id,
      s.author_id,
      s.handle,
      s.campus,
      s.flair,
      s.title,
      s.body,
      s.kind,
      s.media_url,
      s.votes,
      s.comments,
      s.created_at,
      -- Guarded denominator: age_hours is always >= 0 (or 0 at birth), so
      -- (age_hours + 2) is always >= 2, never zero. GREATEST is a final safety net.
      (s.raw_signal)
        / POWER(GREATEST(s.age_hours, 0.0) + v_age_offset, v_gravity) AS score
    FROM scoped s
  )
  SELECT
    st.id,
    st.author_id,
    st.handle,
    st.campus,
    st.flair,
    st.title,
    st.body,
    st.kind,
    st.media_url,
    st.votes,
    st.comments,
    st.created_at,
    st.score,
    (pv.value IS NOT NULL)        AS has_voted,
    COALESCE(pv.value, 0::smallint)    AS vote_value,
    (bm.post_id IS NOT NULL)      AS has_bookmarked
  FROM scored st
  -- LATERAL probes are run once per survivor row. Each key is the composite PK
  -- (user_id, post_id) backed by an index, so these are point lookups, not scans,
  -- and cannot fan out the candidate result set.
  LEFT JOIN LATERAL (
    SELECT value FROM public.post_votes pv
    WHERE pv.user_id = p_user_id AND pv.post_id = st.id
  ) pv ON true
  LEFT JOIN LATERAL (
    SELECT post_id FROM public.bookmarks bm
    WHERE bm.user_id = p_user_id AND bm.post_id = st.id
  ) bm ON true
  ORDER BY st.score DESC, st.id DESC
  LIMIT p_limit OFFSET p_offset;
END;
$$;

-- Useful if callers use the RPC directly and we need a manual prefix guard.
GRANT EXECUTE ON FUNCTION public.get_hot_campus_feed(UUID, TEXT, INT, INT) TO authenticated, service_role;