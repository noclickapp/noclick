// Hook for managing Supabase OAuth flow with PKCE in NodeCredentials.
// Handles popup window, postMessage communication, and token exchange via backend.
// After token exchange, the backend lists the user's projects. If there is one project
// it is auto-selected; if there are multiple the onNeedsSelection callback is invoked
// so the UI can present a project picker (like the Facebook/Instagram multi-account flow).

import { useCallback, useEffect, useRef, useState } from 'react';
import { useOAuthExchange } from './OAuthExchangeContext';

export interface SupabaseProject {
    ref: string;
    name: string;
    organization_id?: string;
}

interface SupabaseOAuthResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    projectUrl?: string;
    error?: string;
}

interface UseSupabaseOAuthOptions {
    onSuccess?: (result: SupabaseOAuthResult) => void;
    onError?: (error: string) => void;
    onNeedsSelection?: (projects: SupabaseProject[], pendingId: string) => void;
}

interface SupabaseOAuthCallbackData {
    type: 'supabase-oauth-callback';
    success: boolean;
    code?: string;
    redirectUri?: string;
    codeVerifier?: string;
    credentialName?: string;
    error?: string;
}

export function useSupabaseOAuth(options: UseSupabaseOAuthOptions = {}) {
    // OAuth exchange routes through the transport context: socket in-app,
    // HTTP on the public provide page. Ref so the message-handler closure stays fresh.
    const oauthExchange = useOAuthExchange();
    const oauthExchangeRef = useRef(oauthExchange);
    useEffect(() => { oauthExchangeRef.current = oauthExchange; }, [oauthExchange]);
    const [isConnecting, setIsConnecting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);
    const isConnectingRef = useRef(false);

    useEffect(() => {
        optionsRef.current = options;
    }, [options]);

    useEffect(() => {
        const handleMessage = async (event: MessageEvent) => {
            const data = event.data as SupabaseOAuthCallbackData;
            if (data?.type !== 'supabase-oauth-callback') return;
            if (!isConnectingRef.current) return;
            isConnectingRef.current = false;

            console.log('[useSupabaseOAuth] Received callback:', data);

            if (!data.success) {
                const errorMsg = data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            try {
                console.log('[useSupabaseOAuth] Exchanging code for tokens...');
                const response = await oauthExchangeRef.current({
                    event_name: 'supabase:oauth:exchange',
                    request_id: `supabase-oauth-${Date.now()}`,
                    code: data.code,
                    redirect_uri: data.redirectUri,
                    code_verifier: data.codeVerifier,
                    credential_name: data.credentialName || 'Supabase',
                });

                console.log('[useSupabaseOAuth] Exchange response:', response);

                if (response?.needs_project_selection) {
                    // Backend found multiple projects — let the UI show a project picker.
                    // isConnecting stays true (cleared by selectProject or error).
                    optionsRef.current.onNeedsSelection?.(
                        response.projects || [],
                        response.pending_id || ''
                    );
                    return;
                }

                if (response?.success) {
                    setError(null);
                    setIsConnecting(false);
                    optionsRef.current.onSuccess?.({
                        success: true,
                        credentialId: response.credential_id ?? undefined,
                        credentialName: response.credential_name ?? undefined,
                        projectUrl: response.project_url ?? undefined,
                    });
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useSupabaseOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    /** Send supabase:oauth:select_project after the user picks from multiple projects. */
    const selectProject = useCallback(async (projectRef: string, pendingId: string) => {
        try {
            const response = await oauthExchangeRef.current({
                event_name: 'supabase:oauth:select_project',
                request_id: `supabase-select-${Date.now()}`,
                project_ref: projectRef,
                pending_id: pendingId,
            });

            if (response?.success) {
                setError(null);
                setIsConnecting(false);
                optionsRef.current.onSuccess?.({
                    success: true,
                    credentialId: response.credential_id ?? undefined,
                    credentialName: response.credential_name ?? undefined,
                    projectUrl: response.project_url ?? undefined,
                });
            } else {
                throw new Error(response?.error || response?.message || 'Failed to select project');
            }
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Project selection failed';
            setError(errorMsg);
            setIsConnecting(false);
            optionsRef.current.onError?.(errorMsg);
        }
    }, []);

    /** Open the Supabase OAuth popup. No project URL required — backend handles project listing. */
    const connect = useCallback((credentialName: string) => {
        setIsConnecting(true);
        isConnectingRef.current = true;
        setError(null);

        const params = new URLSearchParams({ name: credentialName });

        const width = 500;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        const popup = window.open(
            `/api/auth/supabase/authorize?${params.toString()}`,
            'supabase-oauth',
            `width=${width},height=${height},left=${left},top=${top},popup=yes`
        );

        if (!popup) {
            setIsConnecting(false);
            isConnectingRef.current = false;
            const msg = 'Popup was blocked. Please allow popups for this site.';
            setError(msg);
            optionsRef.current.onError?.(msg);
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

    return { connect, selectProject, isConnecting, error, clearError };
}
