// monday.com OAuth authorize route.
// Redirects to monday's consent screen to request user authorization.
// monday uses standard OAuth 2.0 (authorization_code) with space-delimited scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const MONDAY_AUTH_URL = 'https://auth.monday.com/oauth2/authorize';

// Default scopes. NodeCredentials pulls the canonical list from the credential
// schema's x-oauth-scopes (see backend/nodes/monday_node.py:MondayOAuthCredential)
// and passes it via the ?scopes= param (comma-separated) — this default only
// triggers for callers that forgot to.
const MONDAY_DEFAULT_SCOPES = [
    'account:read',
    'boards:read',
    'boards:write',
    'docs:read',
    'docs:write',
    'workspaces:read',
    'workspaces:write',
    'users:read',
    'users:write',
    'teams:read',
    'teams:write',
    'updates:read',
    'updates:write',
    'notifications:write',
    'webhooks:read',
    'webhooks:write',
    'assets:read',
    'tags:read',
    'me:read',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'monday');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || MONDAY_DEFAULT_SCOPES;

    const clientId = process.env.MONDAY_CLIENT_ID;
    const redirectUri = process.env.MONDAY_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[monday.authorize] Missing MONDAY_CLIENT_ID or MONDAY_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'monday',
            missing: ['MONDAY_CLIENT_ID', 'MONDAY_REDIRECT_URI'],
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

    // monday expects space-delimited scopes.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `${MONDAY_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
