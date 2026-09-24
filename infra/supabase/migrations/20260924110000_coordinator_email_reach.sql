-- The coordinator's own inbound address shares the namespace with inbound-
-- email trigger nodes, so the two can never collide: one reservation table,
-- a kind column, and at most one coordinator address per account.
ALTER TABLE public.email_reservations ALTER COLUMN workflow_id DROP NOT NULL;
ALTER TABLE public.email_reservations ALTER COLUMN node_id DROP NOT NULL;
ALTER TABLE public.email_reservations ADD COLUMN kind text NOT NULL DEFAULT 'trigger'
    CHECK (kind IN ('trigger', 'coordinator'));
ALTER TABLE public.email_reservations ADD CONSTRAINT email_reservations_kind_target
    CHECK ((kind = 'trigger') = (workflow_id IS NOT NULL AND node_id IS NOT NULL));
CREATE UNIQUE INDEX email_reservations_one_coordinator
    ON public.email_reservations (user_id) WHERE kind = 'coordinator';
