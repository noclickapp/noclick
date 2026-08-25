// Hook for managing Google OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Works with any Google API (Sheets, Gmail, Drive, etc.) - just pass different scopes.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';
import { augmentScopes } from '~/utils/oauthProviders';

interface GoogleOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    credentialType?: string;
    email?: string;
    error?: string;
}

interface UseGoogleOAuthOptions {
    onSuccess?: (result: GoogleOAuthResult) => void;
    onError?: (error: string) => void;
}

interface GoogleOAuthCallbackData {
    type: 'google-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    error?: string;
}

export function useGoogleOAuth(options: UseGoogleOAuthOptions = {}) {
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => { oauthExchangeRef.current = oauthExchange; }, [oauthExchange]);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    // Ref to track if THIS specific hook instance initiated the OAuth flow.
    // Prevents race conditions when multiple components mount this hook simultaneously
    // (e.g., guided assist view with multiple credential selectors).
    const isConnectingRef = useRef(false);
    // Stash custom client credentials for use in the postMessage callback handler
    const customClientRef = useRef<{ client_id: string; client_secret: string } | undefined>(undefined);

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
            const data = event.data as GoogleOAuthCallbackData;
            if (data?.type !== 'google-oauth-callback') return;

            // Only process if THIS instance initiated the connect (prevents race between multiple instances)
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useGoogleOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log('[useGoogleOAuth] Exchanging code for tokens...');
                const customClient = customClientRef.current;
                const response = await oauthExchangeRef.current({
                    event_name: 'google:oauth:exchange',
                    request_id: `google-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    credential_name: data.credentialName || 'Google Sheets',
                    scopes: data.scopes || ['https://www.googleapis.com/auth/spreadsheets'],
                    ...(customClient ? {
                        custom_client_id: customClient.client_id,
                        custom_client_secret: customClient.client_secret,
                    } : {}),
                });

                console.log('[useGoogleOAuth] Exchange response:', response);

                if (response?.success) {
                    const result: GoogleOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        credentialType: response.credential_type ?? undefined,
                        email: response.email ?? undefined,
                    };
                    setError(null);
                    optionsRef.current.onSuccess?.(result);
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useGoogleOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    const connect = useCallback((
        credentialName: string,
        scopes: string[],
        customClient?: { client_id: string; client_secret: string },
    ) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        customClientRef.current = customClient;
        setError(null);

        // Identity scopes (email/profile) come from the provider config so the
        // credential-request link applies the exact same set — see augmentScopes.
        const allScopes = augmentScopes('google', scopes);

        const params = new URLSearchParams({
            name: credentialName,
            scopes: allScopes.join(','),
            ...(customClient ? { custom_client_id: customClient.client_id } : {}),
        });

        // Calculate popup position (centered on screen)
        const width = 500;
        const height = 600;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        // Open OAuth flow in new popup window (unified route for all Google APIs)
        const popup = window.open(
            `/api/auth/google/authorize?${params.toString()}`,
            'google-oauth',
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
        // Note: COOP policy may block popup.closed access, so we wrap in try-catch
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
