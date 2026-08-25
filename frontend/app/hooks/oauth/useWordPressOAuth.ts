// WordPress OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useWordPressOAuth = createOAuthHook({
    provider: 'wordpress',
    defaultScopes: ['global'],
});
