// Hook for managing QuickBooks (Intuit) OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Intuit uses OAuth 2.0 (authorization_code) and returns a realmId (company ID)
// on the callback that scopes every API call — it is persisted with the tokens.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';
import { openOAuthPostPopup } from '~/lib/oauthPopup';

interface QuickBooksOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    name?: string;
    email?: string;
    realmId?: string;
    error?: string;
}

interface UseQuickBooksOAuthOptions {
    onSuccess?: (result: QuickBooksOAuthResult) => void;
    onError?: (error: string) => void;
}

interface QuickBooksOAuthCallbackData {
    type: 'quickbooks-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    realmId?: string;
    isSandbox?: boolean;
    scopes?: string[];
    customClientId?: string;
    customClientSecret?: string;
    error?: string;
}

const QUICKBOOKS_DEFAULT_SCOPES = [
    'com.intuit.quickbooks.accounting',
    'openid',
    'profile',
    'email',
];

export function useQuickBooksOAuth(options: UseQuickBooksOAuthOptions = {}) {
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => {
        oauthExchangeRef.current = oauthExchange;
    }, [oauthExchange]);

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
            const data = event.data as QuickBooksOAuthCallbackData;
            if (data?.type !== 'quickbooks-oauth-callback') return;

            // Only process if THIS instance initiated the connect (prevents race between multiple instances)
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useQuickBooksOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log(
                    '[useQuickBooksOAuth] Exchanging code for tokens...'
                );
                const response = await oauthExchangeRef.current({
                    event_name: 'quickbooks:oauth:exchange',
                    request_id: `quickbooks-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    realm_id: data.realmId,
                    is_sandbox: data.isSandbox ?? false,
                    scopes: data.scopes || QUICKBOOKS_DEFAULT_SCOPES,
                    client_id: data.customClientId,
                    client_secret: data.customClientSecret,
                });

                console.log(
                    '[useQuickBooksOAuth] Exchange response:',
                    response
                );

                if (response?.success) {
                    const result: QuickBooksOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        name: response.name ?? undefined,
                        email: response.email ?? undefined,
                        realmId: response.realm_id ?? undefined,
                    };
                    setError(null);
                    optionsRef.current.onSuccess?.(result);
                } else {
                    throw new Error(
                        response?.error ||
                            response?.message ||
                            'Failed to exchange authorization code'
                    );
                }
            } catch (err) {
                const errorMsg =
                    err instanceof Error
                        ? err.message
                        : 'OAuth exchange failed';
                console.error('[useQuickBooksOAuth] Exchange error:', errorMsg);
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
    // but QuickBooks derives the credential name from the connected Intuit profile.
    const connect = useCallback(
        (
            _credentialName: string,
            scopes: string[],
            customClientId?: string,
            customClientSecret?: string
        ) => {
            setIsConnecting(true);
            isConnectingRef.current = true;
            setError(null);

            const popup = openOAuthPostPopup({
                action: '/api/auth/intuit/authorize',
                name: 'quickbooks-oauth',
                fields: {
                    scopes: (scopes && scopes.length
                        ? scopes
                        : QUICKBOOKS_DEFAULT_SCOPES
                    ).join(','),
                    customClientId,
                    customClientSecret,
                },
            });

            // Handle case where popup was blocked
            if (!popup) {
                setIsConnecting(false);
                setError(
                    'Popup was blocked. Please allow popups for this site.'
                );
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
        },
        []
    );

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
