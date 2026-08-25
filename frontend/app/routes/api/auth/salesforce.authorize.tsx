// Salesforce OAuth authorize route.
// Redirects to Salesforce's consent screen to request user authorization.
// Salesforce uses standard OAuth 2.0 Web Server Flow with PKCE.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const SALESFORCE_AUTH_URL =
    'https://login.salesforce.com/services/oauth2/authorize';
const SALESFORCE_SANDBOX_AUTH_URL =
    'https://test.salesforce.com/services/oauth2/authorize';

/**
 * Generate a cryptographically random code verifier for PKCE.
 * Must be 43-128 characters, using unreserved URI characters.
 */
function generateCodeVerifier(): string {
    // Generate 32 random bytes and base64url encode them (gives us 43 characters)
    return crypto.randomBytes(32).toString('base64url');
}

/**
 * Generate the code challenge from the code verifier using SHA256.
 * This is the S256 method required by Salesforce.
 */
function generateCodeChallenge(verifier: string): string {
    return crypto.createHash('sha256').update(verifier).digest('base64url');
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'salesforce');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Salesforce';
    const scopesParam = url.searchParams.get('scopes') || 'api,refresh_token';
    const isSandbox = url.searchParams.get('sandbox') === 'true';

    const clientId = process.env.SALESFORCE_CLIENT_ID?.trim();
    const redirectUri = process.env.SALESFORCE_REDIRECT_URI?.trim();

    if (!clientId || !redirectUri) {
        console.error(
            '[salesforce.authorize] Missing SALESFORCE_CLIENT_ID or SALESFORCE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'salesforce',
            missing: ['SALESFORCE_CLIENT_ID', 'SALESFORCE_REDIRECT_URI'],
        });
    }

    // Generate PKCE code verifier and challenge
    const codeVerifier = generateCodeVerifier();
    const codeChallenge = generateCodeChallenge(codeVerifier);

    // State contains metadata to pass through OAuth flow
    // We include the code_verifier so it can be used in the token exchange
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            isSandbox,
            codeVerifier, // PKCE: Store verifier to use in token exchange
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Salesforce expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        state: state,
        // PKCE parameters
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    const authUrl = isSandbox
        ? SALESFORCE_SANDBOX_AUTH_URL
        : SALESFORCE_AUTH_URL;
    const fullUrl = `${authUrl}?${params.toString()}`;

    return oauthRedirect(request, fullUrl);
}
