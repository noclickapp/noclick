-- Completion events wake the same coordinator; they never encode a future action.
CREATE TABLE public.coordinator_wakeups (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('builder', 'agent')),
    source_id uuid NOT NULL,
    context jsonb NOT NULL,
    payload jsonb NOT NULL,
    send_to_phone boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','ready','delivering','done','skipped')),
    attempt_id uuid,
    started_at timestamptz,
    lease_until timestamptz,
    response text,
    delivery_error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(source, source_id)
);
CREATE INDEX coordinator_wakeups_pending ON public.coordinator_wakeups (status, created_at)
    WHERE status IN ('queued','running','ready','delivering');
CREATE INDEX coordinator_wakeups_user ON public.coordinator_wakeups (user_id);
ALTER TABLE public.coordinator_wakeups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_wakeups FROM anon, authenticated;

-- Null preserves the notification-only behavior of requests created before rollout.
ALTER TABLE public.coordinator_agent_tasks ADD COLUMN continuation jsonb;
