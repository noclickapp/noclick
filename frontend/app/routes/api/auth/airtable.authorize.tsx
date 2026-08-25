// Airtable OAuth authorize route with PKCE support.
// Generates PKCE code verifier and challenge, then redirects to Airtable's consent screen.
// PKCE (Proof Key for Code Exchange) is required by Airtable for OAuth 2.0.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const AIRTABLE_AUTH_URL = 'https://airtable.com/oauth2/v1/authorize';

// Generate PKCE code verifier (43-128 characters)
function generateCodeVerifier(): string {
    return crypto.randomBytes(64).toString('base64url').slice(0, 128);
}

// Generate PKCE code challenge from verifier (S256 method)
function generateCodeChallenge(verifier: string): string {
    return crypto.createHash('sha256').update(verifier).digest('base64url');
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'airtable');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Airtable';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'data.records:read,data.records:write,data.recordComments:read,data.recordComments:write,schema.bases:read,schema.bases:write,webhook:manage';

    const clientId = process.env.AIRTABLE_CLIENT_ID;
    const redirectUri = process.env.AIRTABLE_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[airtable.authorize] Missing AIRTABLE_CLIENT_ID or AIRTABLE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'airtable',
            missing: ['AIRTABLE_CLIENT_ID', 'AIRTABLE_REDIRECT_URI'],
        });
    }

    // Generate PKCE values
    const codeVerifier = generateCodeVerifier();
    const codeChallenge = generateCodeChallenge(codeVerifier);

    // State contains metadata to pass through OAuth flow including PKCE verifier
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            codeVerifier, // Store verifier to use in token exchange
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Airtable expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        state: state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    const authUrl = `${AIRTABLE_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
