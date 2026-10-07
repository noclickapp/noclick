// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const fixture = vi.hoisted(() => ({
    navigate: vi.fn(), sync: vi.fn(), sendAuthUpdate: vi.fn(), refresh: vi.fn(),
    getSession: vi.fn(), setSession: vi.fn(), onAuthStateChange: vi.fn(), unsubscribe: vi.fn(),
    state: { status: 'disconnected', lastErrorCode: 'token_expired', lastError: 'synthetic-hook-secret' },
}));
vi.mock('react-router', () => ({
    useNavigate: () => fixture.navigate,
    useLoaderData: () => ({ env: { SUPABASE_URL: 'https://fixture.invalid', SUPABASE_ANON_KEY: 'synthetic-public-fixture' } }),
}));
vi.mock('~/hooks/useSocketConnection', () => ({ useSocketConnection: () => fixture.state }));
vi.mock('~/lib/socket-receiver', () => ({ socketReceiver: { updateAllAuth: fixture.sync, sendAuthUpdate: fixture.sendAuthUpdate } }));
vi.mock('~/lib/supabase-client', () => ({ getExistingBrowserClient: () => ({ auth: { refreshSession: fixture.refresh } }) }));
vi.mock('~/lib/supabase', () => ({ createBrowserSupabaseClient: () => ({ auth: {
    getSession: fixture.getSession, refreshSession: fixture.refresh, setSession: fixture.setSession,
    onAuthStateChange: fixture.onAuthStateChange,
} }) }));

import { useSocketAuthMonitor } from '~/hooks/useSocketAuthMonitor';
import { useSocketTokenRefresh } from '~/hooks/useSocketTokenRefresh';

const SECRET = 'synthetic-hook-secret';
let logs: ReturnType<typeof vi.spyOn>[] = [];
let authChange: (event: string, session: { expires_at?: number } | null) => void;
const logged = () => JSON.stringify(logs.flatMap(log => log.mock.calls));

beforeEach(() => {
    vi.useFakeTimers();
    logs = ['log', 'warn', 'error'].map(method => vi.spyOn(console, method as 'log').mockImplementation(() => undefined));
    vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Forbidden synthetic fetch'); }));
    vi.stubGlobal('WebSocket', vi.fn(() => { throw new Error('Forbidden synthetic WebSocket'); }));
    fixture.navigate.mockReset(); fixture.sync.mockReset(); fixture.refresh.mockReset();
    fixture.sendAuthUpdate.mockReset(); fixture.getSession.mockReset(); fixture.setSession.mockReset();
    fixture.onAuthStateChange.mockImplementation(callback => {
        authChange = callback;
        return { data: { subscription: { unsubscribe: fixture.unsubscribe } } };
    });
    fixture.state = { status: 'disconnected', lastErrorCode: 'token_expired', lastError: SECRET };
    fixture.sendAuthUpdate.mockResolvedValue({ success: true });
    window.history.replaceState(null, '', '/dashboard');
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('actual auth hook diagnostic sinks', () => {
    it.each(['returned', 'thrown'])('keeps token-expiry recovery/redirect control and projects %s refresh errors', async mode => {
        if (mode === 'returned') fixture.refresh.mockResolvedValue({ error: { message: SECRET, opaque: SECRET } });
        else fixture.refresh.mockRejectedValue(new Error(SECRET));
        renderHook(() => useSocketAuthMonitor());
        await act(async () => { await Promise.resolve(); });
        expect(fixture.refresh).toHaveBeenCalledOnce();
        expect(fixture.navigate).toHaveBeenCalledWith('/auth/login', { replace: true });
        expect(fixture.sync).not.toHaveBeenCalled();
        expect(logged()).not.toContain(SECRET);
        expect(logged()).toContain('token_expired');
    });

    it('retains successful token-expiry recovery and definitive machine-code redirect', async () => {
        fixture.refresh.mockResolvedValue({ error: null });
        const hook = renderHook(() => useSocketAuthMonitor());
        await act(async () => { await Promise.resolve(); });
        expect(fixture.sync).toHaveBeenCalledOnce();
        expect(fixture.navigate).not.toHaveBeenCalled();
        hook.unmount();
        fixture.state.lastErrorCode = 'token_invalid';
        renderHook(() => useSocketAuthMonitor());
        expect(fixture.navigate).toHaveBeenCalledWith('/auth/login', { replace: true });
        expect(logged()).not.toContain(SECRET);
    });

    it.each(['returned', 'thrown'])('projects %s update_auth results without changing sync calls', async mode => {
        if (mode === 'returned') fixture.sendAuthUpdate.mockResolvedValue({ success: false, error: SECRET });
        else fixture.sendAuthUpdate.mockRejectedValue(new Error(SECRET));
        renderHook(() => useSocketTokenRefresh());
        act(() => authChange('INITIAL_SESSION', { expires_at: 1 }));
        await act(async () => { await vi.runOnlyPendingTimersAsync(); });
        expect(fixture.sync).toHaveBeenCalledOnce();
        expect(fixture.sendAuthUpdate).toHaveBeenCalledOnce();
        expect(logged()).not.toContain(SECRET);
    });

    it('projects visibility-refresh failures while preserving foreground refresh behavior', async () => {
        fixture.getSession.mockResolvedValue({ data: { session: { expires_at: 0 } }, error: null });
        fixture.refresh.mockRejectedValue(new Error(SECRET));
        renderHook(() => useSocketTokenRefresh());
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
        await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await Promise.resolve(); });
        expect(fixture.getSession).toHaveBeenCalledOnce();
        expect(fixture.refresh).toHaveBeenCalledOnce();
        expect(logged()).not.toContain(SECRET);
    });

    it('uses synthetic callback tokens unchanged and projects setSession failure', async () => {
        fixture.setSession.mockResolvedValue({ error: { message: SECRET, opaque: SECRET } });
        window.history.replaceState(null, '', `/dashboard#access_token=${SECRET}&refresh_token=synthetic-refresh-fixture`);
        renderHook(() => useSocketTokenRefresh());
        await act(async () => { await Promise.resolve(); });
        expect(fixture.setSession).toHaveBeenCalledWith({ access_token: SECRET, refresh_token: 'synthetic-refresh-fixture' });
        expect(window.location.hash).toBe('');
        expect(logged()).not.toContain(SECRET);
    });
});
