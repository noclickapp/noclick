-- Verified phone identity: the binding every phone-keyed channel (WhatsApp,
-- calls) resolves to a NoClick account through. A number is linked only by a
-- server-observed "approved" Twilio Verify check on a challenge minted for
-- that exact user + number; a caller id or a WhatsApp sender never links one.
CREATE TABLE public.phone_verification_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    phone_e164 TEXT NOT NULL,
    provider_sid TEXT,
    -- pending | approved | conflict | expired | superseded | failed
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE INDEX phone_verification_challenges_user_created_idx
    ON public.phone_verification_challenges (user_id, created_at DESC);
CREATE INDEX phone_verification_challenges_phone_created_idx
    ON public.phone_verification_challenges (phone_e164, created_at DESC);

CREATE TABLE public.user_phones (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    phone_e164 TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unlinked_at TIMESTAMPTZ,
    -- Bumps on every (re)link so work queued against an older binding is
    -- recognised as stale instead of reaching a rebound number.
    link_version INTEGER NOT NULL DEFAULT 1,
    challenge_id UUID REFERENCES public.phone_verification_challenges(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One account per live number.
CREATE UNIQUE INDEX user_phones_active_phone_idx
    ON public.user_phones (phone_e164) WHERE unlinked_at IS NULL;

-- Backend-only tables: read/written via asyncpg as `postgres` (bypasses RLS).
-- RLS on with no policies + no API-role grants = full deny through PostgREST.
ALTER TABLE public.phone_verification_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_phones ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.phone_verification_challenges, public.user_phones FROM anon, authenticated;
GRANT ALL ON TABLE public.phone_verification_challenges, public.user_phones TO service_role;

CREATE TRIGGER update_user_phones_updated_at
BEFORE UPDATE ON public.user_phones
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
