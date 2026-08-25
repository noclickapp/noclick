// Twitter/X OAuth callback route.
// Handles the redirect from Twitter after user grants permission.
// Reads codeVerifier directly from the state parameter (set by authorize.tsx),
// then passes everything to the opener window via postMessage.

import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { type LoaderFunctionArgs } from 'react-router';
import { useLoaderData } from 'react-router';
import { useEffect, useState } from 'react';
import { oauthCallbackUrl } from '~/lib/oauthFlow.server';

interface LoaderData {
    success: boolean;
    code?: string;
    redirectUri?: string;
    credentialName?: string;
    codeVerifier?: string;
    error?: string;
}

export async function loader({
    request,
}: LoaderFunctionArgs) {
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');

    if (error) {
        console.error('[x.callback] OAuth error:', error);
        return json<LoaderData>({ success: false, error: `Twitter OAuth error: ${error}` });
    }

    if (!code || !stateB64) {
        console.error('[x.callback] Missing code or state');
        return json<LoaderData>({
            success: false,
            error: 'Missing authorization code or state parameter',
        });
    }

    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson);

        if (!state.codeVerifier) {
            console.error('[x.callback] codeVerifier missing from state');
            return json<LoaderData>({
                success: false,
                error: 'Invalid session data. Please try connecting again.',
            });
        }

        return json<LoaderData>({
            success: true,
            code,
            redirectUri: process.env.X_REDIRECT_URI,
            credentialName: state.credentialName,
            codeVerifier: state.codeVerifier,
        });
    } catch (e) {
        console.error('[x.callback] Failed to decode state:', e);
        return json<LoaderData>({
            success: false,
            error: 'Invalid state parameter. Please try connecting again.',
        });
    }
}

export default function TwitterOAuthCallback() {
    const data = useLoaderData<JsonPayloadOf<typeof loader>>();
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        if (window.opener) {
            window.opener.postMessage(
                {
                    type: 'twitter-oauth-callback',
                    ...data,
                },
                window.location.origin
            );

            if (data.success) {
                setStatus('success');
                setTimeout(() => window.close(), 1500);
            } else {
                setStatus('error');
                setErrorMessage(data.error || 'Unknown error');
            }
        } else {
            setStatus('error');
            setErrorMessage(
                'This page should be opened from the workflow editor. Please try connecting again.'
            );
        }
    }, [data]);

    return (
        <div className="flex items-center justify-center min-h-screen bg-background dark:bg-zinc-950">
            <div className="text-center p-8 rounded-lg bg-card border border-border max-w-md">
                {status === 'sending' && (
                    <>
                        <div className="animate-spin w-8 h-8 border-2 border-border dark:border-zinc-700 border-t-foreground rounded-full mx-auto mb-4" />
                        <div className="text-foreground mb-2">
                            Connecting to Twitter...
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
