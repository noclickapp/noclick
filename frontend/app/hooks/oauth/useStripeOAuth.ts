// Stripe OAuth — built from the shared createOAuthHook factory (config only).
import { createOAuthHook } from './createOAuthHook';

export const useStripeOAuth = createOAuthHook({
    provider: 'stripe',
    defaultScopes: ['read_write'],
});
