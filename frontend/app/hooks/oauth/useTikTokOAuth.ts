// TikTok OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useTikTokOAuth = createOAuthHook({
    provider: 'tiktok',
    defaultScopes: [
        'user.info.basic',
        'user.info.profile',
        'user.info.stats',
        'video.list',
        'video.query',
        'video.publish',
        'video.upload',
        'video.like.list',
    ],
});
