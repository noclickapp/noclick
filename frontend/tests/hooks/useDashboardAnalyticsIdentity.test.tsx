// @vitest-environment jsdom
// Exercise the dashboard's production identity hook with a deferred safe client.
// This preserves customer acquisition, internal opt-out, signup deduplication
// and local feature authorization after removing the eager analytics import.
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { User } from '@supabase/supabase-js';
import type { PostHog } from 'posthog-js';
import { AnalyticsClient } from '~/lib/analyticsClient';
import { useDashboardAnalyticsIdentity } from '~/hooks/useDashboardAnalyticsIdentity';
import { debugToolsState } from '~/lib/debugToolsState';
import { featureGateState } from '~/lib/featureGates';
import { EVENTS } from '~/lib/analytics-events';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

vi.mock('~/lib/internalUsers', () => ({
    isInternalEmail: (email: string) => email === 'staff@example.test',
    isNonCustomerEmail: (email: string) => ['staff@example.test', 'former@example.test'].includes(email),
}));
vi.mock('~/lib/tracking', () => ({ getTrackingData: () => ({
    utm_source: 'campaign', referrer: 'https://search.example.test/', landing_page: '/pricing',
}) }));
vi.mock('~/lib/debugToolsState', () => ({ debugToolsState: { internalUser: false } }));
vi.mock('~/lib/featureGates', () => ({ featureGateState: { email: '' } }));

let optedOut: boolean;
let client: any;
beforeEach(() => {
    optedOut = false;
    localStorage.clear();
    debugToolsState.internalUser = false;
    featureGateState.email = '';
    client = {
        has_opted_out_capturing: vi.fn(() => optedOut),
        opt_out_capturing: vi.fn(() => { optedOut = true; }),
        opt_in_capturing: vi.fn(() => { optedOut = false; }),
        identify: vi.fn(), capture: vi.fn(),
    };
});
afterEach(() => localStorage.clear());
const user = (email: string | undefined = 'customer@example.test', recent = false) => ({
    id: 'fixture-user', email, created_at: recent ? new Date().toISOString() : '2025-01-01T00:00:00Z',
    user_metadata: { signup_channel: 'phone' },
} as User);

function mounted(account: User) {
    let active: PostHog | undefined;
    const wrapper = ({ children }: { children: ReactNode }) => <AnalyticsClient.Provider value={active}>{children}</AnalyticsClient.Provider>;
    const hook = renderHook(({ current }) => useDashboardAnalyticsIdentity(current), { initialProps: { current: account }, wrapper });
    return { hook, account, activate: () => { active = client; hook.rerender({ current: account }); } };
}

describe('dashboard identity after safe deferred analytics init', () => {
    it('the actual dashboard route uses the tested identity hook', () => {
        expect(readFileSync(resolve('app/routes/dashboard.tsx'), 'utf8')).toContain('useDashboardAnalyticsIdentity(user)');
    });

    it('updates local authorization without a client, then identifies once with ordinary first-touch props', () => {
        const fixture = mounted(user());
        expect(featureGateState.email).toBe('customer@example.test');
        expect(client.identify).not.toHaveBeenCalled();
        fixture.activate();
        expect(client.identify).toHaveBeenCalledWith('fixture-user', { email: 'customer@example.test' },
            expect.objectContaining({ $initial_utm_source: 'campaign', $initial_referrer: 'https://search.example.test/', initial_landing_page: '/pricing' }));
        fixture.hook.rerender({ current: fixture.account });
        expect(client.identify).toHaveBeenCalledOnce();
        fixture.hook.unmount();
    });

    it.each(['staff@example.test', 'former@example.test'])('identifies and opts out %s without an opt-in dance', (email) => {
        const fixture = mounted(user(email));
        expect(debugToolsState.internalUser).toBe(email === 'staff@example.test');
        fixture.activate();
        expect(client.identify).toHaveBeenCalledWith('fixture-user', { email, $internal_or_test_user: true });
        expect(client.opt_out_capturing).toHaveBeenCalledOnce();
        expect(client.opt_in_capturing).not.toHaveBeenCalled();
        fixture.hook.rerender({ current: { ...user(email) } });
        expect(client.identify).toHaveBeenCalledOnce();
        expect(client.opt_out_capturing).toHaveBeenCalledOnce();
        fixture.hook.unmount();
    });

    it('opts a returning customer in and preserves phone-only identity', () => {
        optedOut = true;
        const fixture = mounted(user(''));
        fixture.activate();
        expect(client.opt_in_capturing).toHaveBeenCalledOnce();
        expect(client.identify).toHaveBeenCalledWith('fixture-user', { signup_channel: 'phone' }, expect.any(Object));
        fixture.hook.unmount();
    });

    it('fires recent OAuth signup once and honors the email signup marker', () => {
        const account = user('customer@example.test', true);
        const fixture = mounted(account);
        fixture.activate();
        expect(client.capture).toHaveBeenCalledWith(EVENTS.USER_SIGNED_UP, { auth_method: 'oauth' });
        fixture.hook.rerender({ current: { ...account } });
        expect(client.capture).toHaveBeenCalledOnce();
        fixture.hook.unmount();
        localStorage.clear();
        client.capture.mockClear();
        localStorage.setItem('pc:signed_up_fired:email', '1');
        const emailFixture = mounted(account);
        emailFixture.activate();
        expect(client.capture).not.toHaveBeenCalled();
        expect(localStorage.getItem('pc:signed_up_fired:email')).toBeNull();
        emailFixture.hook.unmount();
    });
});
