// Keep auth response URLs out of hosted analytics and buffered session replay.
// This shared boundary handles initial documents, raw history changes and the
// pinned SDK's later attribution/feature-flag requests without loading the SDK.
import type { CaptureResult } from 'posthog-js';

interface AnalyticsLocation {
    pathname: string;
    search?: string;
    hash?: string;
}

// All integration auth routes, including nested callbacks and newly added
// providers. Confirm/recovery can also render an error document at their URL.
const AUTH_CALLBACK_PATH = /^\/api\/auth(?:\/|$)|^\/auth\/(callback|confirm|reset-password)(?:\/|$)/i;
const AUTH_PARAMETERS = new Set([
    'code', 'state', 'access_token', 'refresh_token', 'id_token', 'token_hash',
    'oauth_token', 'oauth_verifier',
]);

export function isAuthAnalyticsPath(pathname: string): boolean {
    try {
        pathname = decodeURIComponent(pathname);
    } catch { /* The raw path can still match a known auth namespace. */ }
    return AUTH_CALLBACK_PATH.test(pathname);
}

function hasAuthParameters(value: string): boolean {
    const params = new URLSearchParams(value.replace(/^[?#]/, ''));
    return [...params.keys()].some((key) => AUTH_PARAMETERS.has(key.toLowerCase()));
}

/** Auth responses are private even when an implicit flow lands on login/dashboard. */
export function isAuthAnalyticsExcluded(location: AnalyticsLocation): boolean {
    return isAuthAnalyticsPath(location.pathname)
        || hasAuthParameters(location.search ?? '')
        || hasAuthParameters(location.hash ?? '');
}

const URL_PROPERTIES = ['$current_url', '$referrer', '$initial_referrer', '$initial_current_url',
    '$session_entry_url', '$session_entry_referrer'];

function sanitizeUrls(properties: Record<string, unknown>, keys = URL_PROPERTIES): Record<string, unknown> {
    let out = properties;
    for (const key of keys) {
        const url = privateAnalyticsUrl(properties[key]);
        if (!url || (!url.search && !url.hash)) continue;
        if (out === properties) out = { ...properties };
        url.search = '';
        url.hash = '';
        out[key] = url.href;
    }
    return out;
}

function record(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

interface PersistenceClient {
    get_property: (key: string) => unknown;
    register: (properties: Record<string, unknown>) => void;
}

/**
 * PostHog 1.392.0 also sends initial person URLs directly to /flags, outside
 * before_send. Use public persistence methods before its first request, and
 * after capture has updated attribution, to remove private URL query/hash
 * parts. These compact attribution keys are pinned by the SDK regression.
 */
export function sanitizeAuthAnalyticsPersistence(client: PersistenceClient): void {
    for (const key of ['$initial_person_info', '$initial_referrer_info', '$initial_campaign_params',
        '$stored_person_properties', '$client_session_props']) {
        const value = client.get_property(key);
        if (!record(value)) continue;
        let safe = sanitizeUrls(value, key === '$initial_person_info' ? ['r', 'u'] : URL_PROPERTIES);
        if (key === '$client_session_props' && record(value.props)) {
            const props = sanitizeUrls(value.props, ['r', 'u', ...URL_PROPERTIES]);
            if (props !== value.props) safe = { ...safe, props };
        }
        if (safe !== value) client.register({ [key]: safe });
    }
}

function privateReplayUrl(value: unknown, seen = new WeakSet<object>()): boolean {
    if (!value || typeof value !== 'object' || seen.has(value)) return false;
    seen.add(value);
    return Object.entries(value).some(([key, nested]) =>
        (['href', 'src', 'url', 'referrer'].includes(key) && privateAnalyticsUrl(nested) !== null)
        || privateReplayUrl(nested, seen));
}

function privateAnalyticsUrl(value: unknown): URL | null {
    if (typeof value !== 'string' || !value) return null;
    try {
        const url = new URL(value, 'https://analytics.invalid');
        return isAuthAnalyticsExcluded(url) ? url : null;
    } catch {
        return null;
    }
}

/**
 * Capture-time barrier for an initialized SDK during SPA navigation. History
 * events can run before React's effects, so consult the live browser URL here.
 * Also reject deferred callback pageviews after the URL has become safe again.
 */
export function filterAuthAnalyticsEvent(event: CaptureResult | null): CaptureResult | null {
    if (!event) return null;
    if (typeof window !== 'undefined' && isAuthAnalyticsExcluded(window.location)) return null;
    if (privateAnalyticsUrl(event.properties?.$current_url)) return null;
    if (event.event === '$snapshot' && privateReplayUrl(event.properties?.$snapshot_data)) return null;

    // A subsequent safe page can carry a callback URL as a referrer/initial URL.
    // Keep normal events and attribution, removing only those private URL parts.
    let properties = sanitizeUrls(event.properties);
    for (const key of ['$set', '$set_once']) {
        const nested = properties[key];
        if (!nested || typeof nested !== 'object' || Array.isArray(nested)) continue;
        const safe = sanitizeUrls(nested as Record<string, unknown>);
        if (safe === nested) continue;
        if (properties === event.properties) properties = { ...properties };
        properties[key] = safe;
    }
    let out = properties === event.properties ? event : { ...event, properties };
    for (const key of ['$set', '$set_once'] as const) {
        const value = out[key];
        if (!record(value)) continue;
        const safe = sanitizeUrls(value);
        if (safe !== value) out = { ...out, [key]: safe };
    }
    return out;
}

interface RecordingClient {
    config: { disable_session_recording: boolean };
    stopSessionRecording: () => void;
    set_config: (config: { disable_session_recording: boolean }) => void;
}

interface NavigationGuard {
    dispose: () => void;
    resume: () => void;
    setClient: (client: RecordingClient) => void;
    listeners: Set<() => void>;
}

const navigationGuards = new WeakMap<History, NavigationGuard>();

/**
 * Install before SDK initialization/history observers. Pause replay before an
 * SPA callback URL or its DOM can enter a buffered/compressed snapshot; a
 * send-time URL filter cannot inspect compressed replay payloads. Restore the
 * existing replay setting on a safe route, without changing consent/opt-out.
 * The boundary lives with the initialized SDK for this document.
 */
function navigationGuard(): NavigationGuard {
    const history = window.history;
    const existing = navigationGuards.get(history);
    if (existing) return existing;
    const listeners = new Set<() => void>();
    let client: RecordingClient | undefined;
    let paused = false;
    let previousDisabled = false;
    const pause = () => {
        if (!client) return;
        if (!paused) {
            previousDisabled = client.config.disable_session_recording;
            paused = true;
        }
        client.stopSessionRecording();
    };
    const sync = () => {
        if (isAuthAnalyticsExcluded(window.location)) {
            pause();
        }
        listeners.forEach((listener) => listener());
    };
    const resume = () => {
        if (client && !isAuthAnalyticsExcluded(window.location) && paused) {
            paused = false;
            client.set_config({ disable_session_recording: previousDisabled });
        }
    };
    const originals = { pushState: history.pushState, replaceState: history.replaceState };
    const wrap = (original: History['pushState']): History['pushState'] => function (this: History, ...args) {
        const target = new URL(String(args[2] ?? window.location.href), window.location.href);
        if (isAuthAnalyticsExcluded(target)) pause();
        try {
            const result = original.apply(this, args);
            listeners.forEach((listener) => listener());
            return result;
        } catch (error) {
            // A rejected navigation left the previous safe DOM and URL intact.
            resume();
            throw error;
        }
    };
    const pushState = wrap(originals.pushState);
    const replaceState = wrap(originals.replaceState);
    history.pushState = pushState;
    history.replaceState = replaceState;
    // Capture phase precedes the router and SDK's usual bubbling listeners.
    window.addEventListener('popstate', sync, true);
    window.addEventListener('hashchange', sync, true);
    const dispose = () => {
        window.removeEventListener('popstate', sync, true);
        window.removeEventListener('hashchange', sync, true);
        if (history.pushState === pushState) history.pushState = originals.pushState;
        if (history.replaceState === replaceState) history.replaceState = originals.replaceState;
        navigationGuards.delete(history);
    };
    const guard = { dispose, resume, listeners, setClient: (value: RecordingClient) => { client = value; sync(); } };
    navigationGuards.set(history, guard);
    return guard;
}

export function installAuthAnalyticsNavigationGuard(client: RecordingClient): () => void {
    const guard = navigationGuard();
    guard.setClient(client);
    return guard.dispose;
}

/** Observe raw history/hash changes too: implicit login scrubs without Router navigation. */
export function subscribeAuthAnalyticsLocation(listener: () => void): () => void {
    const { listeners } = navigationGuard();
    listeners.add(listener);
    return () => { listeners.delete(listener); };
}

export function authAnalyticsLocationSnapshot(): string {
    return window.location.href;
}

/** Resume only after React has committed a safe destination, not at pushState time. */
export function resumeAuthAnalyticsRecording(): void {
    navigationGuards.get(window.history)?.resume();
}
