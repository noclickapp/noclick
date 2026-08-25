// QuickBooks (Intuit) OAuth callback route.
// Handles the redirect from Intuit after the user grants permission.
// Validates the callback against a short-lived HttpOnly state cookie.
// Registered as the Intuit developer app's redirect URI (/api/auth/intuit/callback).

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import { createCookie, type LoaderFunctionArgs } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useLoaderData } from 'react-router';
import { useEffect, useState } from 'react';

const intuitOAuthStateCookie = createCookie('intuit_oauth_state', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/api/auth/intuit',
    maxAge: 600,
});

interface LoaderData {
    success: boolean;
    code?: string;
    redirectUri?: string;
    realmId?: string;
    isSandbox?: boolean;
    scopes?: string[];
    customClientId?: string;
    customClientSecret?: string;
    error?: string;
}

export async function loader({ request }: LoaderFunctionArgs) {
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const realmId = url.searchParams.get('realmId');
    const error = url.searchParams.get('error');
    const errorDescription = url.searchParams.get('error_description');
    const cookieHeader = await intuitOAuthStateCookie.serialize('', { maxAge: 0 });

    const fail = (message: string, status = 400) =>
        json<LoaderData>(
            { success: false, error: message },
            {
                status,
                headers: { 'Set-Cookie': cookieHeader },
            },
        );

    if (error) {
        console.error('[intuit.callback] OAuth error:', error, errorDescription);
        return fail(errorDescription || `QuickBooks OAuth error: ${error}`);
    }

    if (!code || !stateB64) {
        console.error('[intuit.callback] Missing code or state');
        return fail('Missing authorization code or state parameter');
    }

    if (!realmId) {
        console.error('[intuit.callback] Missing realmId');
        return fail('Missing realmId (company ID) from QuickBooks');
    }

    const cookieValue = request.headers.get('Cookie');
    const storedStateRaw = await intuitOAuthStateCookie.parse(cookieValue);
    if (!storedStateRaw) {
        console.error('[intuit.callback] Missing OAuth state cookie');
        return fail('OAuth session expired. Try connecting again.');
    }

    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson) as { nonce?: string };
        const storedState = JSON.parse(storedStateRaw) as {
            nonce?: string;
            scopes?: string[];
            customClientId?: string | null;
            customClientSecret?: string | null;
            timestamp?: number;
        };

        if (!state.nonce || !storedState.nonce || state.nonce !== storedState.nonce) {
            console.error('[intuit.callback] State nonce mismatch');
            return fail('Invalid OAuth state parameter');
        }
        if (!storedState.timestamp || Date.now() - storedState.timestamp > 10 * 60 * 1000) {
            console.error('[intuit.callback] OAuth state expired');
            return fail('OAuth session expired. Try connecting again.');
        }

        return json<LoaderData>(
            {
                success: true,
                code,
                redirectUri: process.env.QUICKBOOKS_REDIRECT_URI || process.env.INTUIT_REDIRECT_URI,
                realmId,
                // Intuit development keys only work against the sandbox API; set
                // INTUIT_SANDBOX=true (or QUICKBOOKS_SANDBOX) when the app is a dev
                // app so the node targets sandbox-quickbooks.api.intuit.com.
                isSandbox:
                    process.env.QUICKBOOKS_SANDBOX === 'true' ||
                    process.env.INTUIT_SANDBOX === 'true',
                scopes: storedState.scopes || [],
                customClientId: storedState.customClientId || undefined,
                customClientSecret: storedState.customClientSecret || undefined,
            },
            {
                headers: { 'Set-Cookie': cookieHeader },
            },
        );
    } catch (e) {
        console.error('[intuit.callback] Failed to validate state:', e);
        return fail('Invalid state parameter');
    }
}

export default function QuickBooksOAuthCallback() {
    const data = useLoaderData<JsonPayloadOf<typeof loader>>();
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>('sending');
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        if (window.opener) {
            window.opener.postMessage({
                type: 'quickbooks-oauth-callback',
                ...data,
            }, window.location.origin);

            if (data.success) {
                setStatus('success');
                setTimeout(() => {
                    window.close();
                }, 1500);
            } else {
                setStatus('error');
                setErrorMessage(data.error || 'Unknown error');
            }
        } else {
            setStatus('error');
            setErrorMessage('This page should be opened from the workflow editor. Please try connecting again.');
        }
    }, [data]);

    return (
        <div className="flex items-center justify-center min-h-screen bg-zinc-950">
            <div className="text-center p-8 rounded-lg bg-zinc-900 border border-zinc-800 max-w-md">
                {status === 'sending' && (
                    <>
                        <div className="animate-spin w-8 h-8 border-2 border-zinc-700 border-t-white rounded-full mx-auto mb-4" />
                        <div className="text-white mb-2">Connecting to QuickBooks...</div>
                        <div className="text-zinc-500 text-sm">Please wait while we complete the connection.</div>
                    </>
                )}

                {status === 'success' && (
                    <>
                        <div className="w-12 h-12 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                            <svg className="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                        <div className="text-white mb-2">Connected Successfully!</div>
                        <div className="text-zinc-500 text-sm">This window will close automatically.</div>
                    </>
                )}

                {status === 'error' && (
                    <>
                        <div className="w-12 h-12 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                            <svg className="w-6 h-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </div>
                        <div className="text-white mb-2">Connection Failed</div>
                        <div className="text-red-400 text-sm mb-4">{errorMessage}</div>
                        <button
                            onClick={() => window.close()}
                            className="px-4 py-2 text-sm text-white bg-zinc-800 hover:bg-zinc-700 rounded-lg transition-colors"
                        >
                            Close Window
                        </button>
                    </>
                )}
            </div>
        </div>
    );
}
