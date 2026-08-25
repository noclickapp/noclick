// Webflow OAuth authorize route.
// Redirects to Webflow's consent screen to request user authorization.
// Webflow uses standard OAuth 2.0 (authorization_code) with space-delimited scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const WEBFLOW_AUTH_URL = 'https://webflow.com/oauth/authorize';

// Default scopes. NodeCredentials pulls the canonical list from the credential
// schema's x-oauth-scopes (see backend/nodes/webflow_node.py:WebflowOAuthCredential)
// and passes it via the ?scopes= param (comma-separated) — this default only
// triggers for callers that forgot to.
const WEBFLOW_DEFAULT_SCOPES = [
    'sites:read',
    'sites:write',
    'cms:read',
    'cms:write',
    'pages:read',
    'pages:write',
    'forms:read',
    'forms:write',
    'assets:read',
    'assets:write',
    'ecommerce:read',
    'ecommerce:write',
    'authorized_user:read',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'webflow');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || WEBFLOW_DEFAULT_SCOPES;

    const clientId = process.env.WEBFLOW_CLIENT_ID;
    const redirectUri = process.env.WEBFLOW_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[webflow.authorize] Missing WEBFLOW_CLIENT_ID or WEBFLOW_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'webflow',
            missing: ['WEBFLOW_CLIENT_ID', 'WEBFLOW_REDIRECT_URI'],
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

    // Webflow expects space-delimited scopes.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `${WEBFLOW_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
