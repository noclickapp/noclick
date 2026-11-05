-- Each account's own node output shapes, what its own runs and deliveries had. workflow_node_output_schemas pools
-- every account's and names none, and a shape can hold one account's own field names, so anything a person or a
-- client outside NoClick reads comes from here (utils/node_schema_tracker.py, repositories/node_output_schemas.py).
-- Filled as outputs arrive; nothing older can be told apart by account.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE public.account_node_output_schemas (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    schema_hash text NOT NULL,
    node_type text NOT NULL,
    node_operation text NOT NULL,
    output_schema jsonb NOT NULL,
    -- A delivery carried it, as it arrived: all an event's public shape may show.
    delivered boolean NOT NULL DEFAULT false,
    occurrence_count bigint NOT NULL DEFAULT 1,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, schema_hash)
);

CREATE INDEX account_node_output_schemas_read
    ON public.account_node_output_schemas (user_id, node_type, node_operation, occurrence_count DESC);

ALTER TABLE public.account_node_output_schemas ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.account_node_output_schemas FROM anon, authenticated;
