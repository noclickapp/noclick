// The key proxy: `/api/v1/…` on this app is `/v1/…` on NoClick's API, sent with the app's key, so the browser's SDK
// client works without ever holding it. The gate (gate.server.ts) has already required the owner's session and refused
// requests from other sites by the time a request gets here.
import type { RouterContextProvider } from 'react-router';
import { BROWSER_BEARER } from '@/sdk/proxied';
import { appConfigContext, noclickApiKey } from './config.server';
import { apiError } from './responses.server';

/** The request headers passed on: the ones the SDK sets. Everything else the browser sends (its cookies, its
 *  Authorization, where it came from) stays here. */
export const FORWARDED_REQUEST_HEADERS = ['accept', 'content-type', 'idempotency-key', 'noclick-user'] as const;

/**
 * The response headers passed back, and no others: what the SDK reads (the request's id, both ways the API names it,
 * a retry's wait, whether a write was a replay) and what a body or a download needs. Anything else the API sends
 * (its cookies, its connection's headers, policies and reporting for its own origin) would act on this app's origin
 * instead, so it stays here. A redirect's Location is passed back rewritten.
 */
export const PASSED_RESPONSE_HEADERS = [
    'content-type',
    'content-disposition',
    'content-language',
    'content-range',
    'accept-ranges',
    'etag',
    'last-modified',
    'retry-after',
    'idempotent-replayed',
    'x-request-id',
    'cf-ray',
] as const;

/** Set on every proxied answer: never stored or transformed on the way (a compressing proxy would hold back a stream
 *  of events), never sniffed as another type, readable by this app's pages only, and never run as a page. */
const PROXY_RESPONSE_HEADERS = {
    'cache-control': 'no-store, no-transform',
    'content-security-policy': "default-src 'none'; frame-ancestors 'none'; sandbox",
    'x-content-type-options': 'nosniff',
    'cross-origin-resource-policy': 'same-origin',
};

const NULL_BODY_STATUSES = new Set([101, 204, 205, 304]);
const PREFIX = '/api';

/**
 * The API path a request names (`/v1/…`, still percent-encoded, with its query), or null when it isn't one the proxy
 * forwards: outside `/api/v1/`, with an empty segment (`//`), or with a segment that is or hides `.`, `..`, a
 * backslash or a control character once decoded.
 */
export function apiPathOf(url: URL): string | null {
    if (!url.pathname.startsWith(`${PREFIX}/v1/`)) return null;
    const path = url.pathname.slice(PREFIX.length);
    const segments = path.split('/').slice(1);
    for (const [index, segment] of segments.entries()) {
        // A trailing slash is the only empty segment allowed.
        if (segment === '') {
            if (index === segments.length - 1 && index > 1) continue;
            return null;
        }
        let decoded: string;
        try {
            decoded = decodeURIComponent(segment);
        } catch {
            return null;
        }
        if (/[\\\u0000-\u001f\u007f]/.test(decoded)) return null;
        if (decoded.split('/').some((part) => part === '.' || part === '..')) return null;
    }
    return path + url.search;
}

export interface Upstream {
    /** NoClick's API, without a trailing slash. */
    apiUrl: string;
    /** The NoClick key the call is made with. */
    key: string;
}

/** Forwards `request` to NoClick's API with the app's key, streaming the body both ways. */
export async function forward(request: Request, upstream: Upstream, fetchImpl: typeof fetch = fetch): Promise<Response> {
    // Only the app's own SDK client sends this. A link opened from a mail app, a page's `<img>` or `<form>`, or a
    // navigation can't set Authorization, so none of them reaches the API, and no answer is ever opened as a page.
    if (request.headers.get('authorization') !== `Bearer ${BROWSER_BEARER}`) {
        return apiError(403, {
            type: 'permission_denied',
            message: 'This app’s API answers its own pages’ calls only.',
            next_step: `Call it through the app’s SDK client, which sends Authorization: Bearer ${BROWSER_BEARER}.`,
        });
    }
    const path = apiPathOf(new URL(request.url));
    const base = new URL(upstream.apiUrl);
    const target = path === null ? null : new URL(upstream.apiUrl + path);
    // The path can't move the request to another host, or out of /v1/, but check what was built rather than trust it.
    if (path === null || target === null || target.origin !== base.origin || !target.pathname.startsWith(`${base.pathname.replace(/\/$/, '')}/v1/`)) {
        return apiError(400, {
            type: 'invalid_request',
            message: 'This app forwards only NoClick API paths, under /api/v1/.',
        });
    }

    let response: Response;
    try {
        const headers = new Headers();
        for (const name of FORWARDED_REQUEST_HEADERS) {
            const value = request.headers.get(name);
            if (value !== null) headers.set(name, value);
        }
        headers.set('authorization', `Bearer ${upstream.key}`);
        const hasBody = request.method !== 'GET' && request.method !== 'HEAD' && request.body !== null;
        response = await fetchImpl(target, {
            method: request.method,
            headers,
            body: hasBody ? request.body : null,
            // A body is passed on as it arrives, not read whole first.
            ...(hasBody ? { duplex: 'half' } : {}),
            redirect: 'manual',
            // The browser going away (a closed tab, a stopped stream of events) ends the call to the API.
            signal: request.signal,
        } as RequestInit);
    } catch (error) {
        if (!request.signal.aborted) {
            // The error's name and code only: its message, or the request it describes, may carry the key.
            const reason = (error as { cause?: { code?: unknown } }).cause?.code ?? (error as Error).name;
            console.error(`The key proxy couldn't reach NoClick's API at ${base.origin} (${String(reason)}).`);
        }
        return apiError(502, {
            type: 'upstream_error',
            message: 'This app’s server couldn’t reach NoClick’s API.',
            next_step: 'Check NOCLICK_API_URL and the server’s network connection, then try again.',
        });
    }

    const out = new Headers();
    for (const name of PASSED_RESPONSE_HEADERS) {
        const value = response.headers.get(name);
        if (value !== null) out.set(name, value);
    }
    const location = response.headers.get('location');
    if (location !== null) out.set('location', localLocation(location, target, base));
    for (const [name, value] of Object.entries(PROXY_RESPONSE_HEADERS)) out.set(name, value);

    const body = NULL_BODY_STATUSES.has(response.status) || request.method === 'HEAD' ? null : response.body;
    return new Response(body, { status: response.status, statusText: response.statusText, headers: out });
}

/** A redirect to another API path, as this app's path for it; any other address as the API gave it. */
function localLocation(location: string, target: URL, base: URL): string {
    let url: URL;
    try {
        url = new URL(location, target);
    } catch {
        return location;
    }
    const root = base.pathname.replace(/\/$/, '');
    if (url.origin !== base.origin || !url.pathname.startsWith(`${root}/v1/`)) return url.toString();
    return PREFIX + url.pathname.slice(root.length) + url.search + url.hash;
}

/** The proxy route's loader and action: forwards with the app's key, to the API the gate checked the config for. */
export function proxy({ request, context }: { request: Request; context: Readonly<RouterContextProvider> }): Promise<Response> {
    return forward(request, { apiUrl: context.get(appConfigContext).apiUrl, key: noclickApiKey() });
}
