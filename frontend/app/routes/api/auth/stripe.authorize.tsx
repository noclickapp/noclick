// Stripe Connect OAuth authorize route.
// Redirects to Stripe's OAuth consent screen. Stripe Connect uses standard OAuth 2.0 (no PKCE).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const STRIPE_AUTH_URL = 'https://connect.stripe.com/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'stripe');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Stripe';
    const scopesParam = url.searchParams.get('scopes') || 'read_write';

    const clientId = process.env.STRIPE_CONNECT_CLIENT_ID;
    const redirectUri = process.env.STRIPE_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[stripe.authorize] Missing STRIPE_CONNECT_CLIENT_ID or STRIPE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'stripe',
            missing: ['STRIPE_CONNECT_CLIENT_ID', 'STRIPE_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow.
    // We base64 encode it to safely pass through URL.
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        scope: 'read_write',
        redirect_uri: redirectUri,
        state: state,
    });

    const authUrl = `${STRIPE_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
