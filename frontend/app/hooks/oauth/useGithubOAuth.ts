// Github OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useGithubOAuth = createOAuthHook({
    provider: 'github',
    // Mirrors GithubOAuthCredential's x-oauth-scopes, derived from
    // backend/nodes/scopes/github.py. Keep in sync.
    defaultScopes: ['gist', 'read:org', 'read:user', 'repo', 'user:email'],
});
