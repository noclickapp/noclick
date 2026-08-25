// Calendly OAuth authorize route.
// Redirects to Calendly's consent screen (auth.calendly.com) to request user
// authorization. Standard OAuth 2.0 with a shared NoClick app.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const CALENDLY_AUTH_URL = 'https://auth.calendly.com/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'calendly');
    const url = new URL(request.url);
    // Calendly scopes: the factory passes space-delimited scopes via ?scopes=,
    // but the default is empty — Calendly's 2026 granular-scope strings aren't
    // publicly documented, so the registered app's access governs. Only send a
    // scope param when explicit scopes are supplied.
    const scopesParam = url.searchParams.get('scopes') || '';

    const clientId = process.env.CALENDLY_CLIENT_ID;
    const redirectUri = process.env.CALENDLY_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[calendly.authorize] Missing CALENDLY_CLIENT_ID or CALENDLY_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'calendly',
            missing: ['CALENDLY_CLIENT_ID', 'CALENDLY_REDIRECT_URI'],
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

    return oauthRedirect(request, `${CALENDLY_AUTH_URL}?${params.toString()}`);
}
