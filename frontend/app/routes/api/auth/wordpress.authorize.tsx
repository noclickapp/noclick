// WordPress.com OAuth authorize route.
// Redirects to WordPress.com's consent screen for OAuth authorization.
// WordPress.com uses standard OAuth 2.0 flow (no PKCE required).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const WORDPRESS_AUTH_URL = 'https://public-api.wordpress.com/oauth2/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'wordpress');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'WordPress';
    const scopesParam = url.searchParams.get('scopes') || 'global';
    const siteId = url.searchParams.get('site_id') || '';

    const clientId = process.env.WORDPRESS_CLIENT_ID;
    const redirectUri = process.env.WORDPRESS_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[wordpress.authorize] Missing WORDPRESS_CLIENT_ID or WORDPRESS_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'wordpress',
            missing: ['WORDPRESS_CLIENT_ID', 'WORDPRESS_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            siteId,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // WordPress.com expects space-separated scopes (typically just 'global')
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        state: state,
    });

    const authUrl = `${WORDPRESS_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
