// Facebook Pages OAuth authorize route.
// Redirects to Facebook Login requesting Pages + Messaging scopes. Distinct from
// the Instagram-focused `facebook` provider — this mints a facebook_oauth
// credential for the Facebook (Pages + Messenger) node.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const FB_AUTH_URL = 'https://www.facebook.com/v25.0/dialog/oauth';

const FB_PAGES_DEFAULT_SCOPES = [
    'public_profile',
    'email',
    'pages_show_list',
    'pages_read_engagement',
    'pages_read_user_content',
    'pages_manage_posts',
    'pages_manage_engagement',
    'pages_manage_metadata',
    'pages_messaging',
    'read_insights',
    'business_management',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'facebook_pages');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || FB_PAGES_DEFAULT_SCOPES;

    const clientId = process.env.FACEBOOK_APP_ID;
    const redirectUri = process.env.FACEBOOK_PAGES_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[facebook_pages.authorize] Missing FACEBOOK_APP_ID or FACEBOOK_PAGES_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'facebook_pages',
            missing: ['FACEBOOK_APP_ID', 'FACEBOOK_PAGES_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(','),
        state,
    });
    return oauthRedirect(request, `${FB_AUTH_URL}?${params.toString()}`);
}
