-- A purchase the coordinator hands its owner is a job it waits on: the job id
-- is the one-tap link (/pay/{id}), the Stripe webhook records the payment on
-- the job, and the per-minute poll closes paid jobs (waking the coordinator)
-- and retires links nobody used.
ALTER TABLE public.coordinator_jobs DROP CONSTRAINT coordinator_jobs_kind_check;
ALTER TABLE public.coordinator_jobs ADD CONSTRAINT coordinator_jobs_kind_check
    CHECK (kind IN ('build', 'agent', 'video', 'purchase'));
ALTER TABLE public.coordinator_jobs ADD CONSTRAINT coordinator_jobs_purchase_spec
    CHECK (kind <> 'purchase' OR (spec ? 'kind' AND spec ? 'billing_period' AND spec ? 'price_usd' AND spec ? 'expires_at'));
CREATE INDEX coordinator_jobs_open_purchases ON public.coordinator_jobs (created_at)
    WHERE kind = 'purchase' AND status = 'waiting';
