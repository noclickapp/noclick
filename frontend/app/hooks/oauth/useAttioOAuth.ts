// Attio OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useAttioOAuth = createOAuthHook({
    provider: 'attio',
    defaultScopes: [
        'record_permission:read-write',
        'object_configuration:read-write',
        'list_entry:read-write',
        'list_configuration:read-write',
        'user_management:read',
        'comment:read-write',
        'task:read-write',
        'note:read-write',
        'webhook:read-write',
        'file:read',
    ],
    scopeDelimiter: ' ',
});
