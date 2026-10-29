-- Each write of a workflow's definition (coder/workflow/graph_service.py), kept 90 days. One author's writes
-- from one source within five minutes of a version's first are that version; a restore is a write of its own,
-- and what a workflow was when its history began is its first row (source 'baseline'). A version holds the
-- definition whole, so a restore puts all of it back: the graph as written (never a runtime key), the workflow's
-- name and description, and the settings a client may write (never NoClick's own, utils/system_workflows.py).
-- history_version is the version's own number, the workflows.graph_version its first write produced, never
-- changed (reads and restores name a version by it); version is the graph_version its latest write produced.
-- A workflow's newest version is open: its state is NULL, being the workflow as it stands, and the write that
-- starts the next version fills it in, so an autosave never writes the graph twice.
-- definition is reserved for an agent's own fields, written with its workflow; author_key_id names the API key
-- or grant that wrote it; changes are the lines its summary is made of.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE public.workflow_versions (
    workflow_id uuid NOT NULL REFERENCES public.workflows(id) ON DELETE CASCADE,
    history_version bigint NOT NULL,
    version bigint NOT NULL,
    graph jsonb,
    name text,
    description text,
    settings jsonb,
    definition jsonb,
    author_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    author_key_id text,
    source text NOT NULL CHECK (source IN ('baseline', 'canvas', 'api', 'builder', 'mcp', 'coordinator', 'deploy',
                                           'restore')),
    changes text[] NOT NULL DEFAULT '{}',
    restored_from bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workflow_id, history_version),
    UNIQUE (workflow_id, version),
    CHECK ((graph IS NULL) = (name IS NULL))
);

CREATE INDEX workflow_versions_updated_at ON public.workflow_versions (updated_at);
CREATE INDEX workflow_versions_author ON public.workflow_versions (workflow_id, source, author_user_id, version DESC);

ALTER TABLE public.workflow_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.workflow_versions FROM anon, authenticated;
