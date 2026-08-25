// ClickUp OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useClickUpOAuth = createOAuthHook({
    provider: 'clickup',
});
