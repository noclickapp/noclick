// Parallel OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useParallelOAuth = createOAuthHook({
    provider: 'parallel',
    sendScopes: false,
});
