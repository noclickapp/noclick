// Pipedrive OAuth callback route.
// Handles both editor popups and standalone Marketplace installations.
// Installs use a fresh owner/browser-bound flow and save the credential server-side;
// editor popups return their validated authorization to the editor.
// Pipedrive's Developer Hub allows a SINGLE Callback URL, and it ALSO sends the
// app-uninstall notification here as a DELETE (HTTP Basic auth, body carries
// client_id/company_id/user_id) — handled by `action` below, which removes the matching
// Pipedrive credential(s) so uninstalling in Pipedrive cleans up in NoClick.

import { oauthCallbackUrl } from '~/lib/oauthFlow.server';
import {
    redirect,
    type ActionFunctionArgs,
    type LoaderFunctionArgs,
} from 'react-router';
import { useLoaderData } from 'react-router';
import { useEffect, useState } from 'react';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { json } from '~/lib/routerResponse';

import {
    PIPEDRIVE_INSTALL_PATH as INSTALL_PATH,
    PIPEDRIVE_INSTALL_HEADERS as PRIVATE_HEADERS,
} from '~/lib/pipedriveInstall';
import { requirePipedriveInstallAuth } from '~/lib/pipedriveInstall.server';

export const headers = () => PRIVATE_HEADERS;

interface LoaderData {
    success: boolean;
    code?: string;
    redirectUri?: string;
    scopes?: string[];
    error?: string;
    mode?: 'install';
}

export async function loader({ request }: LoaderFunctionArgs) {
    const incoming = new URL(request.url);
    if (
        incoming.searchParams.get('code') &&
        !incoming.searchParams.get('state') &&
        !incoming.searchParams.has('error')
    ) {
        // Marketplace starts consent without our state. Discard that unbound
        // code; a fresh flow after sign-in establishes browser and owner binding.
        return redirect(INSTALL_PATH, { headers: PRIVATE_HEADERS });
    }
    const url = await oauthCallbackUrl(request);
    const code = url.searchParams.get('code');
    const stateB64 = url.searchParams.get('state');
    const error = url.searchParams.get('error');
    if (error) {
        return json<LoaderData>(
            {
                success: false,
                error:
                    error === 'user_denied'
                        ? 'Pipedrive installation was cancelled. No connection was saved.'
                        : 'Pipedrive could not authorize the connection. Please try again.',
                ...(!stateB64 ? { mode: 'install' as const } : {}),
            },
            { headers: PRIVATE_HEADERS }
        );
    }

    if (!code || !stateB64) {
        console.error('[pipedrive.callback] Missing code or state');
        return json<LoaderData>(
            {
                success: false,
                error: 'Missing authorization code or state parameter',
            },
            { headers: PRIVATE_HEADERS }
        );
    }

    // Decode state (validates the base64url round-trip)
    try {
        const stateJson = Buffer.from(stateB64, 'base64url').toString('utf-8');
        const state = JSON.parse(stateJson) as {
            mode?: string;
            userId?: string;
        };

        if (state.mode === 'install') {
            // If the NoClick session expired, restart after login without the
            // authorization code appearing in a login URL or client loader data.
            const { user, session, headers } =
                await requirePipedriveInstallAuth(request);
            const fail = (message: string) =>
                json<LoaderData>(
                    { success: false, mode: 'install', error: message },
                    { headers }
                );
            if (!state.userId || state.userId !== user.id) {
                return fail(
                    'Your NoClick account changed during installation. Please restart the connection.'
                );
            }
            const redirectUri = process.env.PIPEDRIVE_REDIRECT_URI;
            if (!redirectUri)
                return fail('Pipedrive is not configured on this instance.');
            try {
                const response = await fetch(
                    `${apiBaseUrl()}/api/credential-request/pipedrive/install/exchange`,
                    {
                        method: 'POST',
                        headers: {
                            authorization: `Bearer ${session.access_token}`,
                            'content-type': 'application/json',
                        },
                        body: JSON.stringify({
                            code,
                            redirect_uri: redirectUri,
                        }),
                        signal: AbortSignal.timeout(30_000),
                    }
                );
                if (!response.ok)
                    return fail(
                        'Could not save the Pipedrive connection. Please restart installation or contact support.'
                    );
                const result = (await response.json()) as {
                    success?: boolean;
                    credential_id?: string;
                };
                if (
                    !result.success ||
                    typeof result.credential_id !== 'string' ||
                    !result.credential_id
                ) {
                    return fail(
                        'Pipedrive did not finish connecting. Please restart installation.'
                    );
                }
                return redirect(
                    `/dashboard?tab=settings&section=credentials&account=${encodeURIComponent(result.credential_id)}`,
                    { headers }
                );
            } catch {
                return fail(
                    'Could not finish the Pipedrive installation. Please try again.'
                );
            }
        }

        return json<LoaderData>(
            {
                success: true,
                code,
                redirectUri: process.env.PIPEDRIVE_REDIRECT_URI,
                scopes: [],
            },
            { headers: PRIVATE_HEADERS }
        );
    } catch (e) {
        if (e instanceof Response) throw e;
        return json<LoaderData>(
            {
                success: false,
                error: 'Invalid state parameter',
            },
            { headers: PRIVATE_HEADERS }
        );
    }
}

// Pipedrive app-uninstall callback. Same URL as the OAuth callback (Developer
// Hub allows only one), differentiated by the DELETE method. Authenticated with
// HTTP Basic client_id:client_secret; body = { client_id, company_id, user_id,
// timestamp }. The backend holds the secret, authenticates the provider and
// atomically removes only the exact app/company/user grant. No redirect/retry:
// authorization must never follow a different destination or mask failed cleanup.
export async function action({ request }: ActionFunctionArgs) {
    if (request.method !== 'DELETE') {
        return new Response('Method Not Allowed', { status: 405 });
    }

    const authorization = request.headers.get('authorization');
    if (!authorization || !/^Basic [A-Za-z0-9+/]+=*$/i.test(authorization)) {
        return new Response('Unauthorized', { status: 401 });
    }

    let body: { client_id?: unknown; company_id?: unknown; user_id?: unknown };
    try {
        body = await request.json();
        if (!body || typeof body !== 'object' || Array.isArray(body))
            throw new Error();
    } catch {
        return new Response('Invalid uninstall identity', { status: 400 });
    }
    const digits = (v: unknown) => {
        if (
            typeof v !== 'string' &&
            (typeof v !== 'number' || !Number.isSafeInteger(v))
        )
            return '';
        return /^[1-9][0-9]{0,19}$/.test(String(v)) ? String(v) : '';
    };
    const companyId = digits(body.company_id);
    const userId = digits(body.user_id);
    if (
        !companyId ||
        !userId ||
        typeof body.client_id !== 'string' ||
        !body.client_id ||
        body.client_id.length > 128
    ) {
        return new Response('Invalid uninstall identity', { status: 400 });
    }
    try {
        const response = await fetch(
            `${apiBaseUrl()}/api/credential-request/pipedrive/install/uninstall`,
            {
                method: 'POST',
                headers: { authorization, 'content-type': 'application/json' },
                body: JSON.stringify({
                    client_id: body.client_id,
                    company_id: companyId,
                    user_id: userId,
                }),
                signal: AbortSignal.timeout(30_000),
                redirect: 'error',
            }
        );
        if (!response.ok) {
            const status = [400, 401, 500].includes(response.status)
                ? response.status
                : 502;
            return new Response('Pipedrive cleanup failed', { status });
        }
        const result = (await response.json()) as {
            success?: unknown;
            removed?: unknown;
        };
        if (
            result?.success !== true ||
            typeof result.removed !== 'number' ||
            !Number.isSafeInteger(result.removed) ||
            result.removed < 0
        ) {
            return new Response('Invalid cleanup result', { status: 502 });
        }
        return json(
            { success: true, removed: result.removed },
            { headers: PRIVATE_HEADERS }
        );
    } catch {
        return new Response('Pipedrive cleanup unavailable', { status: 502 });
    }
}

export default function PipedriveOAuthCallback() {
    const data = useLoaderData() as LoaderData;
    const [status, setStatus] = useState<'sending' | 'success' | 'error'>(
        'sending'
    );
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    useEffect(() => {
        if (data.mode === 'install') {
            setStatus('error');
            setErrorMessage(
                data.error || 'Please restart the Pipedrive installation.'
            );
            return;
        }
        // Send result back to opener window via postMessage
        if (window.opener) {
            window.opener.postMessage(
                {
                    type: 'pipedrive-oauth-callback',
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
                data.error ||
                    'The editor window is no longer available. Restart installation to connect Pipedrive in this tab.'
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
                            Connecting to Pipedrive...
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
                            Authorization received
                        </div>
                        <div className="text-muted-foreground/70 dark:text-zinc-500 text-sm">
                            Return to the editor to finish connecting. This
                            window will close automatically.
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
                        <a
                            href={INSTALL_PATH}
                            className="block text-foreground underline mb-4"
                        >
                            Restart Pipedrive installation
                        </a>
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
