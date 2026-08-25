// Dropbox OAuth authorize route.
// Redirects to Dropbox's consent screen to request user authorization.
// Dropbox uses standard OAuth 2.0 flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const DROPBOX_AUTH_URL = 'https://www.dropbox.com/oauth2/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'dropbox');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Dropbox';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'account_info.read,files.metadata.read,files.metadata.write,files.content.read,files.content.write,sharing.read,sharing.write,file_requests.read,file_requests.write';

    const clientId = process.env.DROPBOX_CLIENT_ID;
    const redirectUri = process.env.DROPBOX_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[dropbox.authorize] Missing DROPBOX_CLIENT_ID or DROPBOX_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'dropbox',
            missing: ['DROPBOX_CLIENT_ID', 'DROPBOX_REDIRECT_URI'],
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

    // Dropbox expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        token_access_type: 'offline', // Request refresh token
        state: state,
    });

    // Only add scope if scopes are specified
    if (spaceSeparatedScopes) {
        params.set('scope', spaceSeparatedScopes);
    }

    const authUrl = `${DROPBOX_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
