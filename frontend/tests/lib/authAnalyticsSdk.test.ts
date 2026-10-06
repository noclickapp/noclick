// @vitest-environment jsdom
// Verify the lock-pinned SDK's real event and direct feature-flag serializers.
// A transport fixture collects synthetic requests offline so persistence URL
// changes and synchronous history capture can be checked without live egress.

import { createRequire } from 'node:module';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { filterAuthAnalyticsEvent, installAuthAnalyticsNavigationGuard,
    resumeAuthAnalyticsRecording, sanitizeAuthAnalyticsPersistence } from '~/lib/authAnalyticsPrivacy';

// Exercise the installed, lock-pinned SDK internals with only the transport
// replaced. No mocked URL-property assembler or flag serializer.
const require = createRequire(import.meta.url);
const { PostHog } = require('posthog-js/lib/src/posthog-core.js');
const { PostHogFeatureFlags } = require('posthog-js/lib/src/posthog-featureflags.js');
const { HistoryAutocapture } = require('posthog-js/lib/src/extensions/history-autocapture.js');
const { version } = require('posthog-js/package.json');
const privateUrl = 'https://app.example.test/api/auth/google/callback?code=fixture-auth-code&state=fixture-auth-state';
const originalHistory = { pushState: window.history.pushState, replaceState: window.history.replaceState };
const originalReferrer = Object.getOwnPropertyDescriptor(document, 'referrer');
let client: any;
let requests: any[];
let dispose: (() => void) | undefined;

beforeEach(() => {
    vi.useFakeTimers();
    window.history.replaceState(null, '', '/dashboard');
    requests = [];
    client = new PostHog();
    client._send_request = vi.fn((request) => requests.push(request));
    client._send_retriable_request = vi.fn((request) => requests.push(request));
});

afterEach(() => {
    client.historyAutocapture?.stop();
    client._remoteConfigLoader?.stop();
    dispose?.(); dispose = undefined;
    window.history.pushState = originalHistory.pushState;
    window.history.replaceState = originalHistory.replaceState;
    if (originalReferrer) Object.defineProperty(document, 'referrer', originalReferrer);
    else delete (document as any).referrer;
    vi.clearAllTimers();
    vi.useRealTimers();
});

function initialize(loaded = sanitizeAuthAnalyticsPersistence) {
    dispose = installAuthAnalyticsNavigationGuard(client);
    client.init('fixture-project', {
        defaults: '2026-05-30', api_host: 'https://analytics.example.test', persistence: 'memory',
        request_batching: false, disable_external_dependency_loading: true,
        opt_out_useragent_filter: true, person_profiles: 'always', loaded,
        __extensionClasses: { featureFlags: PostHogFeatureFlags, historyAutocapture: HistoryAutocapture },
        before_send: (event: any) => {
            sanitizeAuthAnalyticsPersistence(client);
            return filterAuthAnalyticsEvent(event);
        },
    });
}

function flagsRequest() {
    client.featureFlags._callFlagsEndpoint();
    return requests.find((request) => request.url.includes('/flags/'));
}

describe('PostHog installed SDK auth URL barriers', () => {
    it('pins the SDK attribution/flags/replay contract version', () => {
        expect(version).toBe('1.392.0');
    });

    it('real event assembly and direct flags serialization sanitize private document referrer', () => {
        Object.defineProperty(document, 'referrer', { configurable: true, value: privateUrl });
        initialize();
        client.capture('$pageview');
        const flags = flagsRequest();
        expect(flags).toBeTruthy();
        expect(flags.data.person_properties.$initial_referrer).toBe('https://app.example.test/api/auth/google/callback');
        expect(JSON.stringify(requests)).not.toContain('fixture-auth-code');
        expect(JSON.stringify(requests)).not.toContain('fixture-auth-state');
        expect(client.get_property('$initial_person_info').r).not.toContain('?');
        expect(client.get_property('$client_session_props').props.r).not.toContain('?');
    });

    it('cleans previously retained compact and legacy initial URLs before the first flags request', () => {
        initialize((sdk: any) => {
            // Stored-persistence fixture supplied at the real loaded boundary.
            sdk.register({ $initial_person_info: { r: privateUrl, u: privateUrl },
                $initial_referrer_info: { $referrer: privateUrl },
                $stored_person_properties: { $initial_referrer: privateUrl, plan: 'normal' } });
            sanitizeAuthAnalyticsPersistence(sdk);
        });
        const flags = flagsRequest();
        expect(flags.data.person_properties.plan).toBe('normal');
        expect(JSON.stringify(flags.data)).not.toContain('fixture-auth-code');
        expect(JSON.stringify(flags.data)).not.toContain('fixture-auth-state');
    });

    it('real synchronous history pageview cannot capture callback code/state before React effects', () => {
        initialize();
        client.capture('$pageview');
        requests.length = 0;
        window.history.pushState(null, '', '/api/auth/google/callback?code=fixture-auth-code&state=fixture-auth-state');
        expect(client.config.disable_session_recording).toBe(true);
        expect(requests).toEqual([]);
        // Even first-person/session properties updated before before_send
        // cannot become a later direct flags payload.
        expect(JSON.stringify(flagsRequest().data)).not.toContain('fixture-auth-code');
        expect(JSON.stringify(requests)).not.toContain('fixture-auth-state');
        window.history.replaceState(null, '', '/pricing?utm_source=campaign');
        expect(client.config.disable_session_recording).toBe(true);
        resumeAuthAnalyticsRecording();
        expect(client.config.disable_session_recording).toBe(false);
        client.capture('normal-event', { selection: 'pricing' });
        expect(requests.some((request) => request.data?.event === 'normal-event')).toBe(true);
    });

    it('preserves normal campaign and referrer URL properties in events and flag payloads', () => {
        Object.defineProperty(document, 'referrer', { configurable: true, value: 'https://search.example.test/?q=workflow' });
        window.history.replaceState(null, '', '/pricing?utm_source=campaign');
        initialize();
        client.capture('$pageview');
        const flags = flagsRequest();
        expect(flags.data.person_properties.$initial_utm_source).toBe('campaign');
        expect(flags.data.person_properties.$initial_referrer).toBe('https://search.example.test/?q=workflow');
        expect(requests.some((request) => request.data?.properties?.$current_url.includes('utm_source=campaign'))).toBe(true);
    });
});
