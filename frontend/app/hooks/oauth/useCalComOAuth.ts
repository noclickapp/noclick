// CalCom OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useCalComOAuth = createOAuthHook({
    provider: 'calcom',
    defaultScopes: [
        'BOOKING_READ',
        'BOOKING_WRITE',
        'EVENT_TYPE_READ',
        'EVENT_TYPE_WRITE',
        'SCHEDULE_READ',
        'SCHEDULE_WRITE',
        'PROFILE_READ',
        'PROFILE_WRITE',
        'WEBHOOK_READ',
        'WEBHOOK_WRITE',
    ],
});
