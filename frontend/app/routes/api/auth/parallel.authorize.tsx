// Parallel OAuth authorize route with PKCE (S256).
// Redirects to Parallel's consent screen to retrieve the user's API key.
// No client_secret — Parallel uses public PKCE clients identified by hostname.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const PARALLEL_AUTH_URL = 'https://platform.parallel.ai/getKeys/authorize';

function generateCodeVerifier(): string {
    return crypto.randomBytes(64).toString('base64url').slice(0, 128);
}

function generateCodeChallenge(verifier: string): string {
    return crypto.createHash('sha256').update(verifier).digest('base64url');
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    // Unlike the other providers this one still works unconfigured (public PKCE
    // client), but a self-hoster should be able to identify as themselves.
    await applyInstanceOAuthEnv(request, 'parallel');

    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Parallel';

    const clientId = (process.env.PARALLEL_CLIENT_ID || url.hostname).trim();
    const redirectUri = `${new URL(request.url).origin}/api/auth/parallel/callback`;

    const codeVerifier = generateCodeVerifier();
    const codeChallenge = generateCodeChallenge(codeVerifier);

    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            codeVerifier,
            redirectUri,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: 'key:read',
        state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    return oauthRedirect(request, `${PARALLEL_AUTH_URL}?${params.toString()}`);
}
