// Hook for managing Facebook OAuth flow for Instagram integration.
// Handles popup window, BroadcastChannel communication, and token exchange via backend.
// Instagram Graph API requires Facebook Login (connects via Facebook Pages).
// Uses BroadcastChannel instead of window.opener.postMessage because window.opener
// becomes null after the popup navigates through facebook.com (cross-origin).
// Supports multi-account selection: when multiple Instagram accounts are linked to
// the user's Facebook profile, onNeedsSelection is called with the account list.
// Call selectAccount(instagram_user_id) to complete credential creation.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface FacebookOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    instagramUsername?: string;
    email?: string;
    error?: string;
}

interface InstagramAccount {
    instagram_user_id: string;
    instagram_username?: string;
    facebook_page_id?: string;
    facebook_page_name?: string;
}

interface UseFacebookOAuthOptions {
    onSuccess?: (result: FacebookOAuthResult) => void;
    onError?: (error: string) => void;
    onNeedsSelection?: (accounts: InstagramAccount[]) => void;
}

interface FacebookOAuthCallbackData {
    type: 'facebook-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    error?: string;
}

const REQUIRED_INSTAGRAM_SCOPES = [
    'instagram_basic',
    'instagram_content_publish',
    'instagram_manage_comments',
    'pages_show_list',
    'pages_read_engagement',
    'business_management',
];

export function useFacebookOAuth(options: UseFacebookOAuthOptions = {}) {
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => { oauthExchangeRef.current = oauthExchange; }, [oauthExchange]);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [pendingAccounts, setPendingAccounts] = useState<InstagramAccount[] | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);

    // Preserved across the two-step multi-account selection flow
    const pendingStateRef = useRef<{
        pendingSelectionKey: string;
        code: string;
        redirectUri: string;
        credentialName: string;
        scopes: string[];
    } | null>(null);

    // Keep options ref updated
    useEffect(() => {
        optionsRef.current = options;
    }, [options]);

    const _completeExchange = useCallback(async (payload: {
        code: string;
        redirectUri: string;
        credentialName: string;
        scopes: string[];
        selectedInstagramUserId?: string;
        pendingSelectionKey?: string;
    }) => {
        const response = await oauthExchangeRef.current({
            event_name: 'facebook:oauth:exchange',
            request_id: `facebook-oauth-${Date.now()}`,
            code: payload.code,
            redirect_uri: payload.redirectUri,
            credential_name: payload.credentialName,
            scopes: payload.scopes,
            ...(payload.selectedInstagramUserId && {
                selected_instagram_user_id: payload.selectedInstagramUserId,
            }),
            ...(payload.pendingSelectionKey && {
                pending_selection_key: payload.pendingSelectionKey,
            }),
        });

        console.log('[useFacebookOAuth] Exchange response:', response);

        if (response?.needs_selection) {
            // Multiple accounts — ask the user to pick one
            const accounts: InstagramAccount[] = response.accounts || [];
            setPendingAccounts(accounts);
            pendingStateRef.current = {
                pendingSelectionKey: response.pending_selection_key,
                code: payload.code,
                redirectUri: payload.redirectUri,
                credentialName: payload.credentialName,
                scopes: payload.scopes,
            };
            setIsConnecting(false);
            optionsRef.current.onNeedsSelection?.(accounts);
            return;
        }

        if (response?.success) {
            setPendingAccounts(null);
            pendingStateRef.current = null;
            const result: FacebookOAuthResult = {
                success: true,
                credentialId: response.credential_id ?? undefined,
                credentialName: response.credential_name ?? undefined,
                instagramUsername: response.instagram_username ?? undefined,
                email: response.email ?? undefined,
            };
            setError(null);
            optionsRef.current.onSuccess?.(result);
        } else {
            throw new Error(response?.message || 'Failed to exchange authorization code');
        }
    }, []);

    // Listen for BroadcastChannel from OAuth callback popup.
    // BroadcastChannel is same-origin by design so no origin check is needed.
    // Requires FACEBOOK_OAUTH_REDIRECT_URI to use the same origin as the main
    // window (e.g. http://localhost:5174) so the popup and main window share origin.
    useEffect(() => {
        const channel = new BroadcastChannel('facebook-oauth');
        console.log('[useFacebookOAuth] BroadcastChannel listener active');

        channel.onmessage = async (event: MessageEvent) => {
            const data = event.data as FacebookOAuthCallbackData;
            console.log('[useFacebookOAuth] BroadcastChannel message received, isConnecting:', isConnectingRef.current, data);
            if (data?.type !== 'facebook-oauth-callback') return;

            // Only process if THIS instance initiated the connect
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useFacebookOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            try {
                console.log('[useFacebookOAuth] Exchanging code for tokens...');
                await _completeExchange({
                    code: data.code!,
                    redirectUri: data.redirectUri!,
                    credentialName: data.credentialName || 'Instagram',
                    scopes: data.scopes || REQUIRED_INSTAGRAM_SCOPES,
                });
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useFacebookOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        return () => channel.close();
    }, [_completeExchange]);

    /**
     * Complete multi-account selection. Call this after onNeedsSelection fires
     * with the instagram_user_id the user chose.
     */
    const selectAccount = useCallback(async (instagramUserId: string) => {
        const pending = pendingStateRef.current;
        if (!pending) {
            console.error('[useFacebookOAuth] selectAccount called without pending state');
            return;
        }
        setIsConnecting(true);
        setError(null);
        try {
            await _completeExchange({
                code: pending.code,
                redirectUri: pending.redirectUri,
                credentialName: pending.credentialName,
                scopes: pending.scopes,
                selectedInstagramUserId: instagramUserId,
                pendingSelectionKey: pending.pendingSelectionKey,
            });
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Account selection failed';
            console.error('[useFacebookOAuth] selectAccount error:', errorMsg);
            setError(errorMsg);
            optionsRef.current.onError?.(errorMsg);
        } finally {
            setIsConnecting(false);
        }
    }, [_completeExchange]);

    const connect = useCallback((credentialName: string, scopes: string[]) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);
        setPendingAccounts(null);
        pendingStateRef.current = null;

        // Always enforce minimum required scopes for Instagram account discovery.
        const mergedScopes = Array.from(new Set([...(scopes || []), ...REQUIRED_INSTAGRAM_SCOPES]));

        const params = new URLSearchParams({
            name: credentialName,
            scopes: mergedScopes.join(','),
        });

        const width = 600;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        const popup = window.open(
            `/api/auth/facebook/authorize?${params.toString()}`,
            'facebook-oauth',
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
                    // Give BroadcastChannel message 500ms to arrive before treating as cancelled
                    setTimeout(() => {
                        if (isConnectingRef.current) {
                            setIsConnecting(false);
                            isConnectingRef.current = false;
                        }
                    }, 500);
                }
            } catch {
                // COOP policy blocked access to popup.closed; BroadcastChannel handles the
                // success path. Use a 10s timeout as fallback for manual popup closure.
                clearInterval(checkClosed);
                setTimeout(() => {
                    if (isConnectingRef.current) {
                        setIsConnecting(false);
                        isConnectingRef.current = false;
                    }
                }, 10000);
            }
        }, 500);
    }, []);

    const clearError = useCallback(() => {
        setError(null);
    }, []);

    return {
        connect,
        selectAccount,
        isConnecting,
        error,
        clearError,
        pendingAccounts,
    };
}
