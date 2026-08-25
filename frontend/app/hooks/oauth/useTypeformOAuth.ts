// Typeform OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useTypeformOAuth = createOAuthHook({
    provider: 'typeform',
    defaultScopes: [
        'accounts:read',
        'forms:read',
        'forms:write',
        'images:read',
        'images:write',
        'themes:read',
        'themes:write',
        'responses:read',
        'responses:write',
        'webhooks:read',
        'webhooks:write',
        'workspaces:read',
        'workspaces:write',
    ],
});
