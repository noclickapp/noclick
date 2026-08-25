// LinkedIn OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useLinkedInOAuth = createOAuthHook({
    provider: 'linkedin',
    defaultScopes: ['openid', 'profile', 'email', 'w_member_social'],
});
