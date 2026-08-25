// Typeform OAuth authorize route.
// Redirects to Typeform's consent screen to request user authorization.
// Typeform uses standard OAuth 2.0 Authorization Code Flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const TYPEFORM_AUTH_URL = 'https://api.typeform.com/oauth/authorize';

// Default Typeform OAuth scopes.
// Note: 'offline' is excluded — it only works with standard OAuth apps. NoClick's
// registered Typeform app rejects token exchange with "this kind of access tokens
// cannot have refresh tokens" if 'offline' is requested. Do not re-add it
// (regression ).
const DEFAULT_TYPEFORM_SCOPES = [
    'accounts:read',
    'forms:read',
    'forms:write',
    'images:read',
    'images:write',
    'themes:read',
    'themes:write',
    'responses:read',
    'responses:write',
    'webhooks:read',
    'webhooks:write',
    'workspaces:read',
    'workspaces:write',
].join(' ');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'typeform');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Typeform';
    const scopesParam =
        url.searchParams.get('scopes') || DEFAULT_TYPEFORM_SCOPES;

    const clientId = process.env.TYPEFORM_CLIENT_ID?.trim();
    const redirectUri = process.env.TYPEFORM_REDIRECT_URI?.trim();

    if (!clientId || !redirectUri) {
        console.error(
            '[typeform.authorize] Missing TYPEFORM_CLIENT_ID or TYPEFORM_REDIRECT_URI env var'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'typeform',
            missing: ['TYPEFORM_CLIENT_ID', 'TYPEFORM_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopesParam.replace(/,/g, ' '), // Typeform uses space-delimited scopes
        state: state,
    });

    const fullUrl = `${TYPEFORM_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, fullUrl);
}
