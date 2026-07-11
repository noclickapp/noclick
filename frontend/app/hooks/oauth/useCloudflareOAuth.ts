// Cloudflare OAuth — Authorization Code flow via dash.cloudflare.com/oauth2/auth.
// API permissions (account:read, zone:edit, etc.) are configured on the OAuth client
// in the Cloudflare dashboard; the authorize URL only sends OIDC scopes.
// sendScopes:false so no scope param is forwarded from the hook to the authorize route.
import { createOAuthHook } from './createOAuthHook';

export const useCloudflareOAuth = createOAuthHook({
    provider: 'cloudflare',
    sendScopes: false,
});
