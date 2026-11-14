-- The secret each of a provider's senders signs a webhook's deliveries with, keyed by sender: WhatsApp's WAHooks
-- connection ids (utils/webhook_routes.py, webhook_secret_on_row). One NoClick URL can be registered on several
-- connections (a re-scan leaves the previous link's), and WAHooks gives each config its own secret, so the one
-- `secret` column can't verify them all. A delivery is checked against the secret of the connection it names.
ALTER TABLE public.webhooks
    ADD COLUMN IF NOT EXISTS signing_secrets jsonb NOT NULL DEFAULT '{}'::jsonb;

-- The one secret a WhatsApp row holds so far is its attached credential's connection's: registering, the nightly
-- sweep's adoption and a re-scan all read it there.
UPDATE public.webhooks w
SET signing_secrets = jsonb_build_object(c.metadata->>'connection_id', w.secret)
FROM public.credentials c
WHERE w.secret IS NOT NULL
  AND w.signing_secrets = '{}'::jsonb
  AND c.id::text = w.registered_credential_id
  AND c.credential_type = 'whatsapp_qr'
  AND c.metadata->>'connection_id' IS NOT NULL;
