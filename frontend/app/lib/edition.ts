// Frontend mirror of the backend's NOCLICK_LOCAL flag (backend/utils/edition.py),
// set by `make local` and by the self-hosted .env. It gates UI that only makes
// sense on the hosted service: Google sign-in (needs a provider configured in a
// hosted Supabase project, so the button is dead on a fresh local install) and
// the onboarding questionnaire (exists to feed hosted personalization).

export function isLocalEdition(): boolean {
    return import.meta.env.VITE_NOCLICK_LOCAL === '1';
}
