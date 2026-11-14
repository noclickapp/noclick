-- What a WhatsApp chat looks like from one linked connection (utils/whatsapp_profiles.py): the profile picture of a
-- person or group, copied out of WhatsApp's short-lived CDN link into storage at avatar_key (its sha256 says when a
-- refresh found the same picture), and a group's name. One row per (connection, chat id); refresh_after is when a read
-- fetches it again. No picture and a private one are a row with no avatar_key. Rows go when their connection is torn
-- down. connection_id is the WAHooks connection a whatsapp_qr credential holds: no foreign key, credentials keep it in
-- their encrypted blob.
-- Backend-only: RLS on with no policy, and the API roles hold no grants.
CREATE TABLE IF NOT EXISTS public.whatsapp_chat_profiles (
    connection_id text NOT NULL,
    jid text NOT NULL,
    avatar_key text,
    avatar_sha256 text,
    name text,
    refresh_after timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connection_id, jid)
);

ALTER TABLE public.whatsapp_chat_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.whatsapp_chat_profiles FROM anon, authenticated;
