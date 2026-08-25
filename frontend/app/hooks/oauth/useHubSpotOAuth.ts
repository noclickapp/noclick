// HubSpot OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useHubSpotOAuth = createOAuthHook({
    provider: 'hubspot',
    defaultScopes: ['crm.objects.contacts.read', 'crm.objects.contacts.write'],
});
