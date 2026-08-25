// LinkedIn OAuth authorize route.
// Redirects to LinkedIn's consent screen to request user authorization.
// LinkedIn uses OAuth 2.0 with OpenID Connect for authentication.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const LINKEDIN_AUTH_URL = 'https://www.linkedin.com/oauth/v2/authorization';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'linkedin');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'LinkedIn';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'openid,profile,email,w_member_social';

    const clientId = process.env.LINKEDIN_CLIENT_ID;
    const redirectUri = process.env.LINKEDIN_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[linkedin.authorize] Missing LINKEDIN_CLIENT_ID or LINKEDIN_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'linkedin',
            missing: ['LINKEDIN_CLIENT_ID', 'LINKEDIN_REDIRECT_URI'],
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

    // LinkedIn expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: spaceSeparatedScopes,
        state: state,
    });

    const authUrl = `${LINKEDIN_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
