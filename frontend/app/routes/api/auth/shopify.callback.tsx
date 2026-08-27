// Shopify OAuth callback route.
// Handles the redirect from Shopify after user grants permission.
// Passes the authorization code back to the opener window via postMessage.

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import {
    createCookie,
    redirect,
    type LoaderFunctionArgs,
    useLoaderData,
} from 'react-router';
import { useEffect, useState } from 'react';
import { requireAuth } from '~/lib/supabase';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { verifyShopifyQueryHmac } from '~/lib/shopifyHmac.server';
import { getCookieSecret } from '~/lib/serverSecrets';

const shopifyOAuthStateCookie = createCookie('shopify_oauth_state', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/api/auth/shopify',
    maxAge: 600,
    secrets: [getCookieSecret('shopify-oauth-state')],
});

interface LoaderData {
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

export async function loader({ request }: LoaderFunctionArgs) {
    // Shopify signs the exact callback query string it sends. oauthCallbackUrl
    // decrypts our state parameter for the application below, so retain the
    // original URL for HMAC verification before that transformation.
    const signedUrl = new URL(request.url);
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const shop = url.searchParams.get('shop');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');
    const errorDescription = url.searchParams.get('error_description');

    if (error) {
        console.error(
            '[shopify.callback] OAuth error:',
            error,
            errorDescription
        );
        return {
            success: false,
            error: errorDescription || `Shopify OAuth error: ${error}`,
        };
    }

    if (!code || !stateB64 || !shop) {
        console.error('[shopify.callback] Missing code, state, or shop');
        return {
            success: false,
            error: 'Missing authorization code, state, or shop parameter',
        };
    }

    // Decode state
    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson) as { nonce?: string };
        const cookieRaw = await shopifyOAuthStateCookie.parse(
            request.headers.get('Cookie')
        );
        const cookieState = cookieRaw
            ? (JSON.parse(cookieRaw) as {
                  nonce?: string;
                  shop?: string;
                  credentialName?: string;
                  scopes?: string[];
                  customClientId?: string | null;
                  customClientSecret?: string | null;
                  mode?: 'popup' | 'install';
              })
            : null;

        if (
            !state?.nonce ||
            !cookieState?.nonce ||
            state.nonce !== cookieState.nonce
        ) {
            console.error('[shopify.callback] Invalid state nonce');
            return {
                success: false,
                error: 'Invalid OAuth state. Please try connecting again.',
            };
        }

        const shopifySecret =
            cookieState.customClientSecret ||
            process.env.SHOPIFY_CLIENT_SECRET ||
            '';
        if (!verifyShopifyQueryHmac(signedUrl, shopifySecret)) {
            return {
                success: false,
                error: 'Invalid Shopify request signature.',
            };
        }

        const callbackShop = shop
            .trim()
            .toLowerCase()
            .replace(/\.myshopify\.com$/, '');
        if (callbackShop !== cookieState.shop) {
            return {
                success: false,
                error: 'Shopify store did not match the OAuth request.',
            };
        }

        if (cookieState.mode === 'install') {
            const { session, headers } = await requireAuth(request);
            const redirectUri = process.env.SHOPIFY_REDIRECT_URI;
            if (!redirectUri) {
                return {
                    success: false,
                    error: 'Shopify redirect URI is not configured.',
                };
            }
            const response = await fetch(
                `${apiBaseUrl()}/api/credential-request/shopify/install/exchange`,
                {
                    method: 'POST',
                    headers: {
                        authorization: `Bearer ${session.access_token}`,
                        'content-type': 'application/json',
                    },
                    body: JSON.stringify({
                        code,
                        shop: cookieState.shop,
                        redirect_uri: redirectUri,
                        scopes: cookieState.scopes?.join(',') || '',
                    }),
                }
            );
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                return {
                    success: false,
                    error:
                        typeof detail?.detail === 'string'
                            ? detail.detail
                            : 'Could not finish the Shopify installation.',
                };
            }
            const clientId = process.env.SHOPIFY_CLIENT_ID;
            if (!clientId) {
                return {
                    success: false,
                    error: 'Shopify app client ID is not configured.',
                };
            }
            // Return through Shopify Admin so the embedded app home loads with
            // a fresh signed launch query and App Bridge context. Redirecting
            // directly to /dashboard would strand the merchant off-platform.
            return redirect(
                `https://admin.shopify.com/store/${callbackShop}/apps/${clientId}`,
                { headers }
            );
        }

        return {
            success: true,
            code,
            shop: cookieState.shop,
            redirectUri: process.env.SHOPIFY_REDIRECT_URI,
            credentialName: cookieState.credentialName,
            scopes: cookieState.scopes?.join(','),
            customClientId: cookieState.customClientId || undefined,
            customClientSecret: cookieState.customClientSecret || undefined,
        };
    } catch (e) {
        // requireAuth communicates login redirects by throwing a Response.
        // Preserve that redirect instead of turning an expired NoClick session
        // into a misleading OAuth-state failure.
        if (e instanceof Response) throw e;
        console.error('[shopify.callback] Failed to process callback:', e);
        return {
            success: false,
            error: 'Could not finish the Shopify connection.',
        };
    }
}

export default function ShopifyOAuthCallback() {
    const data = useLoaderData<typeof loader>() as LoaderData;
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        const message = { type: 'shopify-oauth-callback', ...data };

        // BroadcastChannel works even when window.opener is nullified by Shopify's
        // Cross-Origin-Opener-Policy header (which severs opener on cross-origin navigation).
        const channel = new BroadcastChannel('shopify-oauth');
        channel.postMessage(message);
        channel.close();

        // Also try postMessage for browsers/cases where opener is still available.
        if (window.opener) {
            try {
                window.opener.postMessage(message, window.location.origin);
            } catch {
                // COOP may block access — BroadcastChannel already handled it
            }
        }

        if (data.success) {
            setStatus('success');
            setTimeout(() => window.close(), 1500);
        } else {
            setStatus('error');
            setErrorMessage(data.error || 'Unknown error');
        }
    }, [data]);

    return (
        <div className="flex items-center justify-center min-h-screen bg-background dark:bg-zinc-950">
            <div className="text-center p-8 rounded-lg bg-card border border-border max-w-md">
                {status === 'sending' && (
                    <>
                        <div className="animate-spin w-8 h-8 border-2 border-border dark:border-zinc-700 border-t-foreground rounded-full mx-auto mb-4" />
                        <div className="text-foreground mb-2">
                            Connecting to Shopify...
                        </div>
                        <div className="text-muted-foreground/70 dark:text-zinc-500 text-sm">
                            Please wait while we complete the connection.
                        </div>
                    </>
                )}

                {status === 'success' && (
                    <>
                        <div className="w-12 h-12 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                            <svg
                                className="w-6 h-6 text-green-500"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M5 13l4 4L19 7"
                                />
                            </svg>
                        </div>
                        <div className="text-foreground mb-2">
                            Connected Successfully!
                        </div>
                        <div className="text-muted-foreground/70 dark:text-zinc-500 text-sm">
                            This window will close automatically.
                        </div>
                    </>
                )}

                {status === 'error' && (
                    <>
                        <div className="w-12 h-12 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                            <svg
                                className="w-6 h-6 text-red-500"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M6 18L18 6M6 6l12 12"
                                />
                            </svg>
                        </div>
                        <div className="text-foreground mb-2">
                            Connection Failed
                        </div>
                        <div className="text-red-600 dark:text-red-400 text-sm mb-4">
                            {errorMessage}
                        </div>
                        <button
                            onClick={() => window.close()}
                            className="px-4 py-2 text-sm text-foreground bg-secondary hover:bg-accent dark:hover:bg-zinc-700 rounded-lg transition-colors"
                        >
                            Close Window
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}
