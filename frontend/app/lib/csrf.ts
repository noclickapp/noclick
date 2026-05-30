// Client-safe CSRF helper. Pairs with csrf.server.ts's `csrfFailureResponse`,
// which (on a stale-session failure) returns a refreshed `csrfToken` alongside
// a freshly-set cookie. This resolves the freshest token to put back into the
// form so the next submit self-heals without a page reload. Kept out of
// csrf.server.ts so it can be imported into browser components.

/**
 * Returns the freshest CSRF token: the one handed back by a failed action or
 * fetcher submission (stale-session recovery) when present, otherwise the
 * loader-provided token. Accepts `unknown` recovery data so it works with the
 * varied action/fetcher result unions across routes.
 */
export function resolveCsrfToken(
    loaderToken: string | undefined,
    recovery: unknown,
): string | undefined {
    if (recovery && typeof recovery === 'object' && 'csrfToken' in recovery) {
        const token = (recovery as { csrfToken?: unknown }).csrfToken;
        if (typeof token === 'string') return token;
    }
    return loaderToken;
}
