// Linear OAuth authorize route.
// Redirects to Linear's consent screen to request user authorization.
// Linear uses standard OAuth 2.0 flow with comma-separated scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const LINEAR_AUTH_URL = 'https://linear.app/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'linear');
    const url = new URL(request.url);
    // Fallback scopes if the caller didn't pass any. `admin` is required for
    // webhookCreate / webhookDelete (Linear trigger nodes). NodeCredentials
    // pulls the canonical list from the credential schema's x-oauth-scopes
    // (see backend/nodes/linear_node.py:LinearOAuthCredential) and passes it
    // via the ?scopes= param — this default only triggers for callers that
    // forgot to.
    const scopesParam =
        url.searchParams.get('scopes') ||
        'read,write,issues:create,comments:create,admin';

    const clientId = process.env.LINEAR_CLIENT_ID;
    const redirectUri = process.env.LINEAR_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[linear.authorize] Missing LINEAR_CLIENT_ID or LINEAR_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'linear',
            missing: ['LINEAR_CLIENT_ID', 'LINEAR_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Linear expects comma-separated scopes
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopesParam,
        state: state,
        prompt: 'consent', // Always show consent screen
    });

    const authUrl = `${LINEAR_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
