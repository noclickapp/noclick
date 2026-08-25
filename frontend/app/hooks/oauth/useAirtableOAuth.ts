// Airtable OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useAirtableOAuth = createOAuthHook({
    provider: 'airtable',
    defaultScopes: [
        'data.records:read',
        'data.records:write',
        'schema.bases:read',
        'schema.bases:write',
        'webhook:manage',
    ],
});
