// Hook for managing Atlassian OAuth flow in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// Atlassian uses standard OAuth 2.0 (3LO) flow with offline_access for refresh tokens.

import { useState, useEffect, useCallback, useRef } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

interface AtlassianOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    cloudId?: string;
    siteName?: string;
    siteUrl?: string;
    error?: string;
}

export interface AtlassianAvailableSite {
    id: string;
    name?: string;
    url: string;
}

export interface AtlassianSiteSuggestion {
    message: string;
    availableSites: AtlassianAvailableSite[];
    useSite: (siteUrl: string) => Promise<void>;
}

interface UseAtlassianOAuthOptions {
    onSuccess?: (result: AtlassianOAuthResult) => void;
    onError?: (error: string) => void;
    onSiteSuggestion?: (suggestion: AtlassianSiteSuggestion) => void;
}

interface AtlassianOAuthCallbackData {
    type: 'atlassian-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    jiraSite?: string;
    error?: string;
}

// Mirrors JiraOAuthCredential's x-oauth-scopes, derived from
// backend/nodes/scopes/jira.py. Keep in sync.
const DEFAULT_ATLASSIAN_SCOPES = [
    'read:jira-work',
    'write:jira-work',
    'read:jira-user',
    'manage:jira-project',
    'manage:jira-configuration',
    'manage:jira-webhook',
    'read:project:jira',
    'read:issue-details:jira',
    'read:jql:jira',
    'read:board-scope:jira-software',
    'read:sprint:jira-software',
    'write:sprint:jira-software',
    'delete:sprint:jira-software',
    'read:epic:jira-software',
    'write:epic:jira-software',
    'offline_access',
];

function isTrustedCallbackOrigin(origin: string): boolean {
    if (origin === window.location.origin) return true;

    let parsed: URL;
    try {
        parsed = new URL(origin);
    } catch {
        return false;
    }

    if (parsed.protocol !== 'https:' && parsed.hostname !== 'localhost') {
        return false;
    }

    return (
        parsed.hostname === 'noclick.com' ||
        parsed.hostname === 'www.noclick.com' ||
        parsed.hostname === 'localhost'
    );
}

export function useAtlassianOAuth(options: UseAtlassianOAuthOptions = {}) {
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

    const connect = useCallback((credentialName: string, scopes: string[], jiraSite: string) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams({
            name: credentialName,
            scopes: scopes.join(','),
            jiraSite,
        });

        // Calculate popup position (centered on screen)
        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        // Open OAuth flow in new popup window
        const popup = window.open(
            `/api/auth/atlassian/authorize?${params.toString()}`,
            'atlassian-oauth',
            `width=${width},height=${height},left=${left},top=${top},popup=yes`
        );

        // Handle case where popup was blocked
        if (!popup) {
            setIsConnecting(false);
            isConnectingRef.current = false;
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

    const exchangeCallback = useCallback(
        async (data: AtlassianOAuthCallbackData, jiraSite: string | undefined) => {
            setIsConnecting(true);
            const scopes = data.scopes || DEFAULT_ATLASSIAN_SCOPES;
            try {
                console.log('[useAtlassianOAuth] Exchanging code for tokens...');
                const response = await oauthExchangeRef.current({
                    event_name: 'atlassian:oauth:exchange',
                    request_id: `atlassian-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    credential_name: data.credentialName || 'Jira',
                    jira_site: jiraSite,
                    scopes,
                });

                console.log('[useAtlassianOAuth] Exchange response:', response);

                if (response?.success) {
                    const result: AtlassianOAuthResult = {
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        cloudId: response.cloud_id ?? undefined,
                        siteName: response.site_name ?? undefined,
                        siteUrl: response.site_url ?? undefined,
                    };
                    setError(null);
                    optionsRef.current.onSuccess?.(result);
                    return;
                }

                const errorMsg =
                    response?.error ||
                    response?.message ||
                    'Failed to exchange authorization code';
                const availableSites = Array.isArray(response?.available_sites)
                    ? (response.available_sites as AtlassianAvailableSite[]).filter(site => site.url)
                    : [];

                if (availableSites.length > 0) {
                    setError(errorMsg);
                    optionsRef.current.onSiteSuggestion?.({
                        message: errorMsg,
                        availableSites,
                        useSite: async (siteUrl: string) => {
                            connect(data.credentialName || 'Jira', scopes, siteUrl);
                        },
                    });
                    return;
                }

                throw new Error(errorMsg);
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useAtlassianOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
            }
        },
        [connect]
    );

    // Listen for postMessage from OAuth callback
    useEffect(() => {
        const handleMessage = async (event: MessageEvent) => {
            // Check if this is our OAuth callback
            const data = event.data as AtlassianOAuthCallbackData;
            if (data?.type !== 'atlassian-oauth-callback') return;
            if (!isTrustedCallbackOrigin(event.origin)) return;

            // Only process if THIS instance initiated the connect (prevents race between multiple instances)
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useAtlassianOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            await exchangeCallback(data, data.jiraSite);
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, [exchangeCallback]);

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
