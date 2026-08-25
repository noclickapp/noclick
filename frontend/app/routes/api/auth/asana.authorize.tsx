// Asana OAuth authorize route.
// Redirects to Asana's consent screen to request user authorization.
// Asana uses standard OAuth 2.0 (authorization_code). The only valid scope is
// 'default', which grants access to all capabilities configured for the app.
// Granular resource-level scopes (tasks:read, projects:write, etc.) do not exist
// in Asana's OAuth model.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const ASANA_AUTH_URL = 'https://app.asana.com/-/oauth_authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'asana');
    const clientId = process.env.ASANA_CLIENT_ID;
    const redirectUri = process.env.ASANA_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[asana.authorize] Missing ASANA_CLIENT_ID or ASANA_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'asana',
            missing: ['ASANA_CLIENT_ID', 'ASANA_REDIRECT_URI'],
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
        scope: 'default',
        state,
    });

    const authUrl = `${ASANA_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
