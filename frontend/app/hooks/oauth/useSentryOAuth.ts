// Sentry OAuth — standard authorization_code flow (shared NoClick app, no
// tenant/custom-client). Built from the shared createOAuthHook factory; only the
// per-provider config lives here. Scopes mirror backend/nodes/oauth/sentry_oauth.py
// (SENTRY_DEFAULT_SCOPES) and ride the authorize URL space-delimited.
import { createOAuthHook } from './createOAuthHook';

export const useSentryOAuth = createOAuthHook({
    provider: 'sentry',
    defaultScopes: [
        'org:read', 'org:write',
        'project:read', 'project:write', 'project:admin', 'project:releases',
        'team:read', 'team:write', 'team:admin',
        'member:read', 'member:write',
        'event:read', 'event:write', 'event:admin',
    ],
    scopeDelimiter: ' ',
});
