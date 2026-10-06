// @vitest-environment jsdom
// Exercise auth route coverage, capture attribution and replay navigation order.
// These synthetic regressions prevent private callback values from leaking into
// ordinary analytics while retaining benign marketing and dashboard data.

import { afterEach, describe, expect, it, vi } from 'vitest';
import routes from '~/routes';
import { filterAuthAnalyticsEvent, installAuthAnalyticsNavigationGuard, isAuthAnalyticsExcluded,
    resumeAuthAnalyticsRecording, sanitizeAuthAnalyticsPersistence } from '~/lib/authAnalyticsPrivacy';
import type { CaptureResult } from 'posthog-js';

const event = (properties: Record<string, unknown>, name = '$pageview') =>
    ({ event: name, properties } as CaptureResult);
const privateUrl = 'https://app.example.test/api/auth/google/callback?code=fixture-code&state=fixture-state';
let dispose: (() => void) | undefined;
afterEach(() => { dispose?.(); dispose = undefined; window.history.replaceState(null, '', '/'); });

describe('auth analytics URL policy', () => {
    it('covers every actual integration callback and auth return route', () => {
        const callbacks = routes.filter((entry) => entry.file.includes('/api/auth/') && entry.file.includes('callback'));
        expect(callbacks).toHaveLength(52);
        for (const entry of callbacks) {
            expect(isAuthAnalyticsExcluded(new URL(`https://app.example.test/${entry.path}`)), entry.file).toBe(true);
        }
        for (const path of ['/auth/callback', '/auth/confirm', '/auth/reset-password', '/api/auth/drip/callback']) {
            expect(isAuthAnalyticsExcluded(new URL(`https://app.example.test${path}`))).toBe(true);
        }
    });

    it.each(['code', 'state', 'access_token', 'refresh_token', 'id_token', 'token_hash', 'oauth_token', 'oauth_verifier', '%63ode', 'STATE'])(
        'excludes %s query and hash on any landing route', (key) => {
            for (const prefix of ['?', '#']) {
                expect(isAuthAnalyticsExcluded(new URL(`https://app.example.test/dashboard${prefix}${key}=fixture`))).toBe(true);
            }
        });

    it.each(['/', '/pricing?utm_source=campaign', '/dashboard?focus=credentials', '/auth/login?next=/dashboard',
        '/api/authorization', '/blog/a#section', '/workflow/example?embed=true'])(
        'preserves ordinary route %s', (path) => {
            expect(isAuthAnalyticsExcluded(new URL(`https://app.example.test${path}`))).toBe(false);
        });

    it('decodes callback path segments without throwing on malformed encoding', () => {
        expect(isAuthAnalyticsExcluded({ pathname: '/api/%61uth/google/callback' })).toBe(true);
        expect(isAuthAnalyticsExcluded({ pathname: '/api/auth/%invalid' })).toBe(true);
    });
});

describe('capture and retained attribution', () => {
    it('drops callback captures and deferred callback pageviews', () => {
        window.history.replaceState(null, '', '/auth/callback?code=fixture');
        expect(filterAuthAnalyticsEvent(event({ action: 'callback' }))).toBeNull();
        window.history.replaceState(null, '', '/dashboard');
        expect(filterAuthAnalyticsEvent(event({ $current_url: privateUrl }))).toBeNull();
    });

    it('sanitizes event, nested and top-level person attribution without mutating input', () => {
        const input = event({ $current_url: 'https://app.example.test/dashboard', $referrer: privateUrl,
            $session_entry_url: privateUrl, $session_entry_referrer: privateUrl,
            $set_once: { $initial_referrer: privateUrl, campaign: 'ordinary' } });
        input.$set_once = { $initial_current_url: privateUrl };
        input.$set = { $referrer: privateUrl };
        const safe = filterAuthAnalyticsEvent(input)!;
        expect(JSON.stringify(safe)).not.toContain('fixture-code');
        expect(JSON.stringify(safe)).not.toContain('fixture-state');
        expect(input.properties.$referrer).toBe(privateUrl);
        expect(safe.properties.$current_url).toBe('https://app.example.test/dashboard');
        expect(safe.properties.$set_once).toMatchObject({ campaign: 'ordinary' });
    });

    it('keeps benign URL attribution and ordinary replay unchanged', () => {
        const input = event({ $current_url: 'https://app.example.test/pricing?utm_source=campaign',
            $initial_referrer: 'https://search.example.test/?q=workflow' });
        expect(filterAuthAnalyticsEvent(input)).toBe(input);
        const replay = event({ $snapshot_data: [{ type: 4, data: { href: 'https://app.example.test/dashboard' } }] }, '$snapshot');
        expect(filterAuthAnalyticsEvent(replay)).toBe(replay);
    });

    it('drops deferred uncompressed replay containing a private URL', () => {
        const replay = event({ $snapshot_data: [{ type: 4, data: { href: privateUrl } }] }, '$snapshot');
        expect(filterAuthAnalyticsEvent(replay)).toBeNull();
    });

    it('cleans all pinned URL-bearing persistence shapes while preserving normal fields', () => {
        const props: Record<string, any> = {
            $initial_person_info: { r: privateUrl, u: privateUrl },
            $initial_referrer_info: { $referrer: privateUrl, $referring_domain: 'app.example.test' },
            $initial_campaign_params: { $current_url: privateUrl, utm_source: 'campaign' },
            $stored_person_properties: { $initial_referrer: privateUrl, email: 'fixture@example.test' },
            $client_session_props: { sessionId: 'fixture-session', props: { r: privateUrl, u: privateUrl } },
        };
        sanitizeAuthAnalyticsPersistence({ get_property: (key) => props[key], register: (next) => Object.assign(props, next) });
        expect(JSON.stringify(props)).not.toContain('fixture-code');
        expect(JSON.stringify(props)).not.toContain('fixture-state');
        expect(props.$client_session_props.sessionId).toBe('fixture-session');
        expect(props.$initial_campaign_params.utm_source).toBe('campaign');
        expect(props.$stored_person_properties.email).toBe('fixture@example.test');
    });
});

describe('synchronous replay navigation boundary', () => {
    it.each([false, true])('pauses before private history and restores the existing recording setting %s only after safe commit', (disabled) => {
        const observations: string[] = [];
        const client = { config: { disable_session_recording: disabled },
            stopSessionRecording: vi.fn(() => { observations.push(window.location.pathname); client.config.disable_session_recording = true; }),
            set_config: vi.fn((next) => Object.assign(client.config, next)),
        };
        window.history.replaceState(null, '', '/dashboard');
        dispose = installAuthAnalyticsNavigationGuard(client);
        window.history.pushState(null, '', '/api/auth/google/callback?code=fixture');
        expect(observations).toEqual(['/dashboard']);
        expect(client.config.disable_session_recording).toBe(true);
        window.history.replaceState(null, '', '/pricing');
        expect(client.set_config).not.toHaveBeenCalled();
        resumeAuthAnalyticsRecording();
        expect(client.set_config).toHaveBeenCalledWith({ disable_session_recording: disabled });
    });

    it.each(['popstate', 'hashchange'])('pauses before bubbling %s observers', (name) => {
        const client = { config: { disable_session_recording: false },
            stopSessionRecording: vi.fn(() => { client.config.disable_session_recording = true; }), set_config: vi.fn() };
        dispose = installAuthAnalyticsNavigationGuard(client);
        window.history.replaceState(null, '', '/dashboard#access_token=fixture');
        client.config.disable_session_recording = false;
        const observer = vi.fn(() => expect(client.config.disable_session_recording).toBe(true));
        window.addEventListener(name, observer);
        try { window.dispatchEvent(new Event(name)); expect(observer).toHaveBeenCalledOnce(); }
        finally { window.removeEventListener(name, observer); }
    });
});
