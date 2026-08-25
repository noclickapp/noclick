import { oauthRedirect } from '~/lib/oauthFlow.server';
import crypto from 'crypto';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const FATHOM_AUTH_URL = 'https://fathom.video/external/v1/oauth2/authorize';
const DEFAULT_FATHOM_SCOPES = 'public_api';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'fathom');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Fathom';
    const scopesParam = url.searchParams.get('scopes') || DEFAULT_FATHOM_SCOPES;

    const clientId = process.env.FATHOM_CLIENT_ID?.trim();
    const redirectUri =
        process.env.FATHOM_REDIRECT_URI?.trim() ||
        `${url.origin}/api/auth/fathom/callback`;

    if (!clientId) {
        console.error('[fathom.authorize] Missing FATHOM_CLIENT_ID env var');
        return oauthNotConfiguredResponse({
            request,
            provider: 'fathom',
            missing: ['FATHOM_CLIENT_ID', 'FATHOM_REDIRECT_URI'],
        });
    }

    const state = Buffer.from(
        JSON.stringify({
            credentialName,
            scopes: scopesParam.split(','),
            mainOrigin: url.origin,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopesParam.split(',').join(' '),
        state,
        response_type: 'code',
    });

    return oauthRedirect(request, `${FATHOM_AUTH_URL}?${params.toString()}`);
}
