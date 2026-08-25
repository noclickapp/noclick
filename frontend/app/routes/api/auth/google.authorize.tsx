// Unified Google OAuth authorize route.
// Redirects to Google's consent screen with the requested scopes.
// Works for any Google API (Sheets, Gmail, Drive, etc.) - just pass different scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'google');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Google Account';
    const scopes =
        url.searchParams.get('scopes') ||
        'https://www.googleapis.com/auth/spreadsheets';
    const customClientId = url.searchParams.get('custom_client_id');

    const clientId = customClientId || process.env.GOOGLE_CLIENT_ID;
    const redirectUri = process.env.GOOGLE_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[google.authorize] Missing GOOGLE_CLIENT_ID or GOOGLE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'google',
            missing: ['GOOGLE_CLIENT_ID', 'GOOGLE_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopes.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
            ...(customClientId ? { customClientId } : {}),
        })
    ).toString('base64url');

    // Google expects space-separated scopes, but we receive comma-separated
    const spaceSeparatedScopes = scopes.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        access_type: 'offline', // Get refresh token
        prompt: 'consent', // Always show consent to ensure we get refresh token
        state: state,
    });

    const authUrl = `${GOOGLE_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
