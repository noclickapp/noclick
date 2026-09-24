-- Long-running credential operations use the same durable continuation inbox.
-- No workflow, synthetic execution, or separate completion queue is needed.
ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_wakeups_source_check;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_wakeups_source_check
    CHECK (source IN ('job','alarm','signal','credential_approval','link','operation'));
ALTER TABLE public.coordinator_wakeups DROP CONSTRAINT coordinator_link_wait_target;
ALTER TABLE public.coordinator_wakeups ADD CONSTRAINT coordinator_link_wait_target
    CHECK (status <> 'waiting' OR (source IN ('link','operation') AND await_key IS NOT NULL AND await_expires_at IS NOT NULL));
