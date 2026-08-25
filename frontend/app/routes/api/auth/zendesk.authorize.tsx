// Zendesk OAuth authorize route.
// Redirects to Zendesk's consent screen to request user authorization.
// Zendesk OAuth is subdomain-scoped — the authorize host is
// {subdomain}.zendesk.com — so the subdomain travels in via the ?subdomain= param
// and is carried through state for the callback + exchange.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

// Broad global scopes the Support REST API honors across endpoints. NodeCredentials
// pulls the canonical list from the credential schema's x-oauth-scopes (see
// backend/nodes/zendesk_node.py:ZendeskOAuthCredential) and passes it via the
// ?scopes= param (comma-separated) — this default only triggers for callers that
// forgot to.
const ZENDESK_DEFAULT_SCOPES = ['read', 'write'].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'zendesk');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || ZENDESK_DEFAULT_SCOPES;
    const subdomain = (url.searchParams.get('subdomain') || '')
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(/\.zendesk\.com$/, '');

    if (!subdomain) {
        console.error('[zendesk.authorize] Missing subdomain');
        throw new Response('Zendesk subdomain is required', { status: 400 });
    }

    const clientId = process.env.ZENDESK_CLIENT_ID;
    const redirectUri = process.env.ZENDESK_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[zendesk.authorize] Missing ZENDESK_CLIENT_ID or ZENDESK_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'zendesk',
            missing: ['ZENDESK_CLIENT_ID', 'ZENDESK_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip. The subdomain MUST round-trip so the
    // callback knows which Zendesk host to exchange against.
    const state = Buffer.from(
        JSON.stringify({
            subdomain,
            scopes,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Zendesk expects space-delimited scopes and a subdomain-scoped authorize host.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `https://${subdomain}.zendesk.com/oauth/authorizations/new?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
