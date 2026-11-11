// @vitest-environment happy-dom
// Tracking sync waits until the page has loaded (its auth calls hold the session lock every signed read waits on),
// reads the session's own user rather than asking the server, and writes only a journey over other pages.
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const auth = { getSession: vi.fn(), getUser: vi.fn(), updateUser: vi.fn(async () => ({ error: null })) };
vi.mock('~/lib/supabase', () => ({ createBrowserSupabaseClient: () => ({ auth }) }));

import { useTrackingSync } from '~/hooks/useTrackingSync';

const ENV = { SUPABASE_URL: 'https://x.test', SUPABASE_ANON_KEY: 'anon' };
const journey = (...paths: string[]) => paths.map((path, i) => ({ path, timestamp: `2026-11-11T10:0${i}:00Z` }));
const signedIn = (metadata: Record<string, unknown>) => auth.getSession.mockResolvedValue({ data: { session: { user: { user_metadata: metadata } } } });
const tracked = (paths: string[]) =>
    localStorage.setItem('noclick_tracking', JSON.stringify({ page_journey: journey(...paths), first_seen_at: '2026-11-11T10:00:00Z', landing_page: paths[0], _storedAt: Date.now() }));

beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    localStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe('tracking sync', () => {
    it('does nothing while the page loads, then reads the session’s own user', async () => {
        tracked(['/pricing', '/dashboard']);
        signedIn({ first_seen_at: 'earlier', page_journey: journey('/dashboard') });
        renderHook(() => useTrackingSync({ env: ENV }));
        await vi.advanceTimersByTimeAsync(9_000);
        expect(auth.getSession).not.toHaveBeenCalled();
        expect(auth.updateUser).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1_500);
        expect(auth.getSession).toHaveBeenCalledTimes(1);
        expect(auth.getUser).not.toHaveBeenCalled();
        expect(auth.updateUser).toHaveBeenCalledWith({ data: { page_journey: journey('/pricing', '/dashboard') } });
    });

    it('writes nothing for a returning user whose journey went over the same pages', async () => {
        tracked(['/dashboard']);
        signedIn({ first_seen_at: 'earlier', page_journey: [{ path: '/dashboard', timestamp: '2026-11-01T08:00:00Z' }] });
        renderHook(() => useTrackingSync({ env: ENV }));
        await vi.advanceTimersByTimeAsync(11_000);
        expect(auth.getSession).toHaveBeenCalledTimes(1);
        expect(auth.updateUser).not.toHaveBeenCalled();
    });
});
