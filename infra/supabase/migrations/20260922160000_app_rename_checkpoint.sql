-- Keep both addresses reserved until the existing deployment has moved and
-- the old CDN content is gone. A retry resumes from this app-owned checkpoint.
ALTER TABLE public.apps
    ADD COLUMN pending_subdomain text,
    ADD COLUMN rename_copied boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT apps_pending_subdomain_valid CHECK (
        pending_subdomain IS NULL OR
        (pending_subdomain <> subdomain AND pending_subdomain ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$')
    ),
    ADD CONSTRAINT apps_rename_copy_has_target CHECK (NOT rename_copied OR pending_subdomain IS NOT NULL);

CREATE UNIQUE INDEX apps_pending_subdomain_key ON public.apps(pending_subdomain)
    WHERE pending_subdomain IS NOT NULL;
