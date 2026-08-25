-- Provider-neutral usage accounting.
--
-- The community runtime does not ship a payment-provider customer schema,
-- product catalogue, plan allowances, add-ons, or cost-allocation policy.  A
-- small compatibility row supplies the policy label used by shared handlers;
-- the event table records operator-visible work without deciding how to bill it.

CREATE TABLE IF NOT EXISTS public.user_billing (
    id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    subscription_tier text NOT NULL DEFAULT 'community',
    organization_id uuid REFERENCES public.organizations(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.user_billing IS
    'Compatibility policy labels for optional operator extensions; no payment data.';

CREATE INDEX IF NOT EXISTS idx_user_billing_org_id
    ON public.user_billing (organization_id)
    WHERE organization_id IS NOT NULL;


CREATE TABLE IF NOT EXISTS public.user_usage_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    total_cost numeric(18,10) NOT NULL CHECK (total_cost >= 0),
    usage_type varchar(100) NOT NULL,
    usage_subtype varchar(100) NOT NULL,
    quantity numeric(18,4) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit_type varchar(50),
    user_resource boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    organization_id uuid REFERENCES public.organizations(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.user_usage_events IS
    'Observed usage units and optional provider cost; no charging allocation.';

CREATE INDEX IF NOT EXISTS idx_usage_user_created
    ON public.user_usage_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_user_date_type_subtype
    ON public.user_usage_events (user_id, created_at DESC, usage_type, usage_subtype)
    INCLUDE (total_cost, quantity, user_resource);
CREATE INDEX IF NOT EXISTS idx_usage_events_org
    ON public.user_usage_events (organization_id, created_at DESC)
    WHERE organization_id IS NOT NULL;


ALTER TABLE public.user_billing ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_usage_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own billing" ON public.user_billing;
DROP POLICY IF EXISTS "Service role can do everything on billing" ON public.user_billing;
DROP POLICY IF EXISTS "Users can view own policy label" ON public.user_billing;
CREATE POLICY "Users can view own policy label" ON public.user_billing
    FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "Service role can manage policy labels" ON public.user_billing;
CREATE POLICY "Service role can manage policy labels" ON public.user_billing
    TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Users can view own usage events" ON public.user_usage_events;
CREATE POLICY "Users can view own usage events" ON public.user_usage_events
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role can do everything on usage events" ON public.user_usage_events;
DROP POLICY IF EXISTS "Service role can manage usage events" ON public.user_usage_events;
CREATE POLICY "Service role can manage usage events" ON public.user_usage_events
    TO service_role USING (true) WITH CHECK (true);

GRANT SELECT ON TABLE public.user_billing TO supabase_auth_admin;
