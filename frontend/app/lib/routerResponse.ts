/**
 * Transitional replacement for Remix's `json()`, which React Router 7 removed.
 *
 * Returns a real `Response`, exactly as `json()` did, so the migration is
 * behaviour-preserving at all ~40 call sites — several of which are HTTP
 * endpoints (Stripe and Pipedrive webhooks, OAuth callbacks) whose callers,
 * and tests, read `.status` and `.json()` off the result. React Router's own
 * `data()` helper returns a wrapper the router unwraps later, which is right
 * for loaders but not for a route that IS an endpoint.
 *
 * Loaders may return plain objects instead; that gives better inference. This
 * exists so that change can happen per route rather than as part of the
 * framework migration.
 */
export function json<T>(payload: T, init?: number | ResponseInit): Response {
    const responseInit: ResponseInit =
        typeof init === 'number' ? { status: init } : (init ?? {});
    const headers = new Headers(responseInit.headers);
    if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json; charset=utf-8');
    }
    return new Response(JSON.stringify(payload), { ...responseInit, headers });
}

export type TypedResponse<T = unknown> = Response & { __payload?: T };
