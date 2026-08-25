// Pipedrive OAuth authorize route.
// Redirects to Pipedrive's consent screen to request user authorization.
// Pipedrive uses standard OAuth 2.0 (authorization_code); scopes are configured
// per-app in the Developer Hub and are NOT passed at the authorize endpoint.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const PIPEDRIVE_AUTH_URL = 'https://oauth.pipedrive.com/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'pipedrive');
    const clientId = process.env.PIPEDRIVE_CLIENT_ID;
    const redirectUri = process.env.PIPEDRIVE_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[pipedrive.authorize] Missing PIPEDRIVE_CLIENT_ID or PIPEDRIVE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'pipedrive',
            missing: ['PIPEDRIVE_CLIENT_ID', 'PIPEDRIVE_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip.
    const state = Buffer.from(
        JSON.stringify({
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        state,
    });

    const authUrl = `${PIPEDRIVE_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
