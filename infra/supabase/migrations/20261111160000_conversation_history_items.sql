-- An agent's model history, one row per item: the SDK's input items of a conversation
-- (coder/openai_agent/session.py, repositories/conversation_history.py). They were one JSON array in
-- conversations.metadata.sdk_history, which every append rewrote whole, megabytes for a long thread.
-- A conversation's items read in order of id; every writer takes the conversation's row first, so one
-- conversation's appends never interleave. Writes land in both places until reads move here, once
-- scripts/backfill_conversation_history.py has copied every history written before.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE public.conversation_history_items (
    conversation_id text NOT NULL REFERENCES public.conversations (conversation_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    id bigint GENERATED ALWAYS AS IDENTITY,
    item jsonb NOT NULL,
    PRIMARY KEY (conversation_id, id)
);

ALTER TABLE public.conversation_history_items ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.conversation_history_items FROM anon, authenticated;
