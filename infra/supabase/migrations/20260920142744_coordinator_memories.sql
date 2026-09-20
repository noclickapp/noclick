-- Separate retrieval descriptions from full memories. Private to one account;
-- only authenticated backend operations can access this table.
CREATE TABLE public.coordinator_memories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100 AND name ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    description text NOT NULL,
    memory_type text NOT NULL CHECK (memory_type IN ('user', 'feedback', 'project', 'reference')),
    content text NOT NULL,
    origin_conversation_id text,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    search_document tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('simple', name || ' ' || description), 'A') ||
        setweight(to_tsvector('simple', content), 'B')
    ) STORED,
    UNIQUE (user_id, name),
    CHECK (deleted_at IS NOT NULL OR (length(btrim(description)) BETWEEN 1 AND 600
        AND length(btrim(content)) BETWEEN 1 AND 16000))
);
CREATE INDEX coordinator_memories_user_recent ON public.coordinator_memories (user_id, updated_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX coordinator_memories_search ON public.coordinator_memories USING gin (search_document)
    WHERE deleted_at IS NULL;
ALTER TABLE public.coordinator_memories ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.coordinator_memories FROM anon, authenticated;
