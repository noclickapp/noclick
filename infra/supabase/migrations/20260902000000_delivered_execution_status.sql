-- Allow the terminal 'delivered' execution status: a run whose agent handed
-- its turn to a sandbox keeps its row (hidden from run history) so the
-- delivery's node outputs and tool calls stay addressable by execution id.
ALTER TABLE public.workflow_executions
    DROP CONSTRAINT IF EXISTS workflow_executions_status_check;

ALTER TABLE public.workflow_executions
    ADD CONSTRAINT workflow_executions_status_check
    CHECK (status IN ('running', 'completed', 'error', 'awaiting_approval', 'awaiting_delay', 'delivered'));
