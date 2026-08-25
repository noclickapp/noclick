// GitHub OAuth authorize route.
// Redirects to GitHub's consent screen to request user authorization.
// GitHub uses standard OAuth 2.0 flow (no PKCE required by default).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const GITHUB_AUTH_URL = 'https://github.com/login/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'github');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'GitHub';
    // Fallback only — the caller normally forwards the credential schema's
    // x-oauth-scopes, derived from backend/nodes/scopes/github.py. Keep in sync.
    const scopesParam =
        url.searchParams.get('scopes') ||
        'gist,read:org,read:user,repo,user:email';

    const clientId = process.env.GITHUB_CLIENT_ID;
    const redirectUri = process.env.GITHUB_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[github.authorize] Missing GITHUB_CLIENT_ID or GITHUB_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'github',
            missing: ['GITHUB_CLIENT_ID', 'GITHUB_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // GitHub expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: spaceSeparatedScopes,
        state: state,
    });

    const authUrl = `${GITHUB_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
