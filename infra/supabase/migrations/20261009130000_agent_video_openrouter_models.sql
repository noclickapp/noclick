-- An agent node's video model now runs only through OpenRouter's video API
-- (backend/nodes/agent/handlers/video.py). Saved agent nodes still name the
-- ids the old Google AI Studio and LiteLLM paths took; each is renamed here to
-- the OpenRouter id of the same model. This is the one place the rename
-- happens: at run time an old id is refused by name, never aliased.
--
-- An old id is a Google model name, bare or behind the prefix of the route
-- that took it (gemini/, google/, vertex_ai/), or a Runway route's id. Veo
-- 3.0 and 2.0 aren't on OpenRouter and move to their Veo 3.1 successor at the
-- same tier; the old default "veo-3" moves to the new default. Ids with no
-- OpenRouter equivalent (Sora, Runway's Gen-4 Turbo) are left for the run
-- to refuse. Every target is pinned to OpenRouter's video catalog by
-- backend/tests/test_agent_video_model_renames.py.
--
-- Rewritten wherever a graph can come back from: the live workflows and
-- their restorable checkpoints. Only an agent node's model is touched, in
-- either stored node shape (save: node.config.model; canvas:
-- node.data.config.model, or node.data.model), and only rows that change are
-- written, so graph_version and updated_at move only for those.

CREATE OR REPLACE FUNCTION pg_temp.agent_video_model_renames() RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT '{
        "veo-3": "google/veo-3.1-fast",
        "veo-3.1-fast-generate-001": "google/veo-3.1-fast",
        "veo-3.1-fast-generate-preview": "google/veo-3.1-fast",
        "veo-3.1-generate-001": "google/veo-3.1",
        "veo-3.1-generate-preview": "google/veo-3.1",
        "veo-3.1-lite-generate-001": "google/veo-3.1-lite",
        "veo-3.1-lite-generate-preview": "google/veo-3.1-lite",
        "veo-3.0-fast-generate-001": "google/veo-3.1-fast",
        "veo-3.0-fast-generate-preview": "google/veo-3.1-fast",
        "veo-3.0-generate-001": "google/veo-3.1",
        "veo-3.0-generate-preview": "google/veo-3.1",
        "veo-2.0-generate-001": "google/veo-3.1-lite",
        "runwayml/gen4.5": "runway/gen-4.5",
        "runwayml/aleph2": "runway/aleph-2",
        "runwayml/hailuo3": "minimax/hailuo-3",
        "runwayml/veo3.1": "google/veo-3.1",
        "runwayml/veo3.1_fast": "google/veo-3.1-fast"
    }'::jsonb
$$;

-- The OpenRouter id for an old saved id, or NULL for any other id.
CREATE OR REPLACE FUNCTION pg_temp.agent_video_model_rename(model text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT pg_temp.agent_video_model_renames()
           ->> regexp_replace(lower(model), '^(gemini|google|vertex_ai)/', '')
$$;

CREATE OR REPLACE FUNCTION pg_temp.agent_video_model_at(node jsonb, path text[]) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(node #> path) = 'string'
                     AND pg_temp.agent_video_model_rename(node #>> path) IS NOT NULL
                THEN jsonb_set(node, path, to_jsonb(pg_temp.agent_video_model_rename(node #>> path)))
                ELSE node END
$$;

CREATE OR REPLACE FUNCTION pg_temp.agent_video_node(node jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN node->>'type' = 'agent'
                THEN pg_temp.agent_video_model_at(
                         pg_temp.agent_video_model_at(
                             pg_temp.agent_video_model_at(node, '{config,model}'),
                             '{data,config,model}'),
                         '{data,model}')
                ELSE node END
$$;

CREATE OR REPLACE FUNCTION pg_temp.agent_video_graph(graph jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(graph->'nodes') = 'array'
                THEN jsonb_set(graph, '{nodes}', COALESCE((
                         SELECT jsonb_agg(pg_temp.agent_video_node(node) ORDER BY ord)
                         FROM jsonb_array_elements(graph->'nodes') WITH ORDINALITY AS t(node, ord)), '[]'::jsonb))
                ELSE graph END
$$;

UPDATE public.workflows w
SET workflow = renamed.graph
FROM (
    SELECT id, pg_temp.agent_video_graph(workflow) AS graph
    FROM public.workflows
    WHERE workflow::text ~* '(veo|runwayml/)'
) renamed
WHERE w.id = renamed.id AND renamed.graph IS DISTINCT FROM w.workflow;

UPDATE public.workflow_checkpoints c
SET workflow = renamed.graph
FROM (
    SELECT id, pg_temp.agent_video_graph(workflow) AS graph
    FROM public.workflow_checkpoints
    WHERE workflow::text ~* '(veo|runwayml/)'
) renamed
WHERE c.id = renamed.id AND renamed.graph IS DISTINCT FROM c.workflow;
