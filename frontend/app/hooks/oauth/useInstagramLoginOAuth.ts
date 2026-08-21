// Instagram Login OAuth — Instagram API *with Instagram Login* (Page-free,
// served from graph.instagram.com). Built from the shared createOAuthHook
// factory. The authorize route lives at /api/auth/instagram_login/authorize and
// the exchange event is instagram_login:oauth:exchange.
import { createOAuthHook } from './createOAuthHook';

export const useInstagramLoginOAuth = createOAuthHook({
    provider: 'instagram_login',
    // Route lives at /api/auth/instagram/* (matches the registered OAuth redirect
    // URI); the provider key stays `instagram_login` for event/callback naming.
    authorizePath: '/api/auth/instagram/authorize',
    defaultScopes: [
        'instagram_business_basic',
        'instagram_business_content_publish',
        'instagram_business_manage_comments',
        'instagram_business_manage_messages',
    ],
});
