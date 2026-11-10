-- idx_cas_manifests_workflow (workflow_id) duplicates the leading column of
-- idx_cas_manifests_node_recency (workflow_id, node_id, created_at DESC): the
-- cascade from workflows and every lookup by workflow use that index without it,
-- and each manifest written or deleted updated one index more.
--
-- CONCURRENTLY, so dropping it never blocks those writes. It must stay this
-- file's only statement: the Supabase CLI sends a migration as one pipeline,
-- which CONCURRENTLY accepts only as its first command, and the test fixture
-- runs the file as one query string.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_cas_manifests_workflow;
