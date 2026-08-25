/*
Handles OAuth callbacks for both:
1. Authorization code flow (SP-initiated SSO) - tokens in query params ?code=xxx
2. Implicit flow (IdP-initiated SSO) - tokens in URL fragment #access_token=xxx

*/
import { redirect, type LoaderFunctionArgs, type MetaFunction } from 'react-router';
import { json, type JsonPayloadOf } from '~/lib/routerResponse';
import { useEffect, useState } from 'react';
import { useLoaderData, useNavigate } from 'react-router';
import { createServerSupabaseClient, createBrowserSupabaseClient } from '~/lib/supabase';
import { buildSeoMeta } from '~/lib/seo';
import {
    getValidRedirectUrl,
    parseAuthCallbackError,
    resolveAuthCallbackErrorPath,
    authErrorPagePath,
    logSupabaseAuthError,
} from '~/lib/authCallbackErrors';

export const meta: MetaFunction = () =>
    buildSeoMeta({
        title: 'Signing In - NoClick',
        description: 'Completing your NoClick sign-in.',
        indexable: false,
    });

export async function loader({ request }: LoaderFunctionArgs) {
    const requestUrl = new URL(request.url);
    const code = requestUrl.searchParams.get('code');
    const next = requestUrl.searchParams.get('next');
    const headers = new Headers();

    // Validate the redirect URL
    const redirectTo = getValidRedirectUrl(next, requestUrl.origin);

    // Supabase redirects back with error params (and no code) when verification failed upstream
    // (user cancelled the provider consent screen, expired email link, DB error creating the user).
    const authError = parseAuthCallbackError(requestUrl.searchParams);
    if (authError) {
        return redirect(
            resolveAuthCallbackErrorPath(authError, 'AuthCallback', next ? redirectTo : null),
            { headers },
        );
    }

    // Authorization code flow (SP-initiated SSO)
    if (code) {
        const supabase = createServerSupabaseClient(request, headers);
        const { error } = await supabase.auth.exchangeCodeForSession(code);

        if (!error) {
            return redirect(redirectTo, { headers });
        }
        // hadVerifierCookie distinguishes "link opened in a different browser context"
        // (cookie absent -> GoTrue validation_failed) from a genuine exchange fault.
        logSupabaseAuthError('AuthCallback', 'Code exchange failed', error, {
            hadVerifierCookie: (request.headers.get('Cookie') ?? '').includes(
                '-auth-token-code-verifier',
            ),
        });
        return redirect(authErrorPagePath(error.code || 'exchange_failed'), { headers });
    }

    // No code - might be implicit flow with tokens in URL fragment
    // Return env vars for client-side Supabase client
    return json({
        env: {
            SUPABASE_URL: process.env.SUPABASE_URL!,
            SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY!,
        },
    });
}

// Client component to handle implicit flow (IdP-initiated SSO)
// URL fragments (#access_token=...) are only available client-side
export default function AuthCallback() {
    const { env } = useLoaderData<JsonPayloadOf<typeof loader>>();
    const navigate = useNavigate();
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const handleImplicitFlow = async () => {
            const hash = window.location.hash;
            const hashParams = new URLSearchParams(hash.startsWith('#') ? hash.substring(1) : hash);

            // Errors can arrive solely in the fragment (the loader only sees query params)
            const authError = parseAuthCallbackError(hashParams);
            if (authError) {
                const rawNext =
                    hashParams.get('next') ?? new URLSearchParams(window.location.search).get('next');
                const validatedNext = rawNext ? getValidRedirectUrl(rawNext, window.location.origin) : null;
                navigate(resolveAuthCallbackErrorPath(authError, 'AuthCallback', validatedNext), {
                    replace: true,
                });
                return;
            }

            // Check if we have tokens in the URL fragment
            if (hash && hash.includes('access_token=')) {
                const accessToken = hashParams.get('access_token');
                const refreshToken = hashParams.get('refresh_token');

                if (accessToken && refreshToken) {
                    const supabase = createBrowserSupabaseClient(env);
                    const { error } = await supabase.auth.setSession({
                        access_token: accessToken,
                        refresh_token: refreshToken,
                    });

                    if (!error) {
                        // Get redirect URL from the hash params or default to dashboard
                        const next = hashParams.get('next');
                        const redirectTo = getValidRedirectUrl(next, window.location.origin);
                        navigate(redirectTo, { replace: true });
                        return;
                    }
                    logSupabaseAuthError('AuthCallback', 'Failed to set session from fragment tokens', error);
                    setError('Failed to set session');
                    return;
                }
            }

            // No code, no tokens, no error params — malformed callback
            navigate(authErrorPagePath('missing_tokens'), { replace: true });
        };

        handleImplicitFlow();
    }, [navigate, env]);

    if (error) {
        return (
            <div className="flex min-h-screen items-center justify-center">
                <div className="text-center">
                    <h1 className="text-xl font-semibold text-red-600">Authentication Error</h1>
                    <p className="mt-2 text-gray-600">{error}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen items-center justify-center">
            <div className="text-center">
                <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mx-auto"></div>
                <p className="mt-4 text-gray-600">Completing sign in...</p>
            </div>
        </div>
    );
}
