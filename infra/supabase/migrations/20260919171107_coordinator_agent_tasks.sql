-- Durable coordinator delegations: queued work survives a container restart,
-- and asynchronous agent responses resolve the exact delivery that requested them.
CREATE TABLE public.coordinator_agent_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    node_id text NOT NULL,
    agent_name text NOT NULL,
    conversation_key text NOT NULL,
    parent_task_id uuid REFERENCES public.coordinator_agent_tasks(id) ON DELETE SET NULL,
    message text NOT NULL CHECK (length(message) BETWEEN 1 AND 16000),
    channel text NOT NULL DEFAULT 'web',
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'waiting', 'completed', 'failed')),
    execution_id uuid REFERENCES public.workflow_executions(id) ON DELETE SET NULL,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    notified_at timestamptz,
    delivery_error text
);
CREATE INDEX coordinator_agent_tasks_user_recent
    ON public.coordinator_agent_tasks (user_id, created_at DESC);
CREATE INDEX coordinator_agent_tasks_queue
    ON public.coordinator_agent_tasks (created_at) WHERE status = 'queued';
CREATE INDEX coordinator_agent_tasks_active_conversation
    ON public.coordinator_agent_tasks (conversation_key, created_at)
    WHERE status IN ('queued', 'running', 'waiting');
CREATE INDEX coordinator_agent_tasks_execution
    ON public.coordinator_agent_tasks (execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX coordinator_agent_tasks_pending_notifications
    ON public.coordinator_agent_tasks (updated_at)
    WHERE status IN ('completed', 'failed') AND notified_at IS NULL;
CREATE INDEX coordinator_agent_tasks_leases
    ON public.coordinator_agent_tasks (lease_until) WHERE status IN ('running', 'waiting');

ALTER TABLE public.coordinator_agent_tasks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_agent_tasks FROM anon, authenticated;

ALTER TABLE public.workflow_executions DROP CONSTRAINT workflow_executions_trigger_source_check;
ALTER TABLE public.workflow_executions ADD CONSTRAINT workflow_executions_trigger_source_check
    CHECK (trigger_source IN ('manual', 'webhook', 'cron', 'mcp', 'api', 'email',
        'agent_turn', 'shared_agent', 'builder_event', 'agent_email_reply',
        'error_handler', 'graph_event', 'phone_call', 'coordinator'));
