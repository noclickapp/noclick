// Hook for managing BambooHR OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// BambooHR OAuth is subdomain-scoped (host = {subdomain}.bamboohr.com), so the
// connect() call carries the subdomain in the shop-name positional slot — the
// same shape Zendesk uses. BambooHR OAuth is limited to approved Marketplace
// apps; the API-key credential is the primary, unrestricted path.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface BambooHROAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    name?: string;
    email?: string;
    error?: string;
}

interface UseBambooHROAuthOptions {
    onSuccess?: (result: BambooHROAuthResult) => void;
    onError?: (error: string) => void;
}

interface BambooHROAuthCallbackData {
    type: 'bamboohr-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    subdomain?: string;
    scopes?: string[];
    error?: string;
}

const BAMBOOHR_DEFAULT_SCOPES = ['openid', 'offline_access'];

export function useBambooHROAuth(options: UseBambooHROAuthOptions = {}) {
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => {
        oauthExchangeRef.current = oauthExchange;
    }, [oauthExchange]);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);

    useEffect(() => {
        optionsRef.current = options;
    }, [options]);

    useEffect(() => {
        const handleMessage = async (event: MessageEvent) => {
            if (event.origin !== window.location.origin) return;

            const data = event.data as BambooHROAuthCallbackData;
            if (data?.type !== 'bamboohr-oauth-callback') return;

            // Only the instance that initiated this connect handles the callback.
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            try {
                const response = await oauthExchangeRef.current({
                    event_name: 'bamboohr:oauth:exchange',
                    request_id: `bamboohr-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    subdomain: data.subdomain,
                    scopes: data.scopes || BAMBOOHR_DEFAULT_SCOPES,
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
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    // subdomain is required — it scopes the OAuth host and the API base URL.
    const connect = useCallback((_credentialName: string, subdomain: string, scopes: string[]) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams({
            subdomain,
            scopes: (scopes && scopes.length ? scopes : BAMBOOHR_DEFAULT_SCOPES).join(','),
        });

        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        const popup = window.open(
            `/api/auth/bamboohr/authorize?${params.toString()}`,
            'bamboohr-oauth',
            `width=${width},height=${height},left=${left},top=${top},popup=yes`
        );

        if (!popup) {
            setIsConnecting(false);
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
