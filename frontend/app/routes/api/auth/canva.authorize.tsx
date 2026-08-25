// Canva OAuth authorize route with PKCE support.
// Generates PKCE code verifier and challenge, then redirects to Canva's consent screen.
// PKCE (Proof Key for Code Exchange) is required by Canva for OAuth 2.0.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const CANVA_AUTH_URL = 'https://www.canva.com/api/oauth/authorize';

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
    await applyInstanceOAuthEnv(request, 'canva');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Canva';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'asset:read,asset:write,design:meta:read,design:content:read,design:content:write,folder:read,folder:write,profile:read';

    const clientId = process.env.CANVA_CLIENT_ID;
    const redirectUri = process.env.CANVA_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[canva.authorize] Missing CANVA_CLIENT_ID or CANVA_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'canva',
            missing: ['CANVA_CLIENT_ID', 'CANVA_REDIRECT_URI'],
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

    // Canva expects space-separated scopes
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

    const authUrl = `${CANVA_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
