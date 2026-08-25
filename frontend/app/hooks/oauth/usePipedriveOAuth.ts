// Pipedrive OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const usePipedriveOAuth = createOAuthHook({
    provider: 'pipedrive',
});
