-- One row per message the email relay delivers to /email/inbound, keyed by the
-- relay's requestId, which stays the same across the relay queue's retries: a
-- retry of a delivery the backend already received answers "already received"
-- instead of firing a workflow, starting a turn or waking an agent again
-- (utils/email_routes.py, repositories/email_deliveries.py). attempt fences a
-- claim taken over after its lease ran out; rows go 30 days after their claim.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE public.email_inbound_deliveries (
    request_id text PRIMARY KEY,
    attempt uuid NOT NULL DEFAULT gen_random_uuid(),
    claimed_at timestamptz NOT NULL DEFAULT now(),
    received_at timestamptz
);

CREATE INDEX email_inbound_deliveries_claimed_at ON public.email_inbound_deliveries (claimed_at);

ALTER TABLE public.email_inbound_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.email_inbound_deliveries FROM anon, authenticated;
