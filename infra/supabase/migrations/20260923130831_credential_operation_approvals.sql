-- Per-connection policy and exact-call approvals reuse the existing resources.
ALTER TABLE public.credentials
    ADD COLUMN approval_operations text[] NOT NULL DEFAULT '{}',
    ADD COLUMN approval_revision bigint NOT NULL DEFAULT 0;

ALTER TABLE public.approval_requests
    ALTER COLUMN workflow_id DROP NOT NULL,
    ALTER COLUMN execution_id DROP NOT NULL,
    ADD COLUMN credential_id uuid REFERENCES public.credentials(id) ON DELETE CASCADE,
    ADD COLUMN action_fingerprint text,
    ADD COLUMN action_payload jsonb,
    ADD COLUMN consumed_at timestamptz,
    ADD COLUMN expires_at timestamptz,
    ADD COLUMN dispatch_after timestamptz NOT NULL DEFAULT now(),
    ADD CONSTRAINT approval_request_target CHECK (
        (credential_id IS NULL AND workflow_id IS NOT NULL AND execution_id IS NOT NULL)
        OR (credential_id IS NOT NULL AND action_fingerprint IS NOT NULL
            AND action_payload IS NOT NULL AND expires_at IS NOT NULL)
    );
CREATE INDEX approval_requests_credential_call ON public.approval_requests
    (credential_id, action_fingerprint, created_at DESC) WHERE credential_id IS NOT NULL AND consumed_at IS NULL;
CREATE INDEX approval_requests_credential_resume ON public.approval_requests
    (execution_id, status) WHERE credential_id IS NOT NULL AND consumed_at IS NULL;
CREATE INDEX approval_requests_credential_dispatch ON public.approval_requests
    (dispatch_after, execution_id) WHERE credential_id IS NOT NULL AND status='approved' AND consumed_at IS NULL;

-- Security policy is never mutable through the public data API or metadata writes.
ALTER TABLE public.credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.credentials, public.approval_requests FROM anon, authenticated;

ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('builder', 'agent', 'alarm', 'credential_approval'));
