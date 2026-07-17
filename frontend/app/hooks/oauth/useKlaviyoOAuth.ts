// Klaviyo OAuth — built from the shared createOAuthHook factory (config only).
// Klaviyo requires PKCE (S256); the code verifier/challenge are generated in the
// authorize route and round-tripped through the callback, which the factory
// forwards to the exchange. Klaviyo OAuth is for approved marketplace apps — the
// Private API Key credential is the primary, unrestricted path.
import { createOAuthHook } from './createOAuthHook';

export const useKlaviyoOAuth = createOAuthHook({
    provider: 'klaviyo',
    scopeDelimiter: ' ',
    defaultScopes: ['accounts:read', 'profiles:read', 'profiles:write', 'lists:read', 'lists:write'],
});
