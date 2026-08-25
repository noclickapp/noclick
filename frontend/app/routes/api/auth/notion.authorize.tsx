// Notion OAuth authorize route.
// Redirects to Notion's consent screen to request user authorization.
// Notion uses standard OAuth 2.0 flow (no PKCE required).

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const NOTION_AUTH_URL = 'https://api.notion.com/v1/oauth/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'notion');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Notion';

    const clientId = process.env.NOTION_CLIENT_ID;
    const redirectUri = process.env.NOTION_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[notion.authorize] Missing NOTION_CLIENT_ID or NOTION_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'notion',
            missing: ['NOTION_CLIENT_ID', 'NOTION_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        owner: 'user', // Required by Notion
        state: state,
    });

    const authUrl = `${NOTION_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
