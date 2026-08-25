// TikTok OAuth authorize route.
// Redirects to TikTok's consent screen for OAuth authorization.
// TikTok uses standard OAuth 2.0 Authorization Code flow.
// Note: TikTok uses 'client_key' (not 'client_id') in the authorization URL.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const TIKTOK_AUTH_URL = 'https://www.tiktok.com/v2/auth/authorize/';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'tiktok');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'TikTok Account';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'user.info.basic,user.info.profile,user.info.stats,video.list,video.upload';

    const clientKey = process.env.TIKTOK_CLIENT_KEY;
    const redirectUri = process.env.TIKTOK_REDIRECT_URI;

    if (!clientKey || !redirectUri) {
        console.error(
            '[tiktok.authorize] Missing TIKTOK_CLIENT_KEY or TIKTOK_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'tiktok',
            missing: ['TIKTOK_CLIENT_KEY', 'TIKTOK_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // TikTok requires comma-separated scopes
    const params = new URLSearchParams({
        client_key: clientKey,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopesParam,
        state: state,
    });

    const authUrl = `${TIKTOK_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
