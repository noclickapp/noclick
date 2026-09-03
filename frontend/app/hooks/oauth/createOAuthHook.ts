// Factory for the standard credential-OAuth hooks. ~29 providers followed the
// identical template (popup → /api/auth/{provider}/authorize → {provider}-oauth-callback
// postMessage → {provider}:oauth:exchange) differing only in default scopes, delimiter,
// authorize path, and whether scopes ride the URL. This collapses those into one
// implementation + per-provider config, so a template bug shows on ALL providers (loud),
// per-provider risk is limited to the config data, and — crucially — the exchange routes
// through OAuthExchangeContext so the SAME hooks work in-app (socket) and on the public
// provide page (HTTP). Genuinely-different providers (Google custom-client, Shopify shop,
// Zendesk subdomain, Slack user-scopes, Atlassian site, Facebook/Supabase selection,
// Twitter PKCE, Reddit route) keep bespoke hooks — they route exchange through the same
// context.

import { useState, useEffect, useCallback, useRef } from 'react';
import { augmentScopes } from '~/utils/oauthProviders';
import { useOAuthExchange } from './OAuthExchangeContext';

export interface OAuthHookResult {
    success: boolean;
    credentialId?: string;
    credentialName?: string;
    name?: string;
    email?: string;
    error?: string;
}

export interface UseOAuthHookOptions {
    onSuccess?: (result: OAuthHookResult) => void;
    onError?: (error: string) => void;
}

export interface OAuthHookConfig {
    /** Provider key — drives the callback type (`{provider}-oauth-callback`) and the
     *  exchange event (`{provider}:oauth:exchange`). */
    provider: string;
    /** Authorize route (default `/api/auth/{provider}/authorize`). */
    authorizePath?: string;
    /** Scopes requested when the caller passes none. */
    defaultScopes?: string[];
    /** How scopes are joined in the authorize URL (default comma). */
    scopeDelimiter?: string;
    /** Whether scopes ride the authorize URL at all (default true). */
    sendScopes?: boolean;
}

export interface OAuthConnectOptions {
    /** Tenant-wide admin consent instead of a user sign-in (providers with
     *  `supportsOrgConsent`). The authorize route sends the admin to the provider's
     *  admin-consent page and, once granted, chains into the normal sign-in. */
    orgConsent?: boolean;
}

interface OAuthCallbackData {
    type: string;
    success: boolean;
    code?: string;
    redirectUri?: string;
    scopes?: string[];
    credentialName?: string;
    // PKCE providers (Airtable, Canva, PostHog, Klaviyo, …) round-trip the code
    // verifier through the callback; the exchange must forward it to the backend.
    codeVerifier?: string;
    error?: string;
}

/** Pure authorize-URL builder — the risky per-provider surface (path, scopes, delimiter),
 *  extracted so it can be contract-tested without a DOM. Scopes are the caller's (falling
 *  back to defaults), then run through augmentScopes so a provider's always-on identity/
 *  refresh scopes (Google email/profile, Microsoft offline_access) are appended from the
 *  ONE source; providers without extraScopes (e.g. Slack) pass through unchanged. */
export function buildAuthorizeUrl(
    config: OAuthHookConfig,
    credentialName: string,
    scopes?: string[],
    options: OAuthConnectOptions = {},
): string {
    const {
        provider,
        authorizePath = `/api/auth/${provider}/authorize`,
        defaultScopes = [],
        scopeDelimiter = ',',
        sendScopes = true,
    } = config;
    const effectiveScopes = augmentScopes(provider, scopes && scopes.length ? scopes : defaultScopes);
    const params = new URLSearchParams({ name: credentialName });
    if (sendScopes) params.set('scopes', effectiveScopes.join(scopeDelimiter));
    if (options.orgConsent) params.set('admin_consent', '1');
    const qs = params.toString();
    return qs ? `${authorizePath}?${qs}` : authorizePath;
}

/** Build a standard credential-OAuth hook from per-provider config. */
export function createOAuthHook(config: OAuthHookConfig) {
    const { provider, defaultScopes = [] } = config;
    const callbackType = `${provider}-oauth-callback`;
    const exchangeEvent = `${provider}:oauth:exchange`;

    function useOAuthHook(options: UseOAuthHookOptions = {}) {
        const [isConnecting, setIsConnecting] = useState(false);
        const [error, setError] = useState<string | null>(null);
        const optionsRef = useRef(options);
        const isConnectingRef = useRef(false);
        // Captured at connect() so the exchange can send credential_name — several
        // providers (e.g. Microsoft) require it on {provider}:oauth:exchange.
        const credentialNameRef = useRef<string>('');
        const exchange = useOAuthExchange();
        const exchangeRef = useRef(exchange);

        useEffect(() => { optionsRef.current = options; }, [options]);
        useEffect(() => { exchangeRef.current = exchange; }, [exchange]);

        useEffect(() => {
            const handleMessage = async (event: MessageEvent) => {
                if (event.origin !== window.location.origin) return;
                const data = event.data as OAuthCallbackData;
                if (data?.type !== callbackType) return;
                // Only the instance that initiated this connect handles the callback.
                if (!isConnectingRef.current) return;
                isConnectingRef.current = false;

                if (!data.success) {
                    const msg = data.error || 'OAuth failed';
                    setError(msg);
                    setIsConnecting(false);
                    optionsRef.current.onError?.(msg);
                    return;
                }

                try {
                    const response = await exchangeRef.current({
                        event_name: exchangeEvent,
                        request_id: `${provider}-oauth-${Date.now()}`,
                        code: data.code,
                        redirect_uri: data.redirectUri,
                        credential_name: data.credentialName || credentialNameRef.current || `${provider} Account`,
                        scopes: data.scopes && data.scopes.length ? data.scopes : defaultScopes,
                        // Forwarded only for PKCE providers; ignored by others
                        // (ClientEventBase is extra='allow').
                        ...(data.codeVerifier ? { code_verifier: data.codeVerifier } : {}),
                    });
                    if (response?.success) {
                        setError(null);
                        optionsRef.current.onSuccess?.({
                            success: true,
                            credentialId: response.credential_id ?? undefined,
                            credentialName: response.credential_name ?? undefined,
                            name: response.name ?? undefined,
                            email: response.email ?? undefined,
                        });
                    } else {
                        throw new Error(response?.error || response?.message || 'Failed to exchange authorization code');
                    }
                } catch (err) {
                    const msg = err instanceof Error ? err.message : 'OAuth exchange failed';
                    setError(msg);
                    optionsRef.current.onError?.(msg);
                } finally {
                    setIsConnecting(false);
                }
            };

            window.addEventListener('message', handleMessage);
            return () => window.removeEventListener('message', handleMessage);
        }, []);

        const connect = useCallback((credentialName: string, scopes?: string[], options?: OAuthConnectOptions) => {
            setIsConnecting(true);
            isConnectingRef.current = true;
            credentialNameRef.current = credentialName;
            setError(null);

            const width = 500;
            const height = 700;
            const left = window.screenX + (window.outerWidth - width) / 2;
            const top = window.screenY + (window.outerHeight - height) / 2;

            const popup = window.open(
                buildAuthorizeUrl(config, credentialName, scopes, options),
                `${provider}-oauth`,
                `width=${width},height=${height},left=${left},top=${top},popup=yes`,
            );

            if (!popup) {
                setIsConnecting(false);
                isConnectingRef.current = false;
                setError('Popup was blocked. Please allow popups for this site.');
                optionsRef.current.onError?.('Popup was blocked');
                return;
            }

            const failConnect = (msg: string) => {
                if (!isConnectingRef.current) return;
                isConnectingRef.current = false;
                setIsConnecting(false);
                setError(msg);
                optionsRef.current.onError?.(msg);
            };

            // Detect popup close without completing (relies on postMessage
            // otherwise). A popup that closes/crashes mid-flow must surface an
            // error. A silent reset otherwise leaves the form saying
            // "connect" with no explanation of what happened.
            const checkClosed = setInterval(() => {
                try {
                    if (popup.closed) {
                        clearInterval(checkClosed);
                        // Grace period: the callback's postMessage can land just
                        // before/as the popup closes itself on success.
                        setTimeout(() => {
                            failConnect(
                                'The connection window closed before finishing. Please try again.'
                            );
                        }, 500);
                    }
                } catch {
                    clearInterval(checkClosed); // COOP blocked popup.closed — rely on postMessage
                }
            }, 500);

            // Watchdog for the COOP path (and any lost postMessage): without it
            // a dead popup leaves the spinner running forever.
            setTimeout(() => {
                clearInterval(checkClosed);
                failConnect(
                    'The connection timed out. Close any leftover sign-in window and try again.'
                );
            }, 5 * 60 * 1000);
        }, []);

        const clearError = useCallback(() => setError(null), []);

        return { connect, isConnecting, error, clearError };
    }

    // Carry the config so contract tests can pin each provider's authorize behavior.
    useOAuthHook.oauthConfig = config;
    return useOAuthHook;
}
