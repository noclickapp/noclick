// Fathom OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useFathomOAuth = createOAuthHook({
    provider: 'fathom',
    defaultScopes: ['public_api'],
});
