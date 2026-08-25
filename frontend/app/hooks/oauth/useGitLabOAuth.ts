// GitLab OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useGitLabOAuth = createOAuthHook({
    provider: 'gitlab',
    defaultScopes: ['api', 'read_user'],
});
