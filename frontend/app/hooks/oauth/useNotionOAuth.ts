// Notion OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useNotionOAuth = createOAuthHook({
    provider: 'notion',
    sendScopes: false,
});
