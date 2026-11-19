// The lab's /v1: a `fetch` that answers from canned routes, so the real client
// and the real pages run with no backend. Page fixture files
// (`pages/*.ts`, each exporting `routes`) are matched before the core ones, so
// a page may specialise a shared read. It answers as the API answers the
// signed-in owner, or (`actsAs: 'key'`) as it answers one of the account's own
// secret keys: the operations only the owner may make are refused, as the API
// refuses them, and the account is read without what only the owner sees.
import { refusedToAccountKey } from '../ownerOnly';
import { CORE_ROUTES, apiError, rememberOperation, type FixtureReply, type FixtureRequest, type FixtureRoute, type FixtureSet } from './core';

type RouteModule = { routes?: readonly FixtureRoute[] };

const PAGE_MODULES = import.meta.glob('./pages/*.ts', { eager: true }) as Record<string, RouteModule>;

export function pageRoutes(modules: Record<string, RouteModule> = PAGE_MODULES): FixtureRoute[] {
    return Object.keys(modules)
        .sort()
        .flatMap((name) => modules[name].routes ?? []);
}

/** `/v1/agents/:id` against `/v1/agents/abc` → `{ id: 'abc' }`, or null. */
export function matchPath(pattern: string, path: string): Record<string, string> | null {
    const want = pattern.split('/').filter(Boolean);
    const got = path.split('/').filter(Boolean);
    if (want.length !== got.length) return null;
    const params: Record<string, string> = {};
    for (let i = 0; i < want.length; i++) {
        if (want[i].startsWith(':')) params[want[i].slice(1)] = decodeURIComponent(got[i]);
        else if (want[i] !== got[i]) return null;
    }
    return params;
}

export interface FixtureFetchOptions {
    set: FixtureSet;
    /** Who the calls are answered as: the signed-in owner (the default), or one of the account's own secret keys. */
    actsAs?: 'owner' | 'key';
    /** Extra routes matched first (tests). */
    routes?: readonly FixtureRoute[];
    /** Sees every request, e.g. to assert the user header or query. */
    onRequest?: (request: FixtureRequest) => void;
}

function toResponse(reply: FixtureReply): Response {
    const status = reply.status ?? 200;
    const type = reply.raw === undefined ? 'application/json' : 'application/octet-stream';
    const headers = new Headers({ 'content-type': type, ...(reply.headers ?? {}) });
    const body = status === 204 ? null : reply.raw !== undefined ? reply.raw : JSON.stringify(reply.body ?? null);
    return new Response(body as BodyInit | null, { status, headers });
}

/** The API's answer to a key for an operation only the signed-in owner may make. */
export const OWNER_ONLY_REFUSAL = apiError(
    403,
    'permission_denied',
    'This call is for the signed-in account owner, not an API key.',
    "Make this call signed in to NoClick: send the session's access token as Authorization: Bearer <token>."
);

/** `GET /v1/account` as a key reads it: the account without who owns it, its keys, or what waits on its owner. */
export function accountForKey(account: Record<string, unknown>): Record<string, unknown> {
    const { email: _email, console_key_id: _key, spend_cap: _cap, counts, ...rest } = account;
    const { keys_active: _active, keys_used: _used, human_requests_awaiting_you: _waiting, ...counted } = (counts ?? {}) as Record<string, unknown>;
    return { ...rest, counts: counted };
}

export function makeFixtureFetch({ set, actsAs = 'owner', routes = [], onRequest }: FixtureFetchOptions): typeof fetch {
    const table = [...routes, ...pageRoutes(), ...CORE_ROUTES];
    return async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const text = typeof init?.body === 'string' ? init.body : null;
        const request: FixtureRequest = {
            set,
            method,
            path: url.pathname,
            params: {},
            query: url.searchParams,
            headers: new Headers(init?.headers),
            body: text ? JSON.parse(text) : null,
        };
        onRequest?.(request);
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return toResponse(OWNER_ONLY_REFUSAL);
        for (const route of table) {
            if (route.method !== method) continue;
            const params = matchPath(route.path, url.pathname);
            if (!params) continue;
            const reply = await route.reply({ ...request, params });
            rememberOperation(reply.body);
            if (actsAs === 'key' && method === 'GET' && url.pathname === '/v1/account' && (reply.status ?? 200) === 200) {
                return toResponse({ ...reply, body: accountForKey(reply.body as Record<string, unknown>) });
            }
            return toResponse(reply);
        }
        return toResponse(
            apiError(404, 'not_found', `No fixture for ${method} ${url.pathname}.`, 'Add a route to a file under fixtures/pages/.')
        );
    };
}
