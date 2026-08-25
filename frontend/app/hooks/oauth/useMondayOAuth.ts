// Monday OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useMondayOAuth = createOAuthHook({
    provider: 'monday',
    defaultScopes: [
        'account:read',
        'boards:read',
        'boards:write',
        'docs:read',
        'docs:write',
        'workspaces:read',
        'workspaces:write',
        'users:read',
        'users:write',
        'teams:read',
        'teams:write',
        'updates:read',
        'updates:write',
        'notifications:write',
        'webhooks:read',
        'webhooks:write',
        'assets:read',
        'tags:read',
        'me:read',
    ],
});
