-- The owner can turn off mail to their coordinator's address without giving the
-- address up: while inbound_paused_at is set, mail to it starts no turn
-- (coder/coordinator/email_channel.receive). Mail the coordinator sends the owner
-- is unaffected. Backend-only, like the rest of the table: RLS stays on with no
-- policy, and the API roles hold no grants.
ALTER TABLE public.email_reservations ADD COLUMN inbound_paused_at timestamptz;

ALTER TABLE public.email_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.email_reservations FROM anon, authenticated;
