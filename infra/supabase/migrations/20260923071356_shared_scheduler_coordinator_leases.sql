-- Operational ownership, never semantic memory. No transaction stays open
-- while a model/tool is running. A unique owner fences expired workers.
ALTER TABLE public.conversations ADD COLUMN coordinator_lease_owner uuid;
ALTER TABLE public.conversations ADD COLUMN coordinator_lease_until timestamptz;
CREATE INDEX coordinator_active_leases ON public.conversations(coordinator_lease_until)
    WHERE coordinator_lease_owner IS NOT NULL;

-- Durable inbox/outbox registration recovery; timing belongs to the shared scheduler.
ALTER TABLE public.coordinator_wakeups ADD COLUMN dispatch_after timestamptz NOT NULL DEFAULT now();
CREATE INDEX coordinator_dispatch_pending ON public.coordinator_wakeups(dispatch_after)
    WHERE status IN ('queued','running','ready','delivering');
CREATE INDEX coordinator_alarm_occurrences ON public.coordinator_wakeups(alarm_id,created_at)
    WHERE alarm_id IS NOT NULL;
CREATE INDEX coordinator_wakeup_retention ON public.coordinator_wakeups(created_at)
    WHERE status IN ('done','skipped');
