// Microsoft OAuth callback route.
// Handles the redirect from Microsoft after user grants permission.
// Works with Microsoft Graph API (Outlook, OneDrive, etc.) - scope-agnostic.
// Passes the authorization code back to the opener window via postMessage.

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
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

// The user-flow errors Entra sends when the tenant's consent policy needs an admin
// (90094 "The grant requires admin permission", 65001 "has not consented"). A user
// declining (65004) is not one of them.
const ADMIN_CONSENT_REQUIRED_RE = /AADSTS(90094|65001)\b/;
const ADMIN_CONSENT_REQUIRED_MESSAGE =
    'Your organization requires an admin to approve NoClick before you can connect. Ask an admin to use "approve NoClick for your organization" under the Connect button.';

export async function loader({
    request,
}: LoaderFunctionArgs): Promise<LoaderData> {
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');
    const errorDescription = url.searchParams.get('error_description');
    // Microsoft stamps admin_consent=True on both outcomes of the admin-consent flow.
    const isAdminConsent = /^true$/i.test(
        url.searchParams.get('admin_consent') || ''
    );

    if (error) {
        console.error(
            '[microsoft.callback] OAuth error:',
            error,
            errorDescription,
            isAdminConsent ? '(admin consent)' : ''
        );
        const detail = errorDescription || `Microsoft OAuth error: ${error}`;
        if (isAdminConsent) {
            return {
                success: false,
                error: `Admin approval was not granted: ${detail}`,
            };
        }
        if (ADMIN_CONSENT_REQUIRED_RE.test(errorDescription || '')) {
            return { success: false, error: ADMIN_CONSENT_REQUIRED_MESSAGE };
        }
        return { success: false, error: detail };
    }

    if (!stateB64 || (!code && !isAdminConsent)) {
        console.error('[microsoft.callback] Missing code or state');
        return {
            success: false,
            error: 'Missing authorization code or state parameter',
        };
    }

    // Decode state
    let state: { credentialName?: string; scopes?: string[] };
    try {
        state = JSON.parse(
            Buffer.from(stateB64, 'base64url').toString('utf-8')
        );
    } catch (e) {
        console.error('[microsoft.callback] Failed to decode state:', e);
        return {
            success: false,
            error: 'Invalid state parameter',
        };
    }

    if (isAdminConsent) {
        // Admin consent returns no code: continue into the normal sign-in with the
        // same credential name + scopes so the admin's own credential is minted.
        const next = new URLSearchParams({
            name: state.credentialName || '',
            scopes: (state.scopes || []).join(','),
        });
        throw redirect(`/api/auth/microsoft/authorize?${next.toString()}`, {
            headers: { 'Cache-Control': 'no-store' },
        });
    }

    return {
        success: true,
        code: code as string,
        redirectUri: process.env.MICROSOFT_REDIRECT_URI,
        credentialName: state.credentialName,
        scopes: state.scopes,
    };
}

export default function MicrosoftOAuthCallback() {
    const data = useLoaderData<typeof loader>() as LoaderData;
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        // Send result back to opener window via postMessage
        if (window.opener) {
            window.opener.postMessage(
                {
                    type: 'microsoft-oauth-callback',
                    ...data,
                },
                window.location.origin
            );

            if (data.success) {
                setStatus('success');
                // Close window after a short delay to ensure message is received
                setTimeout(() => {
                    window.close();
                }, 1500);
            } else {
                setStatus('error');
                setErrorMessage(data.error || 'Unknown error');
            }
        } else {
            // No opener - user navigated directly to this page
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
                            Connecting to Microsoft...
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
