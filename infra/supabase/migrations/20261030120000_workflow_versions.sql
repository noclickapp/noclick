-- Each write of a workflow's graph (coder/workflow/graph_service.py), kept 90 days. version is the
-- workflows.graph_version the write produced: writes by one author from one source within five minutes are
-- one version (its row takes the newer graph and version), a restore is a write of its own, and the graph a
-- workflow had when its history began is its first row (source 'baseline'). graph is the graph as written
-- (never a runtime key); definition is reserved for an agent's own fields, written with its workflow;
-- author_key_id names the API key or grant that wrote it; changes are the lines its summary is made of.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE public.workflow_versions (
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    version bigint NOT NULL,
    graph jsonb NOT NULL,
    definition jsonb,
    author_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    author_key_id text,
    source text NOT NULL CHECK (source IN ('baseline', 'canvas', 'api', 'builder', 'mcp', 'coordinator', 'deploy',
                                           'restore')),
    changes text[] NOT NULL DEFAULT '{}',
    restored_from bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workflow_id, version)
);

CREATE INDEX workflow_versions_updated_at ON public.workflow_versions (updated_at);

ALTER TABLE public.workflow_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.workflow_versions FROM anon, authenticated;
