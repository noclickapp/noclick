-- A hosted platform agent's turn records what started it: a message someone
-- sent, a text, call or email, a trigger's event, a schedule, the agent's own
-- wake-up, or a test run. The open edition keeps the same set of sources as
-- the hosted schema; the schema-vs-code test pins it.

ALTER TABLE public.workflow_executions
    DROP CONSTRAINT IF EXISTS workflow_executions_trigger_source_check;

ALTER TABLE public.workflow_executions
    ADD CONSTRAINT workflow_executions_trigger_source_check
    CHECK (trigger_source IN ('manual', 'webhook', 'cron', 'mcp', 'api', 'email',
                              'agent_turn', 'shared_agent', 'builder_event',
                              'agent_email_reply', 'error_handler', 'graph_event',
                              'phone_call', 'coordinator', 'agent_message',
                              'agent_text', 'agent_event', 'agent_schedule',
                              'agent_wakeup', 'agent_test'));
