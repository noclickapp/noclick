// Instagram Login OAuth authorize route (Instagram API *with Instagram Login*).
// Redirects to Instagram's own consent screen (instagram.com) — NO Facebook
// account or Page required. Uses the Instagram App ID/Secret (distinct from the
// Facebook App ID) and the instagram_business_* scope family; comma-separated.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const INSTAGRAM_AUTH_URL = 'https://www.instagram.com/oauth/authorize';

const INSTAGRAM_DEFAULT_SCOPES = [
    'instagram_business_basic',
    'instagram_business_content_publish',
    'instagram_business_manage_comments',
    'instagram_business_manage_messages',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'instagram');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || INSTAGRAM_DEFAULT_SCOPES;

    const clientId = process.env.INSTAGRAM_APP_ID;
    const redirectUri = process.env.INSTAGRAM_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[instagram.authorize] Missing INSTAGRAM_APP_ID or INSTAGRAM_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'instagram',
            missing: ['INSTAGRAM_APP_ID', 'INSTAGRAM_REDIRECT_URI'],
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

    return oauthRedirect(request, `${INSTAGRAM_AUTH_URL}?${params.toString()}`);
}
