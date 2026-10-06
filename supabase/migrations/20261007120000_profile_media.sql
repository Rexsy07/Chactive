-- Add avatar/banner columns to profiles
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS avatar_url text;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS banner_url text;

-- Fix storage RLS for post-media uploads.
-- The old policies checked (storage.foldername(name))[1], which is the SECOND
-- folder component. All upload paths (post, avatar, banner) are namespaced by
-- the user's id as the FIRST folder, so the policies were broken and blocked
-- every upload. Use [0] so {uid}/... matches for posts, avatars and banners.
DROP POLICY IF EXISTS "Post media own upload" ON storage.objects;
DROP POLICY IF EXISTS "Post media own delete" ON storage.objects;

CREATE POLICY "Post media own upload" ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'post-media' AND (storage.foldername(name))[1] = auth.uid()::text);

CREATE POLICY "Post media own delete" ON storage.objects
  FOR DELETE TO authenticated
  USING (bucket_id = 'post-media' AND (storage.foldername(name))[1] = auth.uid()::text);