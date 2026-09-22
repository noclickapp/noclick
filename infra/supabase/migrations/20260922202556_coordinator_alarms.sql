-- Scheduled messages use the same durable inbox as action completions.
ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('builder', 'agent', 'alarm'));
ALTER TABLE public.coordinator_wakeups ADD COLUMN not_before timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.coordinator_wakeups ADD COLUMN alarm_id uuid;
ALTER TABLE public.coordinator_wakeups ADD COLUMN admitted_at timestamptz;
CREATE INDEX coordinator_wakeups_due ON public.coordinator_wakeups (not_before, created_at)
    WHERE status='queued';
CREATE INDEX coordinator_alarm_admissions ON public.coordinator_wakeups (user_id, admitted_at)
    WHERE source='alarm';
CREATE INDEX coordinator_alarm_series ON public.coordinator_wakeups (user_id, alarm_id)
    WHERE source='alarm';
-- RLS and revoked API grants are inherited from the original private inbox.
