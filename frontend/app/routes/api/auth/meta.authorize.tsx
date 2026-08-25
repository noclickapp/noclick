// Meta (Marketing / Ads / Business) OAuth authorize route.
// Redirects to the Facebook Login consent dialog (facebook.com). Meta uses the
// same Facebook Login OAuth as the Facebook node but requests ads/business
// scopes; scopes are comma-separated.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const META_AUTH_URL = 'https://www.facebook.com/v25.0/dialog/oauth';

const META_DEFAULT_SCOPES = [
    'public_profile',
    'ads_management',
    'ads_read',
    'business_management',
    'leads_retrieval',
    'pages_show_list',
    'pages_read_engagement',
    'catalog_management',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'meta');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || META_DEFAULT_SCOPES;

    const clientId = process.env.META_APP_ID;
    const redirectUri = process.env.META_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[meta.authorize] Missing META_APP_ID or META_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'meta',
            missing: ['META_APP_ID', 'META_REDIRECT_URI'],
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

    return oauthRedirect(request, `${META_AUTH_URL}?${params.toString()}`);
}
