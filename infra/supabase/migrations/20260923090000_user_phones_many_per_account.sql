-- An account may hold several live numbers (each one more channel to the same
-- coordinator); a live number still belongs to exactly one account
-- (user_phones_active_phone_idx). A number binds by a Twilio Verify approval
-- on the web ('verify') or by messaging NoClick's WhatsApp number, whose
-- sender Meta authenticates ('whatsapp').
ALTER TABLE public.user_phones DROP CONSTRAINT user_phones_pkey;
ALTER TABLE public.user_phones ADD COLUMN id UUID NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.user_phones ADD PRIMARY KEY (id);

ALTER TABLE public.user_phones
    ADD COLUMN source TEXT NOT NULL DEFAULT 'verify' CHECK (source IN ('verify', 'whatsapp')),
    -- The last inbound message from this number: outbound reaches the account
    -- on the number it last used.
    ADD COLUMN last_seen_at TIMESTAMPTZ;

-- One row per (account, number); a relink revives it and bumps link_version.
CREATE UNIQUE INDEX user_phones_user_phone_idx ON public.user_phones (user_id, phone_e164);
CREATE INDEX user_phones_user_active_idx ON public.user_phones (user_id) WHERE unlinked_at IS NULL;
