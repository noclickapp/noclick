// Cal.com OAuth authorize route.
// Redirects to Cal.com's consent screen to request user authorization.
// Cal.com uses standard OAuth 2.0 (authorization-code) flow with space-separated scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const CALCOM_AUTH_URL = 'https://app.cal.com/auth/oauth2/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'calcom');
    const url = new URL(request.url);
    // NodeCredentials passes the canonical scopes from the credential schema's
    // x-oauth-scopes (see backend/nodes/cal_com_node.py:CalComOAuthCredential)
    // via ?scopes= (comma-separated). This default only triggers for callers
    // that forgot to pass any.
    const scopesParam =
        url.searchParams.get('scopes') ||
        'BOOKING_READ,BOOKING_WRITE,EVENT_TYPE_READ,EVENT_TYPE_WRITE,SCHEDULE_READ,SCHEDULE_WRITE,PROFILE_READ,PROFILE_WRITE,WEBHOOK_READ,WEBHOOK_WRITE';

    const clientId = process.env.CALCOM_CLIENT_ID;
    const redirectUri = process.env.CALCOM_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[calcom.authorize] Missing CALCOM_CLIENT_ID or CALCOM_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'calcom',
            missing: ['CALCOM_CLIENT_ID', 'CALCOM_REDIRECT_URI'],
        });
    }

    const state = Buffer.from(
        JSON.stringify({
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Cal.com expects space-separated scopes (comma is also accepted).
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopesParam.split(',').join(' '),
        state: state,
    });

    return oauthRedirect(request, `${CALCOM_AUTH_URL}?${params.toString()}`);
}
