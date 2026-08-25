// Webflow OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useWebflowOAuth = createOAuthHook({
    provider: 'webflow',
    defaultScopes: [
        'sites:read',
        'sites:write',
        'cms:read',
        'cms:write',
        'pages:read',
        'pages:write',
        'forms:read',
        'forms:write',
        'assets:read',
        'assets:write',
        'ecommerce:read',
        'ecommerce:write',
        'authorized_user:read',
    ],
});
