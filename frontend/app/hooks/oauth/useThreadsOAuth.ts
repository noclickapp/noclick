// Threads OAuth — standard redirect flow (comma-separated scopes). Built from
// the shared createOAuthHook factory. Threads uses its own OAuth app + tokens,
// distinct from Facebook/Instagram; the authorize route lives at
// /api/auth/threads/authorize and the exchange event is threads:oauth:exchange.
import { createOAuthHook } from './createOAuthHook';

export const useThreadsOAuth = createOAuthHook({
    provider: 'threads',
    defaultScopes: [
        'threads_basic',
        'threads_content_publish',
        'threads_read_replies',
        'threads_manage_replies',
        'threads_manage_insights',
        'threads_manage_mentions',
        'threads_keyword_search',
        'threads_location_tagging',
        'threads_delete',
        'threads_profile_discovery',
    ],
});
