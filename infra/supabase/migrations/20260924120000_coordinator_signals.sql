-- Things elsewhere in the account that wake the coordinator: a workflow run
-- failed, or an agent node messaged it. Failures of one workflow within a
-- window fold into one signal (repeats); only a capped number of signals a
-- day wake the coordinator, so a high-frequency workflow can't flood it.
CREATE TABLE public.coordinator_signals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('run_failure', 'agent_message')),
    workflow_id uuid REFERENCES public.workflows(id) ON DELETE CASCADE,
    node_id text,
    execution_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    repeats integer NOT NULL DEFAULT 0,
    woke boolean NOT NULL DEFAULT false,
    notified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX coordinator_signals_user ON public.coordinator_signals (user_id, created_at DESC);
CREATE INDEX coordinator_signals_workflow ON public.coordinator_signals (workflow_id, kind, created_at DESC);
ALTER TABLE public.coordinator_signals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_signals FROM anon, authenticated;
GRANT ALL ON public.coordinator_signals TO service_role;

ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('job', 'alarm', 'signal'));
