-- The OAuth clients NoClick registered with a vendor MCP server's authorization server (RFC 7591 Dynamic Client
-- Registration), one per authorization server and redirect URI (nodes/oauth/mcp_connect.py): every person who
-- connects that integration through MCP signs in through the one client, never a registration of their own.
-- client_secret_sealed holds a secret the server issued, sealed with the credential key; registration keeps the
-- rest of the server's answer. Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE IF NOT EXISTS public.mcp_oauth_clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer text NOT NULL,
    redirect_uri text NOT NULL,
    client_id text NOT NULL,
    client_secret_sealed text,
    registration jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (issuer, redirect_uri)
);

ALTER TABLE public.mcp_oauth_clients ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.mcp_oauth_clients FROM anon, authenticated;
