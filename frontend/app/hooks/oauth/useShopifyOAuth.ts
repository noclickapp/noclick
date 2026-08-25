// Hook for managing Shopify OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Shopify requires shop parameter in OAuth flow.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';
import { openOAuthPostPopup } from '~/lib/oauthPopup';

interface ShopifyOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    shop_name?: string;
    email?: string;
    error?: string;
}

interface UseShopifyOAuthOptions {
    onSuccess?: (result: ShopifyOAuthResult) => void;
    onError?: (error: string) => void;
}

interface ShopifyOAuthCallbackData {
    type: 'shopify-oauth-callback';
    success: boolean;
    code?: string;
    shop?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string;
    customClientId?: string;
    customClientSecret?: string;
    error?: string;
}

export function useShopifyOAuth(options: UseShopifyOAuthOptions = {}) {
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

    // Keep options ref updated
    useEffect(() => {
        optionsRef.current = options;
    }, [options]);

    // Shared callback handler — called by both window.message and BroadcastChannel listeners.
    // BroadcastChannel messages lack event.origin so we skip that check there; same-origin
    // is guaranteed by the BroadcastChannel name being the same in both files.
    const handleCallbackRef = useRef(async (data: ShopifyOAuthCallbackData) => {
        if (data?.type !== 'shopify-oauth-callback') return;
        if (!isConnectingRef.current) return;
        isConnectingRef.current = false;

        console.log('[useShopifyOAuth] Received callback:', data);

        if (!data.success) {
            const errorMsg = data.error || 'OAuth failed';
            setError(errorMsg);
            setIsConnecting(false);
            optionsRef.current.onError?.(errorMsg);
            return;
        }

        try {
            console.log('[useShopifyOAuth] Exchanging code for tokens...');
            const response = await oauthExchangeRef.current({
                event_name: 'shopify:oauth:exchange',
                request_id: `shopify-oauth-${Date.now()}`,
                code: data.code,
                shop: data.shop,
                redirect_uri: data.redirectUri,
                credential_name: data.credentialName || 'Shopify',
                scopes: data.scopes || '',
                custom_client_id: data.customClientId,
                custom_client_secret: data.customClientSecret,
            });

            console.log('[useShopifyOAuth] Exchange response:', response);

            if (response?.success) {
                const result: ShopifyOAuthResult = {
                    success: true,
                    credentialId: response.credential_id ?? undefined,
                    credentialName: response.credential_name ?? undefined,
                    shop_name: response.shop_name ?? undefined,
                    email: response.email ?? undefined,
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
                err instanceof Error ? err.message : 'OAuth exchange failed';
            console.error('[useShopifyOAuth] Exchange error:', errorMsg);
            setError(errorMsg);
            optionsRef.current.onError?.(errorMsg);
        } finally {
            setIsConnecting(false);
        }
    });

    // Listen via window.message (works when opener is not nullified)
    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.origin !== window.location.origin) return;
            handleCallbackRef.current(event.data as ShopifyOAuthCallbackData);
        };
        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    // Listen via BroadcastChannel — works when Shopify's COOP header nullifies window.opener
    useEffect(() => {
        const channel = new BroadcastChannel('shopify-oauth');
        channel.onmessage = (event) => {
            handleCallbackRef.current(event.data as ShopifyOAuthCallbackData);
        };
        return () => channel.close();
    }, []);

    const connect = useCallback(
        (
            credentialName: string,
            shop: string,
            scopes: string[],
            customClientId?: string,
            customClientSecret?: string
        ) => {
            setIsConnecting(true);
            isConnectingRef.current = true;
            setError(null);

            const popup = openOAuthPostPopup({
                action: '/api/auth/shopify/authorize',
                name: 'shopify-oauth',
                fields: {
                    name: credentialName,
                    shop,
                    scopes: scopes.join(','),
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
