// Facebook OAuth callback route for Instagram integration.
// Handles the redirect from Facebook after user grants permission.
// Instagram Graph API requires Facebook Login (connects via Facebook Pages).
// Uses BroadcastChannel (not window.opener.postMessage) to relay the authorization
// code back to the main window. window.opener becomes null after the popup navigates
// through facebook.com (cross-origin), so postMessage would silently fail.

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import { type LoaderFunctionArgs } from 'react-router';
import { useLoaderData } from 'react-router';
import { useEffect, useState } from 'react';

interface LoaderData {
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    scopes?: string[];
    error?: string;
}

export async function loader({
    request,
}: LoaderFunctionArgs): Promise<LoaderData> {
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');
    const errorReason = url.searchParams.get('error_reason');
    const errorDescription = url.searchParams.get('error_description');

    if (error) {
        console.error('[facebook.callback] OAuth error:', {
            error,
            errorReason,
            errorDescription,
        });

        // User declined permissions
        if (error === 'access_denied') {
            return {
                success: false,
                error: 'Access denied. Please grant the required permissions to connect your Instagram account.',
            };
        }

        return {
            success: false,
            error: errorDescription || `Facebook OAuth error: ${error}`,
        };
    }

    if (!code || !stateB64) {
        console.error('[facebook.callback] Missing code or state');
        return {
            success: false,
            error: 'Missing authorization code or state parameter',
        };
    }

    // Decode state
    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson);

        // Basic CSRF protection - check timestamp is recent (within 10 minutes)
        const ageMs = Date.now() - state.timestamp;
        if (ageMs > 10 * 60 * 1000) {
            console.error('[facebook.callback] State expired:', { ageMs });
            return {
                success: false,
                error: 'OAuth session expired. Please try again.',
            };
        }

        return {
            success: true,
            code,
            redirectUri: process.env.FACEBOOK_OAUTH_REDIRECT_URI,
            credentialName: state.credentialName,
            scopes: state.scopes,
        };
    } catch (e) {
        console.error('[facebook.callback] Failed to decode state:', e);
        return {
            success: false,
            error: 'Invalid state parameter',
        };
    }
}

export default function FacebookOAuthCallback() {
    const data = useLoaderData<typeof loader>() as LoaderData;
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        const payload = { type: 'facebook-oauth-callback', ...data };

        // BroadcastChannel works between same-origin contexts without needing window.opener.
        // The redirect URI must match the origin the main window is served from so both
        // the popup (at the callback URL) and the main window are same-origin.
        const channel = new BroadcastChannel('facebook-oauth');
        channel.postMessage(payload);
        channel.close();

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
                        <div className="animate-spin w-8 h-8 border-2 border-border dark:border-zinc-700 border-t-pink-500 rounded-full mx-auto mb-4" />
                        <div className="text-foreground mb-2">
                            Connecting to Instagram...
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
                            Instagram Connected Successfully!
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
