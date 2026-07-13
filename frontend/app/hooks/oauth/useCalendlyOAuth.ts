// Calendly OAuth — standard authorization_code flow (shared NoClick app, no
// tenant/custom-client). Built from the shared createOAuthHook factory; only the
// per-provider config lives here. Scopes are intentionally empty: Calendly's 2026
// granular-scope token strings aren't publicly documented, so the registered
// app's access governs (see backend/nodes/oauth/calendly_oauth.py).
import { createOAuthHook } from './createOAuthHook';

export const useCalendlyOAuth = createOAuthHook({
    provider: 'calendly',
    defaultScopes: [],
    scopeDelimiter: ' ',
});
