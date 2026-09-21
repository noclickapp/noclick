CREATE TABLE public.coordinator_publications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    builder_conversation_id text UNIQUE,
    instructions text CHECK (length(instructions) BETWEEN 1 AND 16000),
    options jsonb NOT NULL,
    send_to_phone boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (status IN ('queued', 'building', 'waiting', 'ready', 'publishing', 'completed', 'failed', 'cancelled')),
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_until timestamptz,
    notified_at timestamptz,
    notification_token uuid,
    notification_lease_until timestamptz,
    phone_state text CHECK (phone_state IN ('sending', 'sent', 'failed', 'uncertain')),
    delivery_error text,
    CHECK ((instructions IS NULL) = (builder_conversation_id IS NULL))
);
CREATE UNIQUE INDEX coordinator_publications_active_workflow ON public.coordinator_publications (workflow_id)
    WHERE status IN ('queued', 'building', 'waiting', 'ready', 'publishing');
CREATE INDEX coordinator_publications_user_recent ON public.coordinator_publications (user_id, created_at DESC);
CREATE INDEX coordinator_publications_pending ON public.coordinator_publications (created_at)
    WHERE status IN ('queued', 'ready');
CREATE INDEX coordinator_publications_notifications ON public.coordinator_publications (updated_at)
    WHERE status IN ('completed', 'failed', 'cancelled') AND notified_at IS NULL;
CREATE INDEX coordinator_publications_leases ON public.coordinator_publications (lease_until)
    WHERE status IN ('building', 'waiting', 'publishing');
ALTER TABLE public.coordinator_publications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_publications FROM anon, authenticated;
