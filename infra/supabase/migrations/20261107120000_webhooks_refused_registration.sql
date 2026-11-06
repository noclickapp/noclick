-- A registration a provider refused for good (utils/webhook_manager.py, RegistrationRefused): the settings it was
-- refused at, so no reconcile tries it again until they change. credential_rejected waits for the account to be
-- saved again (credentials.token_version); held_elsewhere for the holding registration (refused_holder_id, a
-- webhooks row) to let go. A successful registration clears them. No foreign key on the holder: one deleted has
-- let go.
ALTER TABLE public.webhooks
    ADD COLUMN IF NOT EXISTS refused_fingerprint text,
    ADD COLUMN IF NOT EXISTS refused_kind text CHECK (refused_kind IN ('credential_rejected', 'held_elsewhere')),
    ADD COLUMN IF NOT EXISTS refused_holder_id uuid,
    ADD COLUMN IF NOT EXISTS refused_credential_version integer,
    ADD COLUMN IF NOT EXISTS refused_at timestamptz;
