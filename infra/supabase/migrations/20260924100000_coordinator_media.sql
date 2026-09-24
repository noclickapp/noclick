-- The account coordinator makes images and videos that belong to the
-- account, not to a workflow: a resource may have no workflow.
ALTER TABLE public.workflow_resources ALTER COLUMN workflow_id DROP NOT NULL;

-- A video takes minutes: it is a coordinator job, polled by the per-minute
-- coordinator reconcile and billed on completion.
ALTER TABLE public.coordinator_jobs DROP CONSTRAINT coordinator_jobs_kind_check;
ALTER TABLE public.coordinator_jobs ADD CONSTRAINT coordinator_jobs_kind_check
    CHECK (kind IN ('build', 'agent', 'video'));
