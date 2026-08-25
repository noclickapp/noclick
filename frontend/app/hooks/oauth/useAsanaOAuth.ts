// Asana OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useAsanaOAuth = createOAuthHook({
    provider: 'asana',
    defaultScopes: [
        'tasks:read',
        'tasks:write',
        'tasks:delete',
        'projects:read',
        'projects:write',
        'projects:delete',
        'stories:read',
        'stories:write',
        'users:read',
        'workspaces:read',
        'teams:read',
        'tags:read',
        'tags:write',
        'custom_fields:read',
        'webhooks:read',
        'webhooks:write',
        'webhooks:delete',
    ],
});
