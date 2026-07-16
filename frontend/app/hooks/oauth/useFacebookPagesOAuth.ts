// Facebook Pages OAuth — Facebook Login with Pages/Messaging scopes, minting a
// facebook_oauth credential for the Facebook (Pages + Messenger) node. Built from
// the shared createOAuthHook factory (authorize at /api/auth/facebook_pages/authorize,
// exchange event facebook_pages:oauth:exchange). Distinct from the Instagram-only
// `facebook` provider.
import { createOAuthHook } from './createOAuthHook';

export const useFacebookPagesOAuth = createOAuthHook({
    provider: 'facebook_pages',
    defaultScopes: [
        'public_profile', 'email',
        'pages_show_list', 'pages_read_engagement', 'pages_read_user_content',
        'pages_manage_posts', 'pages_manage_engagement', 'pages_manage_metadata',
        'pages_messaging', 'read_insights', 'business_management',
    ],
});
