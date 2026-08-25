// Salesforce OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useSalesforceOAuth = createOAuthHook({
    provider: 'salesforce',
    defaultScopes: ['api', 'refresh_token'],
});
