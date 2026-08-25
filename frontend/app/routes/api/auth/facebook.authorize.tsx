// Facebook OAuth authorize route for Instagram integration.
// Redirects to Facebook's consent screen with the requested scopes.
// Instagram Graph API requires Facebook Login (connects via Facebook Pages).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const FACEBOOK_AUTH_URL = 'https://www.facebook.com/v21.0/dialog/oauth';

// Default Instagram scopes
const DEFAULT_INSTAGRAM_SCOPES = [
    'instagram_basic',
    'instagram_content_publish',
    'instagram_manage_comments',
    'pages_show_list',
    'pages_read_engagement',
    'business_management',
];

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'facebook');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Instagram Account';
    const scopesParam = url.searchParams.get('scopes');
    const scopes = scopesParam
        ? scopesParam.split(',')
        : DEFAULT_INSTAGRAM_SCOPES;

    const clientId = process.env.FACEBOOK_APP_ID;
    const redirectUri = process.env.FACEBOOK_OAUTH_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[facebook.authorize] Missing FACEBOOK_APP_ID or FACEBOOK_OAUTH_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'facebook',
            missing: ['FACEBOOK_APP_ID', 'FACEBOOK_OAUTH_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
            provider: 'facebook', // Identify this as Facebook/Instagram OAuth
        })
    ).toString('base64url');

    // Facebook expects comma-separated scopes
    const commaSeparatedScopes = scopes.join(',');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: commaSeparatedScopes,
        state: state,
        // auth_type: 'rerequest',  // Uncomment to request declined permissions again
    });

    const authUrl = `${FACEBOOK_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
