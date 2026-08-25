// Singleton Supabase browser client to prevent multiple instances and race conditions.
// Multiple client instances cause auth listener conflicts that lead to random logouts.
// This module ensures only ONE client exists for the entire app lifecycle.

import { createBrowserClient, serializeCookieHeader } from '@supabase/ssr';

// Use ReturnType to infer the correct type from createBrowserClient
type BrowserClient = ReturnType<typeof createBrowserClient>;

let browserClient: BrowserClient | null = null;
let clientEnv: { SUPABASE_URL: string; SUPABASE_ANON_KEY: string } | null =
    null;

/**
 * Per-worktree auth-cookie storage key for local development.
 *
 * Cookies on localhost are scoped by host only, NOT by port, so every git
 * worktree running on its own dev port (5173, 5174, …) shares one cookie jar.
 * With Supabase's single-use rotating refresh tokens that means logging into
 * one worktree overwrites the shared cookie and invalidates every other
 * worktree's session — "logging into one worktree logs the others out".
 * Suffixing the cookie name with the dev port gives each worktree an isolated
 * session. Server and browser derive the same host+port (the dev server the
 * browser is connected to), so the names always match.
 *
 * Gated on a **localhost host**, not merely on port presence: in production the
 * server's request.url host/port comes from forwarded headers and can't be
 * trusted (same reason auth.server.ts uses NODE_ENV, not request.url). Gating
 * on a localhost host guarantees prod returns undefined on BOTH server and
 * browser — the default Supabase cookie name, unchanged — so a deploy never
 * invalidates anyone's session and a spoofed Host can't touch the real cookie.
 */
export function devAuthCookieName(
    hostname: string | null | undefined,
    port: string | null | undefined
): string | undefined {
    const isLocalHost =
        hostname === 'localhost' ||
        hostname === '127.0.0.1' ||
        !!hostname?.endsWith('.localhost');
    if (!isLocalHost || !port) return undefined;
    return `sb-noclick-wt${port}-auth-token`;
}

/**
 * Gets or creates the singleton Supabase browser client.
 * IMPORTANT: Always use this instead of createBrowserSupabaseClient() to avoid
 * multiple client instances which cause auth state race conditions.
 */
export function getSupabaseBrowserClient(env: {
    SUPABASE_URL: string;
    SUPABASE_ANON_KEY: string;
}): BrowserClient {
    // If client exists and env matches, return existing client
    if (browserClient && clientEnv?.SUPABASE_URL === env.SUPABASE_URL) {
        return browserClient;
    }

    // Create new client (first time or env changed)
    clientEnv = env;
    browserClient = createBrowserClient(
        env.SUPABASE_URL,
        env.SUPABASE_ANON_KEY,
        {
            auth: {
                autoRefreshToken: true,
                persistSession: true,
                detectSessionInUrl: true,
                flowType: 'pkce', // Use PKCE flow for better SSR compatibility
            },
            // Namespace the auth cookie per worktree in local dev (see devAuthCookieName).
            cookieOptions: {
                name: devAuthCookieName(
                    typeof window !== 'undefined'
                        ? window.location.hostname
                        : undefined,
                    typeof window !== 'undefined'
                        ? window.location.port
                        : undefined
                ),
            },
            cookies: {
                get(key) {
                    const cookie = document.cookie
                        .split('; ')
                        .find((row) => row.startsWith(`${key}=`));
                    // Handle cookie values that contain '=' (e.g., base64-encoded tokens)
                    if (!cookie) return undefined;
                    const eqIndex = cookie.indexOf('=');
                    return eqIndex === -1
                        ? undefined
                        : cookie.slice(eqIndex + 1);
                },
                set(key, value, options) {
                    // Ensure Path=/ so cookies are available on all routes
                    // Set Secure and SameSite flags for security compliance
                    const isProduction = window.location.protocol === 'https:';
                    const cookieOptions = {
                        ...options,
                        path: '/',
                        secure: isProduction,
                        sameSite: 'lax' as const,
                    };
                    document.cookie = serializeCookieHeader(
                        key,
                        value,
                        cookieOptions
                    );
                },
                remove(key, options) {
                    // Ensure Path=/ matches the path used when setting
                    const isProduction = window.location.protocol === 'https:';
                    const cookieOptions = {
                        ...options,
                        path: '/',
                        secure: isProduction,
                        sameSite: 'lax' as const,
                        maxAge: 0,
                    };
                    document.cookie = serializeCookieHeader(
                        key,
                        '',
                        cookieOptions
                    );
                },
            },
        }
    );

    return browserClient;
}

/**
 * Checks if a browser client has been initialized.
 * Useful for conditional logic that depends on client availability.
 */
export function hasSupabaseBrowserClient(): boolean {
    return browserClient !== null;
}

/**
 * Returns the singleton browser client if it has been initialized, else null.
 *
 * Use this from non-React modules (e.g. socket auth callbacks) that need to
 * call supabase.auth.getSession() without having access to the env loader
 * data. The hook in useSocketTokenRefresh initializes the singleton on mount,
 * and any code reaching for it via this getter will either get the live
 * client or null (in which case it should fall back to the existing
 * document.cookie path).
 */
export function getExistingBrowserClient(): BrowserClient | null {
    return browserClient;
}

/**
 * Clears the singleton client (for testing or explicit cleanup).
 * Normally you should NOT call this in production.
 */
export function clearSupabaseBrowserClient(): void {
    browserClient = null;
    clientEnv = null;
}
