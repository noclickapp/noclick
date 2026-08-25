// Sentry OAuth authorize route.
// Redirects to Sentry's consent screen (sentry.io/oauth/authorize) to request
// user authorization. Standard OAuth 2.0 with a shared NoClick app.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const SENTRY_AUTH_URL = 'https://sentry.io/oauth/authorize/';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'sentry');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || '';

    const clientId = process.env.SENTRY_CLIENT_ID;
    const redirectUri = process.env.SENTRY_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[sentry.authorize] Missing SENTRY_CLIENT_ID or SENTRY_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'sentry',
            missing: ['SENTRY_CLIENT_ID', 'SENTRY_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(' ')
        .map((s) => s.trim())
        .filter(Boolean);

    const state = Buffer.from(
        JSON.stringify({
            scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        state,
    });
    if (scopes.length) {
        params.set('scope', scopes.join(' '));
    }

    return oauthRedirect(request, `${SENTRY_AUTH_URL}?${params.toString()}`);
}
