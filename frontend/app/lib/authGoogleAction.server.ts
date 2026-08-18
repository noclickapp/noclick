// Shared Google OAuth branch for the sign-in and sign-up route actions: initiates
// the provider redirect (carrying the post-auth `next`) or returns a 400 with the
// error. Factored out so login + register stay identical — signup gained Google
// when the /agents SEO "open this agent" CTA started routing new visitors there.

import { redirect } from 'react-router';
import { json } from '~/lib/routerResponse';
import { authenticate } from '~/lib/auth.server';

export async function handleGoogleOAuthAction(request: Request) {
    const nextUrl = new URL(request.url).searchParams.get('next');
    // OAuth initiation is a redirect to Google, not a credential-bearing request —
    // its CSRF protection comes from the provider's own state/PKCE at the callback,
    // so callers invoke this BEFORE their double-submit CSRF check.
    const { error, authUrl, headers } = await authenticate(
        request,
        'google',
        undefined,
        nextUrl || undefined,
    );
    if (error || !authUrl) {
        return json(
            { error: error || 'Failed to initialize Google login' },
            { status: 400, headers },
        );
    }
    return redirect(authUrl, { headers });
}
