// Linear OAuth — standard flow (comma-separated scopes). Built from the shared
// createOAuthHook factory; only the per-provider config lives here.
import { createOAuthHook } from './createOAuthHook';

export const useLinearOAuth = createOAuthHook({
    provider: 'linear',
    defaultScopes: ['read', 'write', 'issues:create', 'comments:create'],
});
