// Hook for the PostHog OAuth flow (public client + PKCE).
// Bespoke (not createOAuthHook) because the token exchange must carry the PKCE
// code_verifier that the callback threads back from `state`. The exchange routes
// through OAuthExchangeContext so it works in-app (socket) and on the provide page.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface PostHogOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    name?: string;
    email?: string;
    error?: string;
}

interface UsePostHogOAuthOptions {
    onSuccess?: (result: PostHogOAuthResult) => void;
    onError?: (error: string) => void;
}

interface PostHogOAuthCallbackData {
    type: 'posthog-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    codeVerifier?: string;
    scopes?: string[];
    error?: string;
}

export function usePostHogOAuth(options: UsePostHogOAuthOptions = {}) {
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => { oauthExchangeRef.current = oauthExchange; }, [oauthExchange]);
    useEffect(() => { optionsRef.current = options; }, [options]);

    useEffect(() => {
        const handleMessage = async (event: MessageEvent) => {
            if (event.origin !== window.location.origin) return;
            const data = event.data as PostHogOAuthCallbackData;
            if (data?.type !== 'posthog-oauth-callback') return;
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            if (!data.success) {
                const msg = data.error || 'OAuth failed';
                setError(msg);
                setIsConnecting(false);
                optionsRef.current.onError?.(msg);
                return;
            }

            try {
                const response = await oauthExchangeRef.current({
                    event_name: 'posthog:oauth:exchange',
                    request_id: `posthog-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    code_verifier: data.codeVerifier,
                    scopes: data.scopes || [],
                });
                if (response?.success) {
                    setError(null);
                    optionsRef.current.onSuccess?.({
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        name: response.name ?? undefined,
                        email: response.email ?? undefined,
                    });
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const msg = err instanceof Error ? err.message : 'OAuth exchange failed';
                setError(msg);
                optionsRef.current.onError?.(msg);
            } finally {
                setIsConnecting(false);
            }
        };
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    const connect = useCallback((_credentialName: string, scopes?: string[]) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams();
        if (scopes && scopes.length) params.set('scopes', scopes.join(' '));

        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        const popup = window.open(
            `/api/auth/posthog/authorize?${params.toString()}`,
            'posthog-oauth',
            `width=${width},height=${height},left=${left},top=${top},popup=yes`,
        );
        if (!popup) {
            setIsConnecting(false);
            isConnectingRef.current = false;
            setError('Popup was blocked. Please allow popups for this site.');
            optionsRef.current.onError?.('Popup was blocked');
            return;
        }
        const checkClosed = setInterval(() => {
            try {
                if (popup.closed) {
                    clearInterval(checkClosed);
                    setTimeout(() => {
                        if (isConnectingRef.current) {
                            setIsConnecting(false);
                            isConnectingRef.current = false;
                        }
                    }, 500);
                }
            } catch {
                clearInterval(checkClosed);
            }
        }, 500);
    }, []);

    const clearError = useCallback(() => setError(null), []);

    return { connect, isConnecting, error, clearError };
}
