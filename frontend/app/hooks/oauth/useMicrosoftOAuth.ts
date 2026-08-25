// Microsoft OAuth — built from the shared createOAuthHook factory (config only).
// User.Read + offline_access are appended from the provider config's extraScopes via
// augmentScopes (applied inside buildAuthorizeUrl), the same set the credential link uses.
import { createOAuthHook } from './createOAuthHook';

export const useMicrosoftOAuth = createOAuthHook({
    provider: 'microsoft',
    defaultScopes: [
        'https://graph.microsoft.com/Mail.Send',
        'https://graph.microsoft.com/Mail.Read',
        'https://graph.microsoft.com/Mail.ReadWrite',
        'https://graph.microsoft.com/User.Read',
    ],
});
