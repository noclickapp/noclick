-- Paid credentials use the existing request lifecycle. A durable provisioning
-- claim prevents a repeated confirmation from repeating an external purchase.
ALTER TABLE public.credential_requests
    ADD COLUMN purchase_quote jsonb,
    ADD COLUMN provisioning_started_at timestamptz,
    ADD COLUMN provision_error text;
ALTER TABLE public.credential_requests DROP CONSTRAINT credential_requests_status_check;
ALTER TABLE public.credential_requests ADD CONSTRAINT credential_requests_status_check
    CHECK (status IN ('pending', 'provisioning', 'fulfilled', 'expired', 'cancelled'));

-- Completed paid requests retain their token and result: requesting another
-- number must not invalidate a receipt or a builder's existing answer link.
ALTER TABLE public.credential_requests DROP CONSTRAINT unique_pending_request;
CREATE UNIQUE INDEX credential_requests_external_unique
    ON public.credential_requests (requester_id, target_email, credential_type)
    WHERE credential_type <> 'phone_number';
CREATE UNIQUE INDEX credential_requests_phone_active_unique
    ON public.credential_requests (requester_id, target_email)
    WHERE credential_type = 'phone_number' AND status IN ('pending', 'provisioning');

-- Requests are backend-owned. Direct client writes must not reset a purchase
-- claim, change a server quote, or forge fulfillment through PostgREST.
ALTER TABLE public.credential_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS credential_requests_select ON public.credential_requests;
DROP POLICY IF EXISTS credential_requests_insert ON public.credential_requests;
DROP POLICY IF EXISTS credential_requests_update ON public.credential_requests;
REVOKE ALL ON TABLE public.credential_requests FROM anon, authenticated;
