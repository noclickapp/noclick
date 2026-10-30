-- What a write of a workflow's graph sets in motion outside it (utils/workflow_reconcile.py), recorded in the
-- write's own transaction and run after it commits, by the workflow's one worker (its lease,
-- workflow_reconcile_leases), in order per step, retried until done: no teardown or registration runs on a
-- request's path, and one cut off resumes. One given up on ('failed') is retried daily until a newer job covering
-- its steps succeeds ('superseded'). old_nodes and new_nodes are the steps the write touched (removed, added,
-- changed), by id, as they were and as it left them; deleted names the steps a canvas said it deleted (NULL: the
-- steps the write removed); from_version and to_version are the graph versions the write moved between.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE IF NOT EXISTS public.workflow_reconcile_jobs (
    id bigserial PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    old_nodes jsonb NOT NULL DEFAULT '{}',
    new_nodes jsonb NOT NULL DEFAULT '{}',
    deleted text[],
    from_version bigint NOT NULL,
    to_version bigint NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'done', 'failed', 'superseded')),
    attempts integer NOT NULL DEFAULT 0,
    retry_at timestamptz NOT NULL DEFAULT now(),
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    done_at timestamptz
);

CREATE INDEX IF NOT EXISTS workflow_reconcile_jobs_queued ON public.workflow_reconcile_jobs (workflow_id, id)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS workflow_reconcile_jobs_done_at ON public.workflow_reconcile_jobs (done_at)
    WHERE status <> 'queued';
-- The staff Reliability view's read: jobs failing (retrying) or given up on, oldest first.
CREATE INDEX IF NOT EXISTS workflow_reconcile_jobs_unfinished ON public.workflow_reconcile_jobs (created_at)
    WHERE status = 'failed' OR (status = 'queued' AND attempts > 0);

ALTER TABLE public.workflow_reconcile_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.workflow_reconcile_jobs FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.workflow_reconcile_jobs_id_seq FROM anon, authenticated;

-- The graph versions a reconcile's own writes produced (a trigger's webhook fields, its schedule's mirrors):
-- an edit made on a version is still made on it when every version after it is one of these.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE IF NOT EXISTS public.workflow_reconcile_versions (
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    version bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workflow_id, version)
);

CREATE INDEX IF NOT EXISTS workflow_reconcile_versions_created_at ON public.workflow_reconcile_versions (created_at);

ALTER TABLE public.workflow_reconcile_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.workflow_reconcile_versions FROM anon, authenticated;
