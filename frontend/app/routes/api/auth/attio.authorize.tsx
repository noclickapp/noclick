// Attio OAuth authorize route.
// Redirects to Attio's consent screen to request user authorization.
// Attio uses standard OAuth 2.0 flow with space-separated scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const ATTIO_AUTH_URL = 'https://app.attio.com/authorize';

// Default scopes if the caller didn't pass any. NodeCredentials pulls the
// canonical list from the credential schema's x-oauth-scopes and passes it via
// the ?scopes= param — this default only triggers for callers that forgot to.
const DEFAULT_SCOPES =
    'record_permission:read-write object_configuration:read-write list_entry:read-write list_configuration:read-write user_management:read comment:read-write task:read-write note:read-write webhook:read-write file:read';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'attio');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || DEFAULT_SCOPES;

    const clientId = process.env.ATTIO_CLIENT_ID;
    const redirectUri = process.env.ATTIO_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[attio.authorize] Missing ATTIO_CLIENT_ID or ATTIO_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'attio',
            missing: ['ATTIO_CLIENT_ID', 'ATTIO_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            scopes: scopesParam.split(' '),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Attio expects space-separated scopes
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopesParam,
        state: state,
        prompt: 'consent', // Always show consent screen
    });

    const authUrl = `${ATTIO_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
