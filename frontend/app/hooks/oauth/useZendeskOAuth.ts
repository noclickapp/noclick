// Hook for managing Zendesk OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Zendesk OAuth is subdomain-scoped, so the connect() call carries the subdomain
// (host = {subdomain}.zendesk.com) in the shop-name positional slot.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface ZendeskOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    name?: string;
    email?: string;
    error?: string;
}

interface UseZendeskOAuthOptions {
    onSuccess?: (result: ZendeskOAuthResult) => void;
    onError?: (error: string) => void;
}

interface ZendeskOAuthCallbackData {
    type: 'zendesk-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    subdomain?: string;
    scopes?: string[];
    error?: string;
}

const ZENDESK_DEFAULT_SCOPES = ['read', 'write'];

export function useZendeskOAuth(options: UseZendeskOAuthOptions = {}) {
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => { oauthExchangeRef.current = oauthExchange; }, [oauthExchange]);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);

    // Keep options ref updated
    useEffect(() => {
        optionsRef.current = options;
    }, [options]);

    // Listen for postMessage from OAuth callback
    useEffect(() => {
        const handleMessage = async (event: MessageEvent) => {
            // Security: Only accept messages from our origin
            if (event.origin !== window.location.origin) return;

            // Check if this is our OAuth callback
            const data = event.data as ZendeskOAuthCallbackData;
            if (data?.type !== 'zendesk-oauth-callback') return;

            // Only process if THIS instance initiated the connect (prevents race between multiple instances)
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useZendeskOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log('[useZendeskOAuth] Exchanging code for tokens...');
                const response = await oauthExchangeRef.current({
                    event_name: 'zendesk:oauth:exchange',
                    request_id: `zendesk-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    subdomain: data.subdomain,
                    scopes: data.scopes || ZENDESK_DEFAULT_SCOPES,
                });

                console.log('[useZendeskOAuth] Exchange response:', response);

                if (response?.success) {
                    const result: ZendeskOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        name: response.name ?? undefined,
                        email: response.email ?? undefined,
                    };
                    setError(null);
                    optionsRef.current.onSuccess?.(result);
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useZendeskOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    // Note: credentialName is accepted for API consistency with other OAuth hooks,
    // but Zendesk derives the credential name from the user's Zendesk profile.
    // subdomain is required — it scopes the OAuth host and the API base URL.
    const connect = useCallback((_credentialName: string, subdomain: string, scopes: string[]) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams({
            subdomain,
            scopes: (scopes && scopes.length ? scopes : ZENDESK_DEFAULT_SCOPES).join(','),
        });

        // Calculate popup position (centered on screen)
        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        // Open OAuth flow in new popup window
        const popup = window.open(
            `/api/auth/zendesk/authorize?${params.toString()}`,
            'zendesk-oauth',
            `width=${width},height=${height},left=${left},top=${top},popup=yes`
        );

        // Handle case where popup was blocked
        if (!popup) {
            setIsConnecting(false);
            setError('Popup was blocked. Please allow popups for this site.');
            optionsRef.current.onError?.('Popup was blocked');
            return;
        }

        // Monitor if popup is closed without completing OAuth
        const checkClosed = setInterval(() => {
            try {
                if (popup.closed) {
                    clearInterval(checkClosed);
                    // Give a small delay for postMessage to process
                    setTimeout(() => {
                        if (isConnectingRef.current) {
                            setIsConnecting(false);
                            isConnectingRef.current = false;
                            // Don't set error - user may have intentionally closed
                        }
                    }, 500);
                }
            } catch {
                // COOP policy blocked access - clear interval and rely on postMessage
                clearInterval(checkClosed);
            }
        }, 500);
    }, []);

    const clearError = useCallback(() => {
        setError(null);
    }, []);

    return {
        connect,
        isConnecting,
        error,
        clearError,
    };
}
