-- Two "service" policies were created without a TO clause, so they applied to
-- every role including anon: the public key could read and delete every row.
-- service_role bypasses RLS and needs no policy; the backend connects as postgres.
DROP POLICY IF EXISTS "Service role full access" ON public.recurring_charges;
DROP POLICY IF EXISTS workflow_embeddings_service_all ON public.workflow_embeddings;

REVOKE ALL ON TABLE public.recurring_charges, public.workflow_embeddings FROM anon, authenticated;

-- Client-era leftover: any signed-up user could insert organization rows with a
-- tier of their choosing. Orgs are created by the backend (repositories/organization.py).
DROP POLICY IF EXISTS "Authenticated users can create organizations" ON public.organizations;
