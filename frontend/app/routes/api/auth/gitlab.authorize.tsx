// GitLab OAuth authorize route.
// Redirects to GitLab's consent screen to request user authorization.
// GitLab uses standard OAuth 2.0 (authorization_code) with space-delimited scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const GITLAB_AUTH_URL = 'https://gitlab.com/oauth/authorize';

// Default scopes. NodeCredentials pulls the canonical list from the credential
// schema's x-oauth-scopes (see backend/nodes/gitlab_node.py:GitLabOAuthCredential)
// and passes it via the ?scopes= param (comma-separated) — this default only
// triggers for callers that forgot to.
const GITLAB_DEFAULT_SCOPES = ['api', 'read_user'].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'gitlab');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || GITLAB_DEFAULT_SCOPES;

    const clientId = process.env.GITLAB_CLIENT_ID;
    const redirectUri = process.env.GITLAB_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[gitlab.authorize] Missing GITLAB_CLIENT_ID or GITLAB_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'gitlab',
            missing: ['GITLAB_CLIENT_ID', 'GITLAB_REDIRECT_URI'],
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

    // GitLab expects space-delimited scopes.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `${GITLAB_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
