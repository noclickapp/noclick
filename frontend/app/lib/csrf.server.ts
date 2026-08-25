// CSRF protection using double-submit cookie pattern.
// Generates a signed CSRF token stored in both a cookie and a hidden form field.
// On POST, validates that the form token matches the cookie token.

import { createCookie } from 'react-router';
import { json, type TypedResponse } from '~/lib/routerResponse';
import { requestIsHttps } from './requestScheme';
import { getServerSecret } from './serverSecrets';

// Shared user-facing copy for a stale CSRF/session token. Keep in one place so
// every form surfaces identical wording.
export const SESSION_EXPIRED_MESSAGE =
    'Your session has expired. Please try again.';

// `secure` must track the actual scheme rather than being hardcoded: a browser
// silently drops a Secure cookie on a plain-HTTP origin, which for a self-hosted
// install (LAN address, TLS-less reverse proxy) meant every submit failed CSRF
// AND the self-heal response couldn't seat a cookie either — an unbreakable loop.
const csrfCookieFor = (request: Request) =>
    createCookie('csrf_token', {
        httpOnly: true,
        secure: requestIsHttps(request),
        sameSite: 'lax',
        path: '/',
        maxAge: 60 * 60 * 24, // 24 hours — long enough to survive realistic open-tab durations
        secrets: [getServerSecret('CSRF_SECRET')],
    });

/**
 * Generates a CSRF token and returns both the token value and the Set-Cookie header.
 * Use in loaders to pass the token to forms.
 */
export async function generateCsrfToken(request: Request): Promise<{
    token: string;
    cookieHeader: string;
}> {
    // Check if there's already a valid token in the cookie
    const existingToken = await csrfCookieFor(request).parse(
        request.headers.get('Cookie')
    );
    if (existingToken && typeof existingToken === 'string') {
        return {
            token: existingToken,
            cookieHeader: await csrfCookieFor(request).serialize(existingToken),
        };
    }

    // Generate a new token
    const token = crypto.randomUUID();
    const cookieHeader = await csrfCookieFor(request).serialize(token);
    return { token, cookieHeader };
}

/**
 * Returns whether the form's CSRF token matches the cookie. Use this when the
 * caller wants to surface a friendly error in actionData (Remix re-runs the
 * loader after the action, so the form re-renders with a fresh token).
 *
 * Pass `formData` when the caller has already consumed the request body (the
 * request body is a one-shot stream); otherwise a fresh clone is parsed here.
 */
export async function isCsrfTokenValid(
    request: Request,
    formData?: FormData
): Promise<boolean> {
    const fields = formData ?? (await request.clone().formData());
    const formToken = fields.get('csrf_token');
    const cookieToken = await csrfCookieFor(request).parse(
        request.headers.get('Cookie')
    );
    return Boolean(formToken && cookieToken && formToken === cookieToken);
}

/**
 * Validates the CSRF token for a user-facing form submission, with built-in
 * self-healing. On failure (the usual cause is a stale cookie/token pair — a
 * tab left open past the cookie's lifetime, or a client-side nav where the
 * loader's Set-Cookie never applied) this returns a ready-to-send 400 that:
 *   1. mints a fresh token+cookie — action responses reliably apply Set-Cookie
 *      client-side, unlike loader revalidation, so the cookie is guaranteed
 *      fresh after this response, and
 *   2. carries the fresh `csrfToken` so the form can re-sync immediately and
 *      the *next* submit succeeds without the user reloading the page.
 * Returns `null` when the token is valid. Usage:
 *   const csrfFailure = await csrfFailureResponse(request);
 *   if (csrfFailure) return csrfFailure;
 */
export async function csrfFailureResponse(
    request: Request,
    formData?: FormData
): Promise<TypedResponse<{ error: string; csrfToken: string }> | null> {
    if (await isCsrfTokenValid(request, formData)) return null;
    const { token, cookieHeader } = await generateCsrfToken(request);
    return json(
        { error: SESSION_EXPIRED_MESSAGE, csrfToken: token },
        { status: 400, headers: { 'Set-Cookie': cookieHeader } }
    );
}

/**
 * Validates the CSRF token from a form submission against the cookie.
 * Throws a 403 Response if validation fails — prefer `csrfFailureResponse` for
 * user-facing forms so an expired cookie self-heals instead of surfacing as a
 * dead-end 403/error that needs a manual page reload.
 */
export async function validateCsrfToken(request: Request): Promise<void> {
    if (!(await isCsrfTokenValid(request))) {
        throw new Response('Invalid CSRF token', { status: 403 });
    }
}

/**
 * Helper function for public route loaders that need auth status and CSRF token.
 * Returns loader data with isAuthenticated flag and csrfToken, along with Set-Cookie header.
 *
 * Usage in route loaders:
 * ```typescript
 * export async function loader({ request }: LoaderFunctionArgs) {
 *     return await createPublicLoaderData(request);
 * }
 *
 * // Or merge with additional data:
 * export async function loader({ request }: LoaderFunctionArgs) {
 *     const { data, headers } = await createPublicLoaderData(request);
 *     return json({ ...data, customField: 'value' }, { headers });
 * }
 * ```
 */
export async function createPublicLoaderData(request: Request) {
    const { createServerSupabaseClient } = await import('~/lib/supabase');
    // NOT `await import('react-router')` — React Router 7 removed `json`; the
    // dynamic destructure returns undefined and makes every caller fail.
    const { json } = await import('~/lib/routerResponse');

    // Pass `headers` so a refreshed (rotated) session is persisted. getUser()
    // refreshes an expired access token before validating; without headers the
    // new cookies were dropped, burning the single-use refresh token. A logged-in
    // user idling on a public page (landing, pricing) would then get bounced to
    // the login screen and only recover after a manual reload. Callers must
    // forward this response's headers (e.g. `{ headers: authResponse.headers }`).
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    const {
        data: { user },
    } = await supabase.auth.getUser();
    const { token: csrfToken, cookieHeader } = await generateCsrfToken(request);
    headers.append('Set-Cookie', cookieHeader);

    return json({ isAuthenticated: !!user, csrfToken }, { headers });
}
