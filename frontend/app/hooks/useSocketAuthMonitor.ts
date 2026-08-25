// Monitor socket connection for auth failures and act on the backend's
// machine error codes (never message-text matching — docs/auth-refactor-spec.md):
//   token_expired  → refresh the Supabase session once, reconnect; redirect
//                    only if that fails or it recurs
//   token_invalid  → definitive, redirect to /auth/login immediately
//   missing_auth / auth_failed → transient (cold start, blips); redirect only
//                    after the disconnect threshold

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useSocketConnection } from './useSocketConnection';
import { socketReceiver } from '~/lib/socket-receiver';
import { getExistingBrowserClient } from '~/lib/supabase-client';

interface AuthMonitorConfig {
    enabled?: boolean;
    // How long to wait after a transient auth failure before redirecting (ms)
    disconnectThresholdMs?: number;
}

const AUTH_ERROR_CODES = new Set([
    'token_expired',
    'token_invalid',
    'auth_failed',
    'missing_auth',
]);

export function useSocketAuthMonitor({
    enabled = true,
    disconnectThresholdMs = 10000, // 10 seconds
}: AuthMonitorConfig = {}) {
    const navigate = useNavigate();
    const { status, lastError, lastErrorCode } = useSocketConnection();
    const redirectTimerRef = useRef<NodeJS.Timeout | null>(null);
    const hasRedirectedRef = useRef(false);
    const authFailureStartRef = useRef<number | null>(null);
    // One recovery attempt per failure episode — a second token_expired after
    // a successful refresh means the session is genuinely unrecoverable.
    const refreshAttemptedRef = useRef(false);

    useEffect(() => {
        // Skip auth monitoring in performance test mode
        const isTestMode =
            typeof window !== 'undefined' &&
            (window as unknown as { __PERF_TEST_MODE__?: boolean }).__PERF_TEST_MODE__;
        if (!enabled || hasRedirectedRef.current || isTestMode) return;

        const isAuthError = !!lastErrorCode && AUTH_ERROR_CODES.has(lastErrorCode);

        if (status === 'connected' || !isAuthError) {
            if (redirectTimerRef.current) {
                clearTimeout(redirectTimerRef.current);
                redirectTimerRef.current = null;
            }
            authFailureStartRef.current = null;
            return;
        }

        if (authFailureStartRef.current === null) {
            authFailureStartRef.current = Date.now();
            console.log('🔴 Auth-related socket error:', { status, lastErrorCode, lastError });
        }

        // Recoverable: refresh the session once, then let the reconnect's auth
        // callback pick up the new token. No user-visible logout for a token
        // that merely expired while the tab was asleep.
        if (lastErrorCode === 'token_expired' && !refreshAttemptedRef.current) {
            refreshAttemptedRef.current = true;
            void (async () => {
                try {
                    const client = getExistingBrowserClient();
                    const { error } = client
                        ? await client.auth.refreshSession()
                        : { error: new Error('no client') };
                    if (!error) {
                        console.log('🔄 Session refreshed after token_expired — reconnecting');
                        socketReceiver.updateAllAuth();
                        return;
                    }
                    console.warn('token_expired refresh failed:', error);
                } catch (err) {
                    console.warn('token_expired refresh threw:', err);
                }
                hasRedirectedRef.current = true;
                navigate('/auth/login', { replace: true });
            })();
            return;
        }

        // Definitive: a bad token won't get better by retrying, and a second
        // token_expired after a refresh attempt means refresh isn't working.
        if (lastErrorCode === 'token_invalid' || (lastErrorCode === 'token_expired' && refreshAttemptedRef.current)) {
            console.log('🚪 Redirecting to /auth/login: definitive auth failure', lastErrorCode);
            hasRedirectedRef.current = true;
            navigate('/auth/login', { replace: true });
            return;
        }

        // Transient (missing_auth cold start, auth_failed catch-all): allow
        // recovery, redirect only after the threshold.
        const failureDuration = Date.now() - authFailureStartRef.current;
        const timeUntilRedirect = Math.max(0, disconnectThresholdMs - failureDuration);

        redirectTimerRef.current = setTimeout(() => {
            console.log('🚪 Redirecting to /auth/login: persistent auth failure', lastErrorCode);
            hasRedirectedRef.current = true;
            navigate('/auth/login', { replace: true });
        }, timeUntilRedirect);

        return () => {
            if (redirectTimerRef.current) {
                clearTimeout(redirectTimerRef.current);
                redirectTimerRef.current = null;
            }
        };
    }, [enabled, status, lastError, lastErrorCode, disconnectThresholdMs, navigate]);

    // Reset per-episode state when the connection is restored
    useEffect(() => {
        if (status === 'connected') {
            hasRedirectedRef.current = false;
            refreshAttemptedRef.current = false;
        }
    }, [status]);
}
