// Box OAuth authorize route.
// Redirects to Box's consent screen to request user authorization.
// Box uses standard OAuth 2.0 (Authorization Code). Scopes are configured on the
// Box app in the Developer Console, so the scope param is optional at authorize
// time — we pass it (space-delimited) for parity with other providers.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const BOX_AUTH_URL = 'https://account.box.com/api/oauth2/authorize';

// Canonical scope set. NodeCredentials pulls the list from the credential
// schema's x-oauth-scopes (see backend/nodes/box_node.py:BoxOAuthCredential) and
// passes it via the ?scopes= param (comma-separated) — this default only
// triggers for callers that forgot to.
const BOX_DEFAULT_SCOPES = [
    'root_readwrite',
    'manage_managed_users',
    'manage_groups',
    'manage_webhook',
    'manage_enterprise_properties',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'box');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || BOX_DEFAULT_SCOPES;

    const clientId = process.env.BOX_CLIENT_ID;
    const redirectUri = process.env.BOX_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[box.authorize] Missing BOX_CLIENT_ID or BOX_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'box',
            missing: ['BOX_CLIENT_ID', 'BOX_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip.
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
    // Box scopes are configured on the app; include them only when present.
    if (scopes.length) {
        params.set('scope', scopes.join(' '));
    }

    const authUrl = `${BOX_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
