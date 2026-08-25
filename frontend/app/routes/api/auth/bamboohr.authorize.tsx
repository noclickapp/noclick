// BambooHR OAuth authorize route.
// Redirects to BambooHR's consent screen. BambooHR OAuth is subdomain-scoped —
// the authorize host is {subdomain}.bamboohr.com — so the subdomain travels in
// via the ?subdomain= param and is carried through state for the callback +
// exchange. BambooHR requires request=authorize and plus/space-delimited scopes;
// offline_access is needed to receive a refresh token.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

// NodeCredentials pulls the canonical scope list from the credential schema's
// x-oauth-scopes (backend/nodes/bamboohr_node.py:BambooHROAuthCredential) and
// passes it via ?scopes=; this default only triggers for callers that forgot to.
const BAMBOOHR_DEFAULT_SCOPES = ['openid', 'offline_access'].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'bamboohr');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || BAMBOOHR_DEFAULT_SCOPES;
    const subdomain = (url.searchParams.get('subdomain') || '')
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(/\.bamboohr\.com$/, '');

    if (!subdomain) {
        console.error('[bamboohr.authorize] Missing subdomain');
        throw new Response('BambooHR company subdomain is required', {
            status: 400,
        });
    }

    const clientId = process.env.BAMBOOHR_CLIENT_ID;
    const redirectUri = process.env.BAMBOOHR_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[bamboohr.authorize] Missing BAMBOOHR_CLIENT_ID or BAMBOOHR_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'bamboohr',
            missing: ['BAMBOOHR_CLIENT_ID', 'BAMBOOHR_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State must round-trip the subdomain so the callback knows which BambooHR
    // host to exchange against. base64url-encoded to survive the URL round-trip.
    const state = Buffer.from(
        JSON.stringify({
            subdomain,
            scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        request: 'authorize',
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `https://${subdomain}.bamboohr.com/authorize.php?${params.toString()}`;
    return oauthRedirect(request, authUrl);
}
