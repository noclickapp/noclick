// Keeps the backend socket authenticated as the Supabase session evolves:
// on TOKEN_REFRESHED / SIGNED_IN / INITIAL_SESSION it pushes the fresh access
// token over `update_auth` (the handshake auth callback in socket/config.ts
// covers reconnects), and on tab-foreground it proactively refreshes a
// near-expiry token (Supabase auto-refresh is foreground-only).
//
// Deliberately owns NO cookie handling: @supabase/ssr's storage adapter
// (supabase-client.ts) is the only code that touches sb-* cookies. The old
// hand-rolled cookie janitor here deleted the live refresh token whenever the
// access token had expired — the diagnosed mid-session logout bug
// (docs/auth-refactor-spec.md).

import { useEffect, useRef } from 'react';
import { useLoaderData } from 'react-router';
import { createBrowserSupabaseClient } from '~/lib/supabase';
import { socketReceiver } from '~/lib/socket-receiver';

interface TokenRefreshConfig {
    enabled?: boolean;
}

/**
 * Pushes the current access token to the backend socket session and wakes
 * idle sockets. Deferred via setTimeout at call sites — Supabase docs warn
 * against async work inside onAuthStateChange callbacks.
 */
function syncAuthWithBackend(logPrefix: string) {
    socketReceiver.updateAllAuth();

    socketReceiver.sendAuthUpdate().then((result) => {
        if (result.success) {
            console.log(`✅ ${logPrefix}: Backend session synced`);
        } else {
            console.warn(`⚠️ ${logPrefix}: Failed to sync backend session:`, result.error);
        }
    }).catch((err) => {
        console.warn(`⚠️ ${logPrefix}: Error syncing backend session:`, err);
    });
}

export function useSocketTokenRefresh({ enabled = true }: TokenRefreshConfig = {}) {
    const { env } = useLoaderData<{ env: { SUPABASE_URL: string; SUPABASE_ANON_KEY: string } }>();

    // Track if we've already set up the listener (prevents double setup in React strict mode)
    const listenerSetupRef = useRef(false);

    useEffect(() => {
        if (!enabled || !env) return;

        // Prevent double setup in React strict mode
        if (listenerSetupRef.current) {
            console.log('🔐 Auth listener already set up, skipping duplicate');
            return;
        }

        let subscription: { unsubscribe: () => void } | null = null;
        let visibilityHandler: (() => void) | null = null;

        const setupAuthListener = (supabase: ReturnType<typeof createBrowserSupabaseClient>) => {
            const { data } = supabase.auth.onAuthStateChange((event, session) => {
                console.log(`🔐 Auth state change: ${event}`);

                if (event === 'TOKEN_REFRESHED' && session?.expires_at) {
                    console.log(
                        '🔄 Token refreshed. New expiration:',
                        new Date(session.expires_at * 1000).toLocaleString()
                    );
                    setTimeout(() => syncAuthWithBackend('Token refresh'), 0);
                }

                if ((event === 'INITIAL_SESSION' || event === 'SIGNED_IN') && session) {
                    setTimeout(() => syncAuthWithBackend('Initial session'), 0);
                }

                // Client-side session death (failed refresh, revoked token).
                // Surface it as an explicit re-login instead of the old silent
                // socket-auth wipe, which left the user on a dead page whose
                // socket was being kicked with no visible explanation.
                if (event === 'SIGNED_OUT') {
                    console.log('🚪 Session ended — redirecting to login');
                    window.location.href = '/auth/login';
                }
            });

            subscription = data.subscription;
            listenerSetupRef.current = true;

            // Compensate for Supabase's documented foreground-only auto-refresh:
            // while the tab is hidden the access token can silently expire; on
            // return, refresh proactively so the first socket reconnect carries
            // a live token. Mirrors requireAuth's 60s threshold.
            visibilityHandler = () => {
                if (document.visibilityState !== 'visible') return;
                void (async () => {
                    try {
                        const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
                        if (sessionError || !sessionData.session) return;
                        const expiresAt = sessionData.session.expires_at ?? 0;
                        const now = Math.floor(Date.now() / 1000);
                        if (expiresAt - now < 60) {
                            console.log('🔄 Tab returned to foreground with near-expiry token, forcing refresh');
                            await supabase.auth.refreshSession();
                        }
                    } catch (err) {
                        console.warn('[useSocketTokenRefresh] visibility refresh failed', err);
                    }
                })();
            };
            document.addEventListener('visibilitychange', visibilityHandler);
        };

        // Implicit-flow tokens in the URL hash (IdP-initiated SSO — Okta
        // redirects straight to /dashboard#access_token=...). Must be consumed
        // before normal initialization.
        const hash = window.location.hash;
        if (hash && hash.includes('access_token=')) {
            console.log('🔐 Detected implicit flow tokens in URL, processing...');

            const params = new URLSearchParams(hash.substring(1));
            const accessToken = params.get('access_token');
            const refreshToken = params.get('refresh_token');

            if (accessToken && refreshToken) {
                // Clear the hash from URL immediately for security
                window.history.replaceState(null, '', window.location.pathname + window.location.search);

                const supabase = createBrowserSupabaseClient(env);
                supabase.auth.setSession({
                    access_token: accessToken,
                    refresh_token: refreshToken,
                }).then(({ error }) => {
                    if (error) {
                        console.error('❌ Failed to set session from URL tokens:', error);
                        window.location.href = '/auth/login';
                    } else {
                        console.log('✅ Session established from URL tokens');
                        setupAuthListener(supabase);
                    }
                });
                return () => {
                    if (subscription) {
                        subscription.unsubscribe();
                        listenerSetupRef.current = false;
                    }
                    if (visibilityHandler) {
                        document.removeEventListener('visibilitychange', visibilityHandler);
                        visibilityHandler = null;
                    }
                };
            }
        }

        // Normal path: the singleton client owns session storage; no cookie
        // pre-validation dance — @supabase/ssr reads its own cookies.
        setupAuthListener(createBrowserSupabaseClient(env));

        return () => {
            if (subscription) {
                subscription.unsubscribe();
                listenerSetupRef.current = false;
            }
            if (visibilityHandler) {
                document.removeEventListener('visibilitychange', visibilityHandler);
                visibilityHandler = null;
            }
        };
    }, [enabled, env]);
}
