// Preserve dashboard identification and internal-user opt-out after deferred SDK init.
// The route can mount before analytics is safe to load, so identity waits for
// the provider's client while local debug/feature-gate state updates immediately.
import { useEffect } from 'react';
import type { User } from '@supabase/supabase-js';
import { useAnalyticsClient } from '~/lib/analyticsClient';
import { getTrackingData } from '~/lib/tracking';
import { debugToolsState } from '~/lib/debugToolsState';
import { featureGateState } from '~/lib/featureGates';
import { isInternalEmail, isNonCustomerEmail } from '~/lib/internalUsers';
import { EVENTS } from '~/lib/analytics-events';

export function useDashboardAnalyticsIdentity(user: User | null): void {
    const posthog = useAnalyticsClient();
    useEffect(() => {
        if (!user) return;
        debugToolsState.internalUser = isInternalEmail(user.email ?? '');
        featureGateState.email = user.email ?? '';
        if (!posthog) return;
        // Former staff remain opted out; current staff also retain local debug
        // authorization. Avoid an opt-in/identify/opt-out dance on every load.
        if (isNonCustomerEmail(user.email ?? '')) {
            if (!posthog.has_opted_out_capturing()) {
                posthog.identify(user.id, { email: user.email, $internal_or_test_user: true });
                posthog.opt_out_capturing();
            }
            return;
        }
        if (posthog.has_opted_out_capturing()) posthog.opt_in_capturing();
        const t = getTrackingData();
        const setOnce: Record<string, string> = {};
        if (user.created_at) setOnce.signup_date = user.created_at;
        if (t.utm_source) setOnce.$initial_utm_source = t.utm_source;
        if (t.utm_medium) setOnce.$initial_utm_medium = t.utm_medium;
        if (t.utm_campaign) setOnce.$initial_utm_campaign = t.utm_campaign;
        if (t.utm_term) setOnce.$initial_utm_term = t.utm_term;
        if (t.utm_content) setOnce.$initial_utm_content = t.utm_content;
        if (t.referrer) setOnce.$initial_referrer = t.referrer;
        if (t.landing_page) setOnce.initial_landing_page = t.landing_page;
        posthog.identify(user.id,
            user.email ? { email: user.email } : { signup_channel: user.user_metadata?.signup_channel },
            Object.keys(setOnce).length ? setOnce : undefined);
        if (user.created_at) {
            const ageMs = Date.now() - new Date(user.created_at).getTime();
            const seenKey = `pc:signed_up_fired:${user.id}`;
            const emailMarker = 'pc:signed_up_fired:email';
            if (ageMs < 5 * 60 * 1000 && !localStorage.getItem(seenKey) && !localStorage.getItem(emailMarker)) {
                localStorage.setItem(seenKey, '1');
                posthog.capture(EVENTS.USER_SIGNED_UP, { auth_method: 'oauth' });
            }
            if (localStorage.getItem(emailMarker)) localStorage.removeItem(emailMarker);
        }
    }, [user, posthog]);
}
