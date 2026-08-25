// Box OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useBoxOAuth = createOAuthHook({
    provider: 'box',
    defaultScopes: [
        'root_readwrite',
        'manage_managed_users',
        'manage_groups',
        'manage_webhook',
        'manage_enterprise_properties',
    ],
});
