// PagerDuty OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const usePagerDutyOAuth = createOAuthHook({
    provider: 'pagerduty',
    defaultScopes: ['read', 'write'],
});
