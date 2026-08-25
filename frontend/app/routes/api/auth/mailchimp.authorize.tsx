// Mailchimp OAuth authorize route.
// Redirects to Mailchimp's consent screen to request user authorization.
// Mailchimp uses standard OAuth 2.0 Web Server Flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const MAILCHIMP_AUTH_URL = 'https://login.mailchimp.com/oauth2/authorize';

// Default Mailchimp OAuth scopes
const DEFAULT_MAILCHIMP_SCOPES = ['marketing:read', 'marketing:write'].join(
    ','
);

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'mailchimp');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Mailchimp';
    const scopesParam =
        url.searchParams.get('scopes') || DEFAULT_MAILCHIMP_SCOPES;

    const clientId = process.env.MAILCHIMP_CLIENT_ID?.trim();
    const redirectUri = process.env.MAILCHIMP_REDIRECT_URI?.trim();

    if (!clientId || !redirectUri) {
        console.error(
            '[mailchimp.authorize] Missing MAILCHIMP_CLIENT_ID or MAILCHIMP_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'mailchimp',
            missing: ['MAILCHIMP_CLIENT_ID', 'MAILCHIMP_REDIRECT_URI'],
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
        response_type: 'code',
        state: state,
    });

    const fullUrl = `${MAILCHIMP_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, fullUrl);
}
