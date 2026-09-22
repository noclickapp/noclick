CREATE TABLE public.builder_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    conversation_id text NOT NULL UNIQUE,
    instructions text CHECK (length(instructions) BETWEEN 1 AND 16000),
    publish jsonb,
    origin jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'waiting_for_input', 'completed', 'failed', 'cancelled')),
    phase text NOT NULL CHECK (phase IN ('building', 'publishing')),
    attempt_id uuid,
    pending_ask jsonb,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_until timestamptz,
    reply_conversation_id text,
    reply_node_id text,
    send_to_phone boolean NOT NULL DEFAULT false,
    notified_at timestamptz,
    notification_token uuid,
    notification_lease_until timestamptz,
    phone_state text CHECK (phone_state IN ('sending', 'sent', 'failed', 'uncertain')),
    delivery_error text,
    CHECK (instructions IS NOT NULL OR publish IS NOT NULL),
    CHECK (phase <> 'publishing' OR publish IS NOT NULL)
);
CREATE UNIQUE INDEX builder_requests_active_workflow ON public.builder_requests (workflow_id)
    WHERE status IN ('queued', 'running', 'waiting_for_input');
CREATE INDEX builder_requests_user_recent ON public.builder_requests (user_id, created_at DESC);
CREATE INDEX builder_requests_pending ON public.builder_requests (created_at) WHERE status='queued';
CREATE INDEX builder_requests_notifications ON public.builder_requests (updated_at)
    WHERE status IN ('completed', 'failed', 'cancelled') AND notified_at IS NULL AND reply_conversation_id IS NOT NULL;
CREATE INDEX builder_requests_leases ON public.builder_requests (lease_until)
    WHERE status IN ('running', 'waiting_for_input');
ALTER TABLE public.builder_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.builder_requests FROM anon, authenticated;
