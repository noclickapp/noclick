-- A phone-only account (made by messaging NoClick on WhatsApp) connects to
-- an email by a code sent to that address and typed back into the chat
-- (utils/account_link.py). Only a matching code moves anything: then the
-- email's existing account absorbs the phone-only one, or the phone-only
-- account takes the email for sign-in.
CREATE TABLE public.account_link_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    -- pending | verified (code matched, the move is queued) | completed | superseded | failed
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    target_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

CREATE INDEX account_link_challenges_user_created_idx
    ON public.account_link_challenges (user_id, created_at DESC);
CREATE INDEX account_link_challenges_email_created_idx
    ON public.account_link_challenges (email, created_at DESC);

ALTER TABLE public.account_link_challenges ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.account_link_challenges FROM anon, authenticated;
GRANT ALL ON TABLE public.account_link_challenges TO service_role;
