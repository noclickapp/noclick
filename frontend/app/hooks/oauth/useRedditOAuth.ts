// Hook for managing Reddit OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Reddit uses standard OAuth 2.0 flow with refresh tokens.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface RedditOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    username?: string;
    error?: string;
}

interface UseRedditOAuthOptions {
    onSuccess?: (result: RedditOAuthResult) => void;
    onError?: (error: string) => void;
}

interface RedditOAuthCallbackData {
    type: 'reddit-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    error?: string;
}

export function useRedditOAuth(options: UseRedditOAuthOptions = {}) {
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
            const data = event.data as RedditOAuthCallbackData;
            if (data?.type !== 'reddit-oauth-callback') return;

            // Only process if THIS instance initiated the connect (prevents race between multiple instances)
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useRedditOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log('[useRedditOAuth] Exchanging code for tokens...');
                const response = await oauthExchangeRef.current({
                    event_name: 'reddit:oauth:exchange',
                    request_id: `reddit-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    credential_name: data.credentialName || 'Reddit',
                    scopes: data.scopes || ['identity', 'read', 'submit', 'vote', 'edit', 'history', 'privatemessages', 'mysubreddits', 'save', 'subscribe'],
                });

                console.log('[useRedditOAuth] Exchange response:', response);

                if (response?.success) {
                    const result: RedditOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        username: response.username ?? undefined,
                    };
                    setError(null);
                    optionsRef.current.onSuccess?.(result);
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useRedditOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    const connect = useCallback((credentialName: string, scopes: string[]) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams({
            name: credentialName,
            scopes: scopes.join(','),
        });

        // Calculate popup position (centered on screen)
        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        // Open OAuth flow in new popup window
        const popup = window.open(
            `/api/auth/reddit.authorize?${params.toString()}`,
            'reddit-oauth',
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
