// Supabase Management API OAuth authorize route with PKCE.
// Redirects to Supabase's consent screen to request Management API access.
// The user's project URL is accepted as a query param and encoded in state so
// the callback can pass it to the backend for API key retrieval.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const SUPABASE_AUTH_URL = 'https://api.supabase.com/v1/oauth/authorize';

function generateCodeVerifier(): string {
    return crypto.randomBytes(64).toString('base64url').slice(0, 128);
}

function generateCodeChallenge(verifier: string): string {
    return crypto.createHash('sha256').update(verifier).digest('base64url');
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'supabase');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Supabase';

    const clientId = process.env.SUPABASE_CLIENT_ID?.trim();
    const redirectUri = process.env.SUPABASE_REDIRECT_URI?.trim();

    if (!clientId || !redirectUri) {
        console.error(
            '[supabase.authorize] Missing SUPABASE_CLIENT_ID or SUPABASE_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'supabase',
            missing: ['SUPABASE_CLIENT_ID', 'SUPABASE_REDIRECT_URI'],
        });
    }

    const codeVerifier = generateCodeVerifier();
    const codeChallenge = generateCodeChallenge(codeVerifier);

    // Encode PKCE verifier and credential name in state (no project URL needed — backend lists projects post-exchange)
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            codeVerifier,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: 'projects:read secrets:read database:read database:write auth:read auth:write storage:read storage:write edge_functions:read edge_functions:write',
        state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    return oauthRedirect(request, `${SUPABASE_AUTH_URL}?${params.toString()}`);
}
