// Supabase OAuth callback route.
// Handles the redirect from Supabase after user grants permission.
// Passes the authorization code, PKCE verifier, and project URL back to the
// opener window via postMessage so the hook can complete the token exchange.

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import { type LoaderFunctionArgs } from 'react-router';
import { useLoaderData } from 'react-router';
import { useEffect, useState } from 'react';

interface LoaderData {
    success: boolean;
    code?: string;
    redirectUri?: string;
    codeVerifier?: string;
    credentialName?: string;
    error?: string;
}

export async function loader({
    request,
}: LoaderFunctionArgs): Promise<LoaderData> {
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');
    const errorDescription = url.searchParams.get('error_description');

    if (error) {
        console.error(
            '[supabase.callback] OAuth error:',
            error,
            errorDescription
        );
        return {
            success: false,
            error: errorDescription || `Supabase OAuth error: ${error}`,
        };
    }

    if (!code || !stateB64) {
        console.error('[supabase.callback] Missing code or state');
        return {
            success: false,
            error: 'Missing authorization code or state parameter',
        };
    }

    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson);

        return {
            success: true,
            code,
            redirectUri: process.env.SUPABASE_REDIRECT_URI?.trim(),
            codeVerifier: state.codeVerifier,
            credentialName: state.credentialName,
        };
    } catch (e) {
        console.error('[supabase.callback] Failed to decode state:', e);
        return { success: false, error: 'Invalid state parameter' };
    }
}

export default function SupabaseOAuthCallback() {
    const data = useLoaderData<typeof loader>() as LoaderData;
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        if (window.opener) {
            window.opener.postMessage(
                { type: 'supabase-oauth-callback', ...data },
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
                            Connecting to Supabase...
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
