-- The app ("whatsapp" | "imessage") a number last texted the instance's own
-- lines on: "the channel they last used" is read from the number itself.
ALTER TABLE public.user_phones
    ADD COLUMN last_seen_app TEXT CHECK (last_seen_app IN ('whatsapp', 'imessage'));
