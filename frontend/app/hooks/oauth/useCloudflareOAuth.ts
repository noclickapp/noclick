// Cloudflare OAuth — Authorization Code flow via dash.cloudflare.com/oauth2/auth.
// Scope strings are hardcoded in cloudflare.authorize.tsx (dot-notation format:
// resource-name.action). sendScopes:false — the hook does not forward scopes.
import { createOAuthHook } from './createOAuthHook';

export const useCloudflareOAuth = createOAuthHook({
    provider: 'cloudflare',
    sendScopes: false,
});
