-- Close the permissive PostgREST policies present in the initial v0.1 schema.
-- Backend asyncpg connections and service_role keep working; anon and signed-in
-- browser clients must go through the backend's workflow/org authorization.

DROP POLICY IF EXISTS "Allow all for anon" ON public.cas_blobs;
DROP POLICY IF EXISTS "Allow all for anon" ON public.cas_manifests;
DROP POLICY IF EXISTS "Allow all for anon" ON public.cas_refs;
DROP POLICY IF EXISTS "Allow all for anon" ON public.cas_storage_stats;
DROP POLICY IF EXISTS "Allow all for anon" ON public.workflow_run_totals;

DROP POLICY IF EXISTS "Allow all for authenticated" ON public.cas_blobs;
DROP POLICY IF EXISTS "Allow all for authenticated" ON public.cas_manifests;
DROP POLICY IF EXISTS "Allow all for authenticated" ON public.cas_refs;
DROP POLICY IF EXISTS "Allow all for authenticated" ON public.cas_storage_stats;
DROP POLICY IF EXISTS "Allow all for authenticated" ON public.workflow_run_totals;

DROP POLICY IF EXISTS "Allow all for authenticated users" ON public.activity_logs;
DROP POLICY IF EXISTS "Allow all for authenticated users" ON public.approval_requests;

REVOKE ALL ON TABLE
    public.activity_logs,
    public.approval_requests,
    public.cas_blobs,
    public.cas_manifests,
    public.cas_refs,
    public.cas_storage_stats,
    public.workflow_run_totals
FROM anon, authenticated;
