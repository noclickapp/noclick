// Twitter/X OAuth authorize route.
// Redirects to Twitter's consent screen to request user authorization.
// Twitter uses OAuth 2.0 with PKCE flow for enhanced security.
//
// PKCE design: codeVerifier is embedded in the state parameter (base64url-encoded JSON).
// Without the scopes array the state is ~230 chars, well under X's 500-char limit.
// Scopes are stored separately in the opener hook (useTwitterOAuth) via a ref.

import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthRedirect } from '~/lib/oauthFlow.server';

const X_AUTH_URL = 'https://x.com/i/oauth2/authorize';

// Default scopes for free-tier X API access.
// Higher-tier scopes (bookmark.*, block.*, mute.*, list.*, dm.*, space.*) require
// Basic or Elevated API access and must be explicitly requested by nodes that need them.
const DEFAULT_SCOPES =
    'tweet.read,tweet.write,users.read,offline.access,like.read,like.write,follows.read,follows.write';

function generatePKCE() {
    const codeVerifier = crypto.randomBytes(32).toString('base64url');
    const codeChallenge = crypto
        .createHash('sha256')
        .update(codeVerifier)
        .digest('base64url');
    return { codeVerifier, codeChallenge };
}

export async function loader({ request }: LoaderFunctionArgs) {
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Twitter';
    const scopesParam = url.searchParams.get('scopes') || DEFAULT_SCOPES;
    const clientId = process.env.X_CLIENT_ID;
    const redirectUri = process.env.X_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[x.authorize] Missing X_CLIENT_ID or X_REDIRECT_URI env vars'
        );
        throw new Response('Twitter OAuth not configured', { status: 500 });
    }

    const { codeVerifier, codeChallenge } = generatePKCE();

    // State carries metadata + codeVerifier. X enforces a 500-char limit, but
    // without the scopes array the encoded state is ~230 chars — well under the limit.
    // Scopes are passed separately as a query param and are already in the OAuth request.
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
            codeVerifier,
        })
    ).toString('base64url');

    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: spaceSeparatedScopes,
        state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    const authUrl = `${X_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
