// ClickUp OAuth authorize route.
// Redirects to ClickUp's consent screen to request user authorization.
// ClickUp uses standard OAuth 2.0 (authorization_code) with NO scopes;
// the user selects which Workspace(s) to authorize on the consent screen.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const CLICKUP_AUTH_URL = 'https://app.clickup.com/api';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'clickup');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || '';

    const clientId = process.env.CLICKUP_CLIENT_ID;
    const redirectUri = process.env.CLICKUP_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[clickup.authorize] Missing CLICKUP_CLIENT_ID or CLICKUP_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'clickup',
            missing: ['CLICKUP_CLIENT_ID', 'CLICKUP_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip.
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // ClickUp's authorize endpoint takes only client_id, redirect_uri and state.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        state,
    });

    const authUrl = `${CLICKUP_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
