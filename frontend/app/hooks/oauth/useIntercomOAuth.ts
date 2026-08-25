// Intercom OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useIntercomOAuth = createOAuthHook({
    provider: 'intercom',
    defaultScopes: [
        'read_write_users',
        'read_write_companies',
        'read_write_conversations',
        'read_write_tags',
        'read_write_events',
        'read_write_tickets',
        'read_admins',
        'read_teams',
    ],
});
