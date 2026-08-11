// Zoom scopes belong exclusively to the Marketplace app configuration. Zoom
// rejects a caller-supplied `scope` parameter after sign-in, so this flow must
// not forward a node's scopes to the authorize route.
import { createOAuthHook } from './createOAuthHook';

export const useZoomOAuth = createOAuthHook({
    provider: 'zoom',
    sendScopes: false,
});
