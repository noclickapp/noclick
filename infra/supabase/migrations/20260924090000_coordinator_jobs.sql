-- One ledger for the work the account coordinator starts and then waits on.
-- `kind` names the work; `spec` holds what was asked, which never changes.
-- Columns a constraint, index or foreign key needs stay columns.
CREATE TABLE public.coordinator_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('build', 'agent')),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'waiting', 'completed', 'failed', 'cancelled')),
    spec jsonb NOT NULL DEFAULT '{}'::jsonb,
    origin jsonb NOT NULL DEFAULT '{}'::jsonb,
    workflow_id uuid REFERENCES public.workflows(id) ON DELETE CASCADE,
    node_id text,
    conversation_key text,
    parent_job_id uuid REFERENCES public.coordinator_jobs(id) ON DELETE SET NULL,
    execution_id uuid REFERENCES public.workflow_executions(id) ON DELETE SET NULL,
    phase text CHECK (phase IN ('building', 'publishing')),
    attempt_id uuid,
    pending_ask jsonb,
    lease_until timestamptz,
    result jsonb,
    error text,
    -- Where the outcome goes: a continuation wakes the coordinator; without
    -- one the result is posted to reply_conversation_id as a notification.
    continuation jsonb,
    send_to_phone boolean NOT NULL DEFAULT false,
    reply_conversation_id text,
    reply_node_id text,
    notified_at timestamptz,
    notification_token uuid,
    notification_lease_until timestamptz,
    phone_state text CHECK (phone_state IN ('sending', 'sent', 'failed', 'uncertain')),
    delivery_error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (kind <> 'build' OR (workflow_id IS NOT NULL AND conversation_key IS NOT NULL AND phase IS NOT NULL
        AND (spec ? 'instructions' OR spec ? 'publish') AND (phase <> 'publishing' OR spec ? 'publish'))),
    CHECK (kind <> 'agent' OR (workflow_id IS NOT NULL AND node_id IS NOT NULL AND conversation_key IS NOT NULL
        AND spec ? 'message' AND status <> 'cancelled'))
);
CREATE UNIQUE INDEX coordinator_jobs_build_conversation ON public.coordinator_jobs (conversation_key)
    WHERE kind = 'build';
CREATE UNIQUE INDEX coordinator_jobs_active_build ON public.coordinator_jobs (workflow_id)
    WHERE kind = 'build' AND status IN ('queued', 'running', 'waiting');
CREATE INDEX coordinator_jobs_user_recent ON public.coordinator_jobs (user_id, created_at DESC);
CREATE INDEX coordinator_jobs_queue ON public.coordinator_jobs (kind, created_at) WHERE status = 'queued';
CREATE INDEX coordinator_jobs_leases ON public.coordinator_jobs (lease_until) WHERE status IN ('running', 'waiting');
CREATE INDEX coordinator_jobs_pending_notifications ON public.coordinator_jobs (updated_at)
    WHERE status IN ('completed', 'failed', 'cancelled') AND notified_at IS NULL;
CREATE INDEX coordinator_jobs_agent_conversation ON public.coordinator_jobs (conversation_key, created_at)
    WHERE kind = 'agent' AND status IN ('queued', 'running', 'waiting');
CREATE INDEX coordinator_jobs_execution ON public.coordinator_jobs (execution_id) WHERE execution_id IS NOT NULL;
ALTER TABLE public.coordinator_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_jobs FROM anon, authenticated;

-- Existing work moves across with its id, so inbox rows keep pointing at it.
INSERT INTO public.coordinator_jobs (
    id, user_id, kind, status, spec, origin, workflow_id, conversation_key, phase, attempt_id, pending_ask,
    lease_until, result, error, continuation, send_to_phone, reply_conversation_id, reply_node_id, notified_at,
    notification_token, notification_lease_until, phone_state, delivery_error, created_at, updated_at)
SELECT id, user_id, 'build',
       CASE status WHEN 'waiting_for_input' THEN 'waiting' ELSE status END,
       jsonb_strip_nulls(jsonb_build_object('instructions', instructions, 'publish', publish)),
       origin - 'continuation', workflow_id, conversation_id, phase, attempt_id, pending_ask,
       lease_until, result, error, origin -> 'continuation', send_to_phone, reply_conversation_id, reply_node_id,
       notified_at, notification_token, notification_lease_until, phone_state, delivery_error, created_at, updated_at
FROM public.builder_requests;

INSERT INTO public.coordinator_jobs (
    id, user_id, kind, status, spec, origin, workflow_id, node_id, conversation_key, execution_id,
    lease_until, result, error, continuation, send_to_phone, notified_at, delivery_error, created_at, updated_at)
SELECT id, user_id, 'agent', status, jsonb_build_object('agent_name', agent_name, 'message', message),
       '{"source": "coordinator"}'::jsonb, workflow_id, node_id, conversation_key, execution_id,
       lease_until, result, error, continuation, channel <> 'web', notified_at, delivery_error, created_at, updated_at
FROM public.coordinator_agent_tasks;
UPDATE public.coordinator_jobs j SET parent_job_id = t.parent_task_id
FROM public.coordinator_agent_tasks t WHERE t.id = j.id AND t.parent_task_id IS NOT NULL;

ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
UPDATE public.coordinator_wakeups SET source = 'job' WHERE source IN ('builder', 'agent');
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('job', 'alarm'));

DROP TABLE public.builder_requests;
DROP TABLE public.coordinator_agent_tasks;
