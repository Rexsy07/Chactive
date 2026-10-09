-- Fix storage RLS path ownership check for post-media bucket.
-- The previous policy used (storage.foldername(name))[1] which is fragile
-- because storage.foldername()'s array indexing depends on PostgreSQL's
-- 1-based array semantics and the exact nesting depth. Users with 2-level
-- avatar/banner paths (uid/media/avatar.jpg) vs 1-level post paths
-- (uid/filename.jpg) would see inconsistent results depending on whether
-- the foldername array was long enough. Use split_part(name, '/', 1) to
-- unambiguously extract the FIRST path component (always the user id
-- namespace) regardless of subfolder depth. Works for:
--   {uid}/filename.ext        (posts)     -> split_part = {uid}
--   {uid}/media/avatar.ext    (avatars)   -> split_part = {uid}
--   {uid}/media/banner.ext    (banners)   -> split_part = {uid}

DROP POLICY IF EXISTS "Post media own upload" ON storage.objects;
DROP POLICY IF EXISTS "Post media own delete" ON storage.objects;

CREATE POLICY "Post media own upload" ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'post-media'
    AND split_part(name, '/', 1) = auth.uid()::text
  );

CREATE POLICY "Post media own delete" ON storage.objects
  FOR DELETE TO authenticated
  USING (
    bucket_id = 'post-media'
    AND split_part(name, '/', 1) = auth.uid()::text
  );
