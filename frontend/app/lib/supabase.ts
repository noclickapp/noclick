import { createServerClient, serializeCookieHeader } from '@supabase/ssr';
import { createClient } from '@supabase/supabase-js';
import { devAuthCookieName, getSupabaseBrowserClient } from './supabase-client';
import { requestIsHttps } from './requestScheme';
import { json } from './routerResponse';

/**
 * Creates a Supabase client for server-side operations with cookie setting
 * Used in actions where we need to modify cookies (sign in/out)
 */
export function createServerSupabaseClient(
    request: Request,
    headers?: Headers
) {
    return createServerClient(
        process.env.SUPABASE_URL!,
        process.env.SUPABASE_ANON_KEY!, // Use anon key for frontend server operations
        {
            // Namespace the auth cookie per worktree in local dev (see devAuthCookieName).
            cookieOptions: (() => {
                const u = new URL(request.url);
                return { name: devAuthCookieName(u.hostname, u.port) };
            })(),
            cookies: {
                get: (key) => {
                    const cookie = request.headers
                        .get('Cookie')
                        ?.split('; ')
                        .find((row) => row.startsWith(`${key}=`));
                    // Handle cookie values that contain '=' (e.g., base64-encoded tokens)
                    if (!cookie) return undefined;
                    const eqIndex = cookie.indexOf('=');
                    return eqIndex === -1
                        ? undefined
                        : cookie.slice(eqIndex + 1);
                },
                set: (key, value, options) => {
                    if (headers) {
                        // Ensure Path=/ so cookies are available on all routes
                        // Set Secure and SameSite flags for security compliance
                        const cookieOptions = {
                            ...options,
                            path: '/',
                            secure: requestIsHttps(request),
                            sameSite: 'lax' as const,
                        };
                        headers.append(
                            'Set-Cookie',
                            serializeCookieHeader(key, value, cookieOptions)
                        );
                    }
                },
                remove: (key, options) => {
                    if (headers) {
                        // Ensure Path=/ matches the path used when setting
                        const cookieOptions = {
                            ...options,
                            path: '/',
                            secure: requestIsHttps(request),
                            sameSite: 'lax' as const,
                            maxAge: 0,
                        };
                        headers.append(
                            'Set-Cookie',
                            serializeCookieHeader(key, '', cookieOptions)
                        );
                    }
                },
            },
            auth: {
                persistSession: true, // Enable session persistence
                autoRefreshToken: true, // Enable auto-refresh for server-side
                detectSessionInUrl: true, // Important for OAuth callbacks
                flowType: 'pkce', // Use PKCE flow for better SSR compatibility
            },
        }
    );
}

/**
 * Gets the singleton Supabase client for client-side operations.
 * IMPORTANT: This returns a SINGLETON to prevent multiple client instances
 * which cause auth state race conditions and random logouts.
 * Requires env variables to be passed from loader data.
 */
export function createBrowserSupabaseClient(env: {
    SUPABASE_URL: string;
    SUPABASE_ANON_KEY: string;
}) {
    return getSupabaseBrowserClient(env);
}

export async function requireAuth(request: Request) {
    const { redirect } = await import('react-router');

    // Headers sink: any refresh-token rotation during getUser() lands here
    // and MUST ride every response — including the login redirects below —
    // or the rotated single-use token is silently burned and the browser
    // logs the user out later.
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);

    // Single auth call: getUser() reads the cookie session, refreshes an
    // expired access token via the rotating refresh token when needed, and
    // verifies the JWT with the auth server. (The old getSession → manual
    // <60s check → refreshSession → getUser choreography made three auth
    // round-trips and two independent refresh initiators per request —
    // rotation-race surface, see docs/auth-refactor-spec.md.)
    const {
        data: { user },
        error: userError,
    } = await supabase.auth.getUser();

    const url = new URL(request.url);
    const currentPath = url.pathname + url.search;
    const loginUrl =
        currentPath && currentPath !== '/'
            ? `/auth/login?next=${encodeURIComponent(currentPath)}`
            : '/auth/login';

    if (userError || !user) {
        throw redirect(loginUrl, { headers });
    }

    // In-memory read of the (possibly just-refreshed) session for callers
    // that need the access token — no additional refresh can trigger here.
    const {
        data: { session },
    } = await supabase.auth.getSession();
    if (!session) {
        throw redirect(loginUrl, { headers });
    }

    return { user, session, supabase, headers };
}

export async function requireGuest(request: Request) {
    const { redirect } = await import('react-router');

    // Pass `headers` so a rotated refresh token gets persisted. getUser() reads
    // the session from cookies and, when the access token has expired, refreshes
    // it using the single-use, rotating refresh token before validating. Without
    // headers the refreshed cookies were silently dropped — burning the rotating
    // token without saving its replacement. That desynced the server (which then
    // rendered this guest auth page) from the browser client, so the user could
    // only get in by manually reloading. Callers must forward these headers.
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    const {
        data: { user },
    } = await supabase.auth.getUser();

    if (user) {
        const url = new URL(request.url);
        const next = url.searchParams.get('next');
        // Only allow relative paths (prevents open redirect)
        const redirectTo =
            next && next.startsWith('/') && !next.startsWith('//')
                ? next
                : '/dashboard';
        throw redirect(redirectTo, { headers });
    }

    return {
        headers,
        env: {
            SUPABASE_URL: process.env.SUPABASE_URL!,
            SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY!,
        },
    };
}

/**
 * Auth + session-persistence helper for JSON resource routes (actions/loaders
 * that return JSON, never a redirect).
 *
 * getUser() refreshes an expired access token before validating, which rotates
 * the single-use refresh token. The returned `respond` wraps Remix's json() and
 * forwards any rotated session cookies on EVERY response, so no return path can
 * silently drop (and thereby burn) that token — the same failure that stranded
 * users on the login page. Use `respond` for all returns instead of json().
 * Throws a 401 (carrying the cookies) when there is no authenticated user.
 */
export async function authedJsonRoute(request: Request) {
    // NOT `await import('react-router')` — React Router 7 removed `json`, and
    // a dynamic destructure can survive static checks and fail every caller at
    // runtime.
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    const {
        data: { user },
    } = await supabase.auth.getUser();

    const respond = <T>(data: T, init?: ResponseInit) => {
        const merged = new Headers(init?.headers);
        for (const cookie of headers.getSetCookie())
            merged.append('Set-Cookie', cookie);
        return json(data, { ...init, headers: merged });
    };

    if (!user) throw respond({ error: 'Unauthorized' }, { status: 401 });
    return { user, supabase, respond };
}

/**
 * Creates a Supabase client with service role key (bypasses RLS)
 * ONLY use for server-side operations where you've already validated the user
 */
export function createServiceRoleClient() {
    return createClient(
        process.env.SUPABASE_URL!,
        process.env.SUPABASE_SECRET_KEY!,
        {
            auth: {
                autoRefreshToken: false,
                persistSession: false,
            },
        }
    );
}

/**
 * Signs out the current user
 * Returns headers that need to be included in the redirect
 */
export async function signOut(request: Request) {
    const headers = new Headers();
    const supabase = createServerSupabaseClient(request, headers);
    await supabase.auth.signOut({ scope: 'local' });
    return headers;
}
