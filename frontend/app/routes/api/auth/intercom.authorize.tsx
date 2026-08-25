// Intercom OAuth authorize route.
// Redirects to Intercom's consent screen to request user authorization.
// Intercom uses standard OAuth 2.0 (authorization_code). The authorize endpoint
// takes ONLY client_id + state (no scope param — scopes are fixed per app in the
// Developer Hub).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const INTERCOM_AUTH_URL = 'https://app.intercom.com/oauth';

// Informational default scopes. Intercom does NOT accept a scope URL param —
// scopes are enabled per app in the Developer Hub. NodeCredentials still passes
// the credential schema's x-oauth-scopes via ?scopes= so the exchange request
// can record which permissions the app was configured with.
const INTERCOM_DEFAULT_SCOPES = [
    'read_write_users',
    'read_write_companies',
    'read_write_conversations',
    'read_write_tags',
    'read_write_events',
    'read_write_tickets',
    'read_admins',
    'read_teams',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'intercom');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || INTERCOM_DEFAULT_SCOPES;
    const region = url.searchParams.get('region') || 'us';

    const clientId = process.env.INTERCOM_CLIENT_ID;
    const redirectUri = process.env.INTERCOM_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[intercom.authorize] Missing INTERCOM_CLIENT_ID or INTERCOM_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'intercom',
            missing: ['INTERCOM_CLIENT_ID', 'INTERCOM_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State carries metadata through the OAuth flow; base64url encoded so it
    // survives the URL round-trip.
    // appOrigin records where the opener page lives so the callback can bounce
    // back if the registered redirect lands on a different origin/port —
    // cross-origin postMessage never reaches the opener.
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            region,
            appOrigin: url.origin,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Intercom's authorize endpoint takes client_id + state only (plus an
    // optional redirect_uri to pick among the app's registered redirect URLs).
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        state,
    });

    const authUrl = `${INTERCOM_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
