-- Model-provider keys an operator saves in Settings — or inline, when the
-- builder asks for the one it is missing. Applied to the backend's environment
-- at startup; backend-only, like instance_oauth_apps.

CREATE TABLE IF NOT EXISTS public.instance_provider_keys (
    env_var text PRIMARY KEY,
    value_encrypted text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL
);

ALTER TABLE public.instance_provider_keys ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.instance_provider_keys FROM anon, authenticated;
