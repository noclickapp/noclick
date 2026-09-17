-- A call to a number a workflow owns runs the wired agent as `phone_call`
-- (each delegated request on the call, and the finished call as the phone
-- node's event). The schema-vs-code test pins the full set of sources.

ALTER TABLE public.workflow_executions
    DROP CONSTRAINT IF EXISTS workflow_executions_trigger_source_check;

ALTER TABLE public.workflow_executions
    ADD CONSTRAINT workflow_executions_trigger_source_check
    CHECK (trigger_source IN ('manual', 'webhook', 'cron', 'mcp', 'api', 'email',
                              'agent_turn', 'shared_agent', 'builder_event',
                              'agent_email_reply', 'error_handler', 'graph_event',
                              'phone_call'));
