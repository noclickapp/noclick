// Hook for managing MCP OAuth flow for MCP Server nodes.
// Handles OAuth discovery, PKCE, dynamic client registration, and token exchange.
// MCP servers announce their OAuth requirements via protected resource metadata (RFC 9728).

import { useState, useEffect, useCallback, useRef } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

// MCP OAuth discovery result from backend
export interface MCPOAuthDiscoveryResult {
    success: boolean;
    requires_oauth: boolean;
    provider_name?: string;
    authorization_endpoint?: string;
    token_endpoint?: string;
    scopes_supported?: string[];
    supports_dynamic_registration: boolean;
    registration_endpoint?: string;
    code_verifier?: string;
    code_challenge?: string;
    resource_url?: string;
    error?: string;
}

// MCP OAuth exchange result
interface MCPOAuthExchangeResult {
    success: boolean;
    credential_id?: string;
    credential_name?: string;
    provider_name?: string;
    error?: string;
    message?: string;
}

// Dynamic client registration result
interface MCPClientRegistrationResult {
    success: boolean;
    client_id?: string;
    message?: string;
}

interface UseMCPOAuthOptions {
    onCredentialCreated?: (credentialId: string, credentialName: string) => void;
    onError?: (error: string) => void;
}

interface MCPOAuthCallbackData {
    type: 'mcp-oauth-callback';
    success: boolean;
    code?: string;
    state?: string;
    error?: string;
    error_description?: string;
}

// NoClick's default MCP OAuth client ID (for servers that don't support dynamic registration)
const NOCLICK_MCP_CLIENT_ID = 'noclick-mcp-client';

export function useMCPOAuth(options: UseMCPOAuthOptions = {}) {
    const [isDiscovering, setIsDiscovering] = useState(false);
    const [isConnecting, setIsConnecting] = useState(false);
    const [discoveryResult, setDiscoveryResult] = useState<MCPOAuthDiscoveryResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const optionsRef = useRef(options);

    // Store PKCE and OAuth state for callback
    const oauthStateRef = useRef<{
        serverUrl: string;
        codeVerifier: string;
        tokenEndpoint: string;
        clientId: string;
        providerName?: string;
        resourceUrl?: string;
    } | null>(null);

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
            const data = event.data as MCPOAuthCallbackData;
            if (data?.type !== 'mcp-oauth-callback') return;

            console.log('[useMCPOAuth] Received callback:', data);

            if (!data.success || !data.code) {
                const errorMsg = data.error_description || data.error || 'OAuth failed';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Get stored OAuth state
            const state = oauthStateRef.current;
            if (!state) {
                const errorMsg = 'OAuth state not found';
                setError(errorMsg);
                setIsConnecting(false);
                optionsRef.current.onError?.(errorMsg);
                return;
            }

            // Exchange code for tokens via backend
            try {
                console.log('[useMCPOAuth] Exchanging code for tokens...');
                const response = await sendEventAsync({
                    event_name: 'mcp:oauth:exchange',
                    request_id: `mcp-oauth-${Date.now()}`,
                    code: data.code,
                    code_verifier: state.codeVerifier,
                    token_endpoint: state.tokenEndpoint,
                    client_id: state.clientId,
                    redirect_uri: `${window.location.origin}/api/auth/mcp/callback`,
                    resource_url: state.resourceUrl,
                    server_url: state.serverUrl,
                    provider_name: state.providerName,
                }) as MCPOAuthExchangeResult;

                console.log('[useMCPOAuth] Exchange response:', response);

                if (response?.success && response.credential_id) {
                    setError(null);
                    optionsRef.current.onCredentialCreated?.(
                        response.credential_id,
                        response.credential_name || 'MCP OAuth'
                    );
                } else {
                    throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                }
            } catch (err) {
                const errorMsg = err instanceof Error ? err.message : 'OAuth exchange failed';
                console.error('[useMCPOAuth] Exchange error:', errorMsg);
                setError(errorMsg);
                optionsRef.current.onError?.(errorMsg);
            } finally {
                setIsConnecting(false);
                oauthStateRef.current = null;
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, []);

    // Discover OAuth requirements for an MCP server URL
    const discover = useCallback(async (serverUrl: string): Promise<MCPOAuthDiscoveryResult | null> => {
        if (!serverUrl) {
            setDiscoveryResult(null);
            return null;
        }

        setIsDiscovering(true);
        setError(null);

        try {
            console.log('[useMCPOAuth] Discovering OAuth for:', serverUrl);
            const response = await sendEventAsync({
                event_name: 'mcp:oauth:discover',
                request_id: `mcp-discover-${Date.now()}`,
                server_url: serverUrl,
            }) as MCPOAuthDiscoveryResult;

            console.log('[useMCPOAuth] Discovery response:', response);

            if (response?.success) {
                setDiscoveryResult(response);
                return response;
            } else {
                const errorMsg = response?.error || 'Discovery failed';
                setError(errorMsg);
                setDiscoveryResult(null);
                return null;
            }
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'OAuth discovery failed';
            console.error('[useMCPOAuth] Discovery error:', errorMsg);
            setError(errorMsg);
            setDiscoveryResult(null);
            return null;
        } finally {
            setIsDiscovering(false);
        }
    }, []);

    // Connect to OAuth (start OAuth flow)
    const connect = useCallback(async (serverUrl: string, credentialName?: string) => {
        if (!discoveryResult?.requires_oauth || !discoveryResult.authorization_endpoint) {
            setError('OAuth discovery required before connecting');
            return;
        }

        setIsConnecting(true);
        setError(null);

        try {
            // Get client ID - either from dynamic registration or use default
            let clientId = NOCLICK_MCP_CLIENT_ID;

            if (discoveryResult.supports_dynamic_registration && discoveryResult.registration_endpoint) {
                console.log('[useMCPOAuth] Registering dynamic client...');
                const regResponse = await sendEventAsync({
                    event_name: 'mcp:oauth:register-client',
                    request_id: `mcp-register-${Date.now()}`,
                    registration_endpoint: discoveryResult.registration_endpoint,
                    client_name: 'NoClick MCP Client',
                    redirect_uris: [`${window.location.origin}/api/auth/mcp/callback`],
                }) as MCPClientRegistrationResult;

                if (regResponse?.success && regResponse.client_id) {
                    clientId = regResponse.client_id;
                    console.log('[useMCPOAuth] Registered client:', clientId);
                } else {
                    console.warn('[useMCPOAuth] Dynamic registration failed, using default client');
                }
            }

            // Store state for callback
            oauthStateRef.current = {
                serverUrl,
                codeVerifier: discoveryResult.code_verifier!,
                tokenEndpoint: discoveryResult.token_endpoint!,
                clientId,
                providerName: discoveryResult.provider_name,
                resourceUrl: discoveryResult.resource_url,
            };

            // Build authorization URL
            const params = new URLSearchParams({
                response_type: 'code',
                client_id: clientId,
                redirect_uri: `${window.location.origin}/api/auth/mcp/callback`,
                code_challenge: discoveryResult.code_challenge!,
                code_challenge_method: 'S256',
                state: btoa(JSON.stringify({
                    serverUrl,
                    credentialName: credentialName || `MCP (${new URL(serverUrl).hostname})`,
                })),
            });

            // Add resource indicator if available (RFC 8707)
            if (discoveryResult.resource_url) {
                params.set('resource', discoveryResult.resource_url);
            }

            // Add scopes if available
            if (discoveryResult.scopes_supported?.length) {
                params.set('scope', discoveryResult.scopes_supported.join(' '));
            }

            const authUrl = `${discoveryResult.authorization_endpoint}?${params.toString()}`;
            console.log('[useMCPOAuth] Opening authorization URL:', authUrl);

            // Calculate popup position (centered on screen)
            const width = 600;
            const height = 700;
            const left = window.screenX + (window.outerWidth - width) / 2;
            const top = window.screenY + (window.outerHeight - height) / 2;

            // Open OAuth flow in popup window
            const popup = window.open(
                authUrl,
                'mcp-oauth',
                `width=${width},height=${height},left=${left},top=${top},popup=yes`
            );

            // Handle case where popup was blocked
            if (!popup) {
                setIsConnecting(false);
                setError('Popup was blocked. Please allow popups for this site.');
                optionsRef.current.onError?.('Popup was blocked');
                oauthStateRef.current = null;
                return;
            }

            // Monitor if popup is closed without completing OAuth
            const checkClosed = setInterval(() => {
                try {
                    if (popup.closed) {
                        clearInterval(checkClosed);
                        // Give a small delay for postMessage to process
                        setTimeout(() => {
                            if (oauthStateRef.current) {
                                setIsConnecting(false);
                                oauthStateRef.current = null;
                            }
                        }, 500);
                    }
                } catch {
                    // COOP policy blocked access - clear interval and rely on postMessage
                    clearInterval(checkClosed);
                }
            }, 500);
        } catch (err) {
            const errorMsg = err instanceof Error ? err.message : 'Failed to start OAuth flow';
            console.error('[useMCPOAuth] Connect error:', errorMsg);
            setError(errorMsg);
            setIsConnecting(false);
            optionsRef.current.onError?.(errorMsg);
        }
    }, [discoveryResult]);

    const clearError = useCallback(() => {
        setError(null);
    }, []);

    const clearDiscovery = useCallback(() => {
        setDiscoveryResult(null);
        setError(null);
    }, []);

    return {
        discover,
        connect,
        isDiscovering,
        isConnecting,
        discoveryResult,
        error,
        clearError,
        clearDiscovery,
    };
}
