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
export function json<T>(payload: T, init?: number | ResponseInit): TypedResponse<T> {
    const responseInit: ResponseInit =
        typeof init === 'number' ? { status: init } : (init ?? {});
    const headers = new Headers(responseInit.headers);
    if (!headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json; charset=utf-8');
    }
    return new Response(JSON.stringify(payload), {
        ...responseInit,
        headers,
    }) as unknown as TypedResponse<T>;
}

declare const responsePayload: unique symbol;

// Deliberately omit Response.type from the static view. If this were a strict
// Response subtype, TypeScript would collapse an inferred
// `Response | TypedResponse<T>` (for loaders that can redirect) to Response and
// erase T. The runtime value is still the native Response created above; the
// omission only keeps loader/action payload inference intact.
export type TypedResponse<T = unknown> = Omit<Response, 'json' | 'type'> & {
    json(): Promise<T>;
    readonly [responsePayload]: T;
};

type ExtractJsonPayload<T> = T extends TypedResponse<infer Payload>
    ? Payload
    : never;

/** Extract the JSON body type from a route loader/action that uses this
 * response helper. React Router 7 deliberately maps native `Response` to
 * `never`, so route components use this type when the endpoint must stay a
 * real Response for direct HTTP callers. */
export type JsonPayloadOf<
    RouteFunction extends (...args: any[]) => unknown,
> = ExtractJsonPayload<Awaited<ReturnType<RouteFunction>>>;
