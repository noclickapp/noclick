// Reddit OAuth authorize route.
// Redirects to Reddit's consent screen to request user authorization.
// Reddit uses standard OAuth 2.0 flow with duration=permanent for refresh tokens.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const REDDIT_AUTH_URL = 'https://www.reddit.com/api/v1/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'reddit');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Reddit';
    const scopesParam =
        url.searchParams.get('scopes') ||
        'identity,read,submit,vote,edit,history,privatemessages,mysubreddits,save,subscribe';

    const clientId = process.env.REDDIT_CLIENT_ID;
    const redirectUri = process.env.REDDIT_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[reddit.authorize] Missing REDDIT_CLIENT_ID or REDDIT_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'reddit',
            missing: ['REDDIT_CLIENT_ID', 'REDDIT_REDIRECT_URI'],
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

    // Reddit expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        response_type: 'code',
        state: state,
        redirect_uri: redirectUri,
        duration: 'permanent', // Get refresh token for long-term access
        scope: spaceSeparatedScopes,
    });

    const authUrl = `${REDDIT_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
