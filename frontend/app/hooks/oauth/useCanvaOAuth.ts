// Canva OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useCanvaOAuth = createOAuthHook({
    provider: 'canva',
    defaultScopes: [
        'asset:read',
        'asset:write',
        'design:meta:read',
        'design:content:read',
        'design:content:write',
        'folder:read',
        'folder:write',
        'profile:read',
        'brandtemplate:meta:read',
        'brandtemplate:content:read',
        'comment:read',
        'comment:write',
    ],
});
