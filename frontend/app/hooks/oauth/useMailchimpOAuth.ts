// Mailchimp OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useMailchimpOAuth = createOAuthHook({
    provider: 'mailchimp',
    defaultScopes: ['marketing:read', 'marketing:write'],
});
