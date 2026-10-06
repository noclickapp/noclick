// @vitest-environment jsdom
// Drive the actual provider, callback components and dashboard SSO hook offline.
// Only external SDK/auth/socket boundaries are fixtures; import timing, raw
// history scrubbing and route commits remain the production paths.

import { act, cleanup, render, screen } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { setTimeout as delay } from 'node:timers/promises';

const originalHistory = { pushState: window.history.pushState, replaceState: window.history.replaceState };
let imports = { sdk: 0, react: 0 };
let importGate: Promise<void> | undefined;
let localEdition = false;
let analyticsConfig: { key: string; apiHost: string; uiHost: string } | null;
let client: any;
let router: ReturnType<typeof createMemoryRouter> | undefined;
let props: Record<string, unknown>;
let captured: unknown[];

beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    imports = { sdk: 0, react: 0 };
    importGate = undefined;
    localEdition = false;
    analyticsConfig = { key: 'fixture-project', apiHost: 'https://analytics.example.test', uiHost: 'https://analytics.example.test' };
    props = {};
    captured = [];
    client = {
        config: { disable_session_recording: false },
        get_property: (key: string) => props[key],
        register: (next: Record<string, unknown>) => Object.assign(props, next),
        stopSessionRecording: vi.fn(() => { client.config.disable_session_recording = true; }),
        set_config: vi.fn((next) => Object.assign(client.config, next)),
        init: vi.fn((_key, config) => { client.config = { disable_session_recording: false, ...config }; config.loaded?.(client); }),
        capture: vi.fn((name, extra = {}) => {
            const input = { event: name, properties: { $current_url: window.location.href, ...extra } };
            const safe = client.config.before_send ? client.config.before_send(input) : input;
            if (safe) captured.push(safe);
        }),
        isFeatureEnabled: vi.fn(() => true),
        featureFlags: { getFlags: () => ['debug'] },
        onFeatureFlags: vi.fn(() => vi.fn()),
    };
    vi.doMock('~/lib/edition', () => ({ isLocalEdition: () => localEdition }));
    vi.doMock('~/lib/analyticsConfig', () => ({ ANALYTICS_CONFIG: analyticsConfig }));
    vi.doMock('posthog-js', async () => { imports.sdk++; await importGate; return { default: client }; });
    vi.doMock('posthog-js/react', () => {
        imports.react++;
        return { PostHogProvider: ({ children }: { children: ReactNode }) => children };
    });
    vi.doMock('~/lib/socket-receiver', () => ({ socketReceiver: {
        sendAuthUpdate: vi.fn(async () => ({ success: true })), updateAllAuth: vi.fn(),
    } }));
    vi.doMock('~/lib/oauthFlow.server', () => ({ oauthCallbackUrl: async (request: Request) => new URL(request.url) }));
    vi.doMock('~/lib/supabase', () => ({ createBrowserSupabaseClient: () => ({ auth: {
        setSession: vi.fn(async () => ({ error: null })),
        onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
        getSession: vi.fn(async () => ({ data: { session: null }, error: null })),
    } }) }));
});

afterEach(async () => {
    cleanup();
    router?.dispose();
    router = undefined;
    const privacy = await import('~/lib/authAnalyticsPrivacy');
    privacy.installAuthAnalyticsNavigationGuard(client)();
    window.history.pushState = originalHistory.pushState;
    window.history.replaceState = originalHistory.replaceState;
    window.history.replaceState(null, '', '/');
    delete (window as any).posthog;
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

async function mount(path: string, element: ReactNode = <div>Route content</div>, loader?: () => unknown) {
    window.history.replaceState(null, '', path);
    const { PHProvider } = await import('~/provider');
    router = createMemoryRouter([{ element: <PHProvider><Outlet /></PHProvider>, children: [
        { path: '*', element, loader },
    ] }], { initialEntries: [path] });
    render(<RouterProvider router={router} />);
    await act(async () => { await delay(25); });
    return router;
}

describe('actual PHProvider and auth route privacy', () => {
    it.each(['/api/auth/google/callback?code=fixture-code&state=fixture-state',
        '/api/auth/x/callback?code=fixture-code&state=fixture-state', '/auth/callback#access_token=fixture-token',
        '/auth/confirm?token_hash=fixture-hash', '/auth/reset-password',
        '/auth/login#access_token=fixture-token&refresh_token=fixture-refresh',
        '/dashboard#access_token=fixture-token'])(
        'blocked callback document %s imports neither analytics SDK', async (path) => {
            await mount(path);
            expect(screen.getByText('Route content')).toBeTruthy();
            expect(imports).toEqual({ sdk: 0, react: 0 });
            expect(client.init).not.toHaveBeenCalled();
            expect((window as any).posthog).toBeUndefined();
        });

    it.each(['google', 'x'])('actual %s callback component still completes opener delivery with no SDK import', async (provider) => {
        const { default: Callback } = provider === 'google'
            ? await import('~/routes/api/auth/google.callback') : await import('~/routes/api/auth/x/callback');
        const postMessage = vi.fn();
        Object.defineProperty(window, 'opener', { configurable: true, value: { postMessage } });
        vi.spyOn(window, 'close').mockImplementation(() => {});
        try {
            await mount(`/api/auth/${provider}/callback?code=fixture-code&state=fixture-state`, <Callback />,
                () => ({ success: true, code: 'fixture-code', credentialName: 'Fixture' }));
            await act(async () => { await Promise.resolve(); });
            expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ success: true, code: 'fixture-code' }), window.location.origin);
            expect(screen.getByText('Connected Successfully!')).toBeTruthy();
            expect(imports).toEqual({ sdk: 0, react: 0 });
        } finally { Object.defineProperty(window, 'opener', { configurable: true, value: null }); }
    });

    it.each(['/', '/pricing?utm_source=campaign', '/dashboard?focus=credentials', '/auth/login'])(
        'preserves hosted analytics on %s', async (path) => {
            await mount(path);
            expect(client.init).toHaveBeenCalledOnce();
            client.capture('$pageview');
            expect(captured).toHaveLength(1);
            expect((captured[0] as any).properties.$current_url).toBe(window.location.href);
        });

    it('keeps local edition free of SDK imports', async () => {
        localEdition = true;
        await mount('/dashboard');
        expect(imports).toEqual({ sdk: 0, react: 0 });
    });

    it('keeps embeds free of SDK imports', async () => {
        await mount('/dashboard?embed=true');
        expect(imports).toEqual({ sdk: 0, react: 0 });
    });

    it('keeps a disabled analytics configuration free of SDK imports', async () => {
        analyticsConfig = null;
        await mount('/pricing');
        expect(imports).toEqual({ sdk: 0, react: 0 });
    });

    it('rechecks live URL when the SDK chunks finish loading', async () => {
        let finish!: () => void;
        importGate = new Promise<void>((resolve) => { finish = resolve; });
        await mount('/pricing');
        window.history.pushState(null, '', '/api/auth/google/callback?code=fixture');
        await act(async () => { finish(); await importGate; });
        expect(client.init).not.toHaveBeenCalled();
    });

    it('blocks initialized capture and replay before SPA callback, then restores safe analytics after commit', async () => {
        const app = await mount('/dashboard');
        expect(client.init).toHaveBeenCalledOnce();
        window.history.pushState(null, '', '/api/auth/google/callback?code=fixture-code&state=fixture-state');
        expect(client.stopSessionRecording).toHaveBeenCalled();
        client.capture('$pageview');
        expect(captured).toEqual([]);
        await act(async () => { await app.navigate('/api/auth/google/callback?code=fixture-code&state=fixture-state'); });
        window.history.replaceState(null, '', '/pricing');
        expect(client.config.disable_session_recording).toBe(true);
        await act(async () => { await app.navigate('/pricing'); });
        expect(client.config.disable_session_recording).toBe(false);
        expect(client.init).toHaveBeenCalledOnce();
        client.capture('$pageview');
        expect(captured).toHaveLength(1);
        // Guard survives the provider's setClient re-render and normal navigation.
        window.history.pushState(null, '', '/auth/login#access_token=fixture');
        expect(client.config.disable_session_recording).toBe(true);
    });

    it('actual dashboard SSO hook scrubs hash without Router navigation and analytics initializes on the safe commit', async () => {
        const { useSocketTokenRefresh } = await import('~/hooks/useSocketTokenRefresh');
        function DashboardAuth() { useSocketTokenRefresh(); return <div>Dashboard fixture</div>; }
        await mount('/dashboard#access_token=fixture-token&refresh_token=fixture-refresh', <DashboardAuth />,
            () => ({ env: { SUPABASE_URL: 'https://auth.example.test', SUPABASE_ANON_KEY: 'fixture-public' } }));
        await act(async () => { await Promise.resolve(); await Promise.resolve(); });
        expect(window.location.hash).toBe('');
        expect(router!.state.location.hash).toContain('access_token');
        expect(client.init).toHaveBeenCalledOnce();
        client.capture('$pageview');
        expect(JSON.stringify(captured)).not.toContain('fixture-token');
        expect(JSON.stringify(captured)).not.toContain('fixture-refresh');
    });

    it('does not restore replay while callback DOM is still committed under a scrubbed safe URL', async () => {
        const app = await mount('/dashboard');
        window.history.pushState(null, '', '/api/auth/google/callback?code=fixture');
        await act(async () => { await app.navigate('/api/auth/google/callback?code=fixture'); });
        await act(async () => { window.history.replaceState(null, '', '/dashboard'); });
        expect(client.config.disable_session_recording).toBe(true);
        await act(async () => { await app.navigate('/dashboard'); });
        expect(client.config.disable_session_recording).toBe(false);
    });
});
