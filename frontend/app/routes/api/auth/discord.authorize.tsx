// Discord OAuth authorize route.
// Redirects to Discord's consent screen to request user authorization.
// Discord uses standard OAuth 2.0 flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const DISCORD_AUTH_URL = 'https://discord.com/oauth2/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'discord');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Discord';
    const scopesParam =
        url.searchParams.get('scopes') || 'identify,email,guilds';

    const clientId = process.env.DISCORD_CLIENT_ID;
    const redirectUri = process.env.DISCORD_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[discord.authorize] Missing DISCORD_CLIENT_ID or DISCORD_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'discord',
            missing: ['DISCORD_CLIENT_ID', 'DISCORD_REDIRECT_URI'],
        });
    }

    // State contains metadata to pass through OAuth flow
    // We base64 encode it to safely pass through URL
    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const scopeList = scopesParam.split(',');
    const isBotInstall = scopeList.includes('bot');

    // Discord expects space-separated scopes
    const spaceSeparatedScopes = scopeList.join(' ');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: spaceSeparatedScopes,
        state: state,
    });

    // Bot installs require a permissions bitmask so Discord shows guild selection.
    // 0x8 = Administrator; adjust to least-privilege as needed.
    if (isBotInstall) {
        params.set('permissions', '8');
    }

    const authUrl = `${DISCORD_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
