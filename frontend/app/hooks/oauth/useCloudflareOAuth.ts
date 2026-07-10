// Cloudflare OAuth — standard Authorization Code flow via Cloudflare's OAuth 2.0 endpoints.
// Scopes are space-separated (Cloudflare convention, not comma). Built from the shared
// createOAuthHook factory; only the per-provider config lives here.
import { createOAuthHook } from './createOAuthHook';

export const useCloudflareOAuth = createOAuthHook({
    provider: 'cloudflare',
    defaultScopes: ['account:read', 'zone:read', 'zone:edit', 'dns:edit', 'workers:write'],
    scopeDelimiter: ' ',
});
