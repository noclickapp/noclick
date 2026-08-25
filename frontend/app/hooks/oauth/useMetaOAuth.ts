// Meta (Marketing / Ads / Business) OAuth — standard redirect flow via Facebook
// Login (comma-separated scopes). Built from the shared createOAuthHook factory.
// The authorize route lives at /api/auth/meta/authorize and the exchange event is
// meta:oauth:exchange.
import { createOAuthHook } from './createOAuthHook';

export const useMetaOAuth = createOAuthHook({
    provider: 'meta',
    defaultScopes: [
        'public_profile',
        'ads_management',
        'ads_read',
        'business_management',
        'leads_retrieval',
        'pages_show_list',
        'pages_read_engagement',
        'catalog_management',
    ],
});
