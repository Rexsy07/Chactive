DROP POLICY IF EXISTS "Own follows read" ON public.follows;
CREATE POLICY "Signed-in students can view follows"
ON public.follows
FOR SELECT
TO authenticated
USING (true);