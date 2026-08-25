// Hook for managing Slack OAuth flow in NodeCredentials.
// Handles popup window, BroadcastChannel communication, and token exchange via backend.
// Slack uses OAuth 2.0 "Add to Slack" flow.
// Uses BroadcastChannel instead of window.opener.postMessage because window.opener
// becomes null after the popup navigates through slack.com (COOP: same-origin).

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';
import { openOAuthPostPopup } from '~/lib/oauthPopup';

interface SlackOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    teamId?: string;
    teamName?: string;
    error?: string;
}

interface UseSlackOAuthOptions {
    onSuccess?: (result: SlackOAuthResult) => void;
    onError?: (error: string) => void;
}

interface SlackOAuthCallbackData {
    type: 'slack-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    customClientId?: string;
    customClientSecret?: string;
    error?: string;
}

export function useSlackOAuth(options: UseSlackOAuthOptions = {}) {
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

    // Listen for BroadcastChannel from OAuth callback popup.
    // BroadcastChannel is same-origin by design so no origin check is needed.
    useEffect(() => {
        const channel = new BroadcastChannel('slack-oauth');
        console.log('[useSlackOAuth] BroadcastChannel listener active');

        channel.onmessage = async (event: MessageEvent) => {
            const data = event.data as SlackOAuthCallbackData;
            if (data?.type !== 'slack-oauth-callback') return;

            // Only process if THIS instance initiated the connect
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useSlackOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log('[useSlackOAuth] Exchanging code for tokens...');
                const exchangeRequest: Record<string, unknown> = {
                    event_name: 'slack:oauth:exchange',
                    request_id: `slack-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    credential_name: data.credentialName || 'Slack',
                    scopes: data.scopes || [
                        'channels:read',
                        'chat:write',
                        'users:read',
                    ],
                };
                if (data.customClientId && data.customClientSecret) {
                    exchangeRequest.client_id = data.customClientId;
                    exchangeRequest.client_secret = data.customClientSecret;
                }
                const response =
                    await oauthExchangeRef.current(exchangeRequest);

                console.log('[useSlackOAuth] Exchange response:', response);

                if (response?.success) {
                    const result: SlackOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        teamId: response.team_id ?? undefined,
                        teamName: response.team_name ?? undefined,
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
                console.error('[useSlackOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        };

        return () => channel.close();
    }, []);

    const connect = useCallback(
        (
            credentialName: string,
            scopes: string[],
            customClientId?: string,
            customClientSecret?: string,
            userScopes?: string[]
        ) => {
            setIsConnecting(true);
            isConnectingRef.current = true;
            setError(null);

            const popup = openOAuthPostPopup({
                action: '/api/auth/slack/authorize',
                name: 'slack-oauth',
                fields: {
                    name: credentialName,
                    scopes: scopes.join(','),
                    user_scopes: userScopes?.join(','),
                    client_id: customClientId,
                    client_secret: customClientSecret,
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
                        // Give a small delay for BroadcastChannel message to process
                        setTimeout(() => {
                            if (isConnectingRef.current) {
                                setIsConnecting(false);
                                isConnectingRef.current = false;
                                // Don't set error - user may have intentionally closed
                            }
                        }, 500);
                    }
                } catch {
                    // COOP policy blocked popup.closed access; BroadcastChannel handles the
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

// Default scopes for Slack workflow automation
export const SLACK_DEFAULT_SCOPES = [
    'channels:read',
    'channels:history',
    'chat:write',
    'chat:write.public',
    'users:read',
    'reactions:read',
    'reactions:write',
    'files:read',
];

// Full scopes for complete Slack integration
export const SLACK_FULL_SCOPES = [
    'channels:read',
    'channels:write',
    'channels:history',
    'chat:write',
    'chat:write.public',
    'users:read',
    'users:read.email',
    'reactions:read',
    'reactions:write',
    'pins:read',
    'pins:write',
    'files:read',
    'files:write',
    'search:read',
    'bookmarks:read',
    'bookmarks:write',
    'usergroups:read',
    'usergroups:write',
    'dnd:read',
    'dnd:write',
    'emoji:read',
    'stars:read',
    'stars:write',
    'reminders:read',
    'reminders:write',
    'team:read',
    'groups:read',
    'groups:write',
    'im:read',
    'im:write',
    'mpim:read',
    'mpim:write',
];
