// Microsoft OAuth authorize route.
// Redirects to Microsoft's consent screen with the requested scopes.
// Works with Microsoft Graph API (Outlook, OneDrive, etc.) - just pass different scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { type LoaderFunctionArgs } from 'react-router';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

// Microsoft OAuth endpoints (using common tenant for multi-tenant apps)
const MICROSOFT_AUTH_URL =
    'https://login.microsoftonline.com/common/oauth2/v2.0/authorize';
// Tenant-wide grant. `organizations`, never `common`: personal accounts have no
// directory to consent for, and Microsoft rejects admin consent through common.
const MICROSOFT_ADMIN_CONSENT_URL =
    'https://login.microsoftonline.com/organizations/v2.0/adminconsent';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'microsoft');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Microsoft Account';
    const scopes =
        url.searchParams.get('scopes') ||
        'https://graph.microsoft.com/Mail.Read,https://graph.microsoft.com/Mail.Send';
    const orgConsent = url.searchParams.get('admin_consent') === '1';

    const clientId = process.env.MICROSOFT_CLIENT_ID;
    const redirectUri = process.env.MICROSOFT_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[microsoft.authorize] Missing MICROSOFT_CLIENT_ID or MICROSOFT_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'microsoft',
            missing: ['MICROSOFT_CLIENT_ID', 'MICROSOFT_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopes.split(','),
            adminConsent: orgConsent,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Microsoft expects space-separated scopes, but we receive comma-separated
    // Always include offline_access for refresh tokens and openid for user identity
    const allScopes = [
        ...new Set([
            ...scopes.split(','),
            'offline_access',
            'openid',
            'profile',
            'email',
        ]),
    ];
    const spaceSeparatedScopes = allScopes.join(' ');

    if (orgConsent) {
        // An admin approves these permissions for every user in the directory.
        // Microsoft returns no code from this endpoint — the callback chains a
        // granted consent into the normal sign-in so the admin ends up connected too.
        const params = new URLSearchParams({
            client_id: clientId,
            redirect_uri: redirectUri,
            scope: spaceSeparatedScopes,
            state,
        });
        return oauthRedirect(
            request,
            `${MICROSOFT_ADMIN_CONSENT_URL}?${params.toString()}`
        );
    }

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        response_mode: 'query',
        prompt: 'consent', // Always show consent to ensure we get refresh token
        state: state,
    });

    const authUrl = `${MICROSOFT_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
