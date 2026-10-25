-- A number can be reached over iMessage (the instance's Sendblue line) as well as WhatsApp: a link code that
-- arrives over iMessage records it.
ALTER TABLE public.user_phones DROP CONSTRAINT IF EXISTS user_phones_source_check;
ALTER TABLE public.user_phones
    ADD CONSTRAINT user_phones_source_check CHECK (source IN ('verify', 'whatsapp', 'imessage'));
