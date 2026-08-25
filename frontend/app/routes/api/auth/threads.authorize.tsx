// Threads OAuth authorize route.
// Redirects to Threads' consent screen (threads.net). Threads uses its OWN OAuth
// app + tokens (distinct from Facebook/Instagram Graph); scopes are comma-separated.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const THREADS_AUTH_URL = 'https://threads.net/oauth/authorize';

const THREADS_DEFAULT_SCOPES = [
    'threads_basic',
    'threads_content_publish',
    'threads_read_replies',
    'threads_manage_replies',
    'threads_manage_insights',
    'threads_manage_mentions',
    'threads_keyword_search',
    'threads_location_tagging',
    'threads_delete',
    'threads_profile_discovery',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'threads');
    const url = new URL(request.url);
    const scopesParam =
        url.searchParams.get('scopes') || THREADS_DEFAULT_SCOPES;

    const clientId = process.env.THREADS_CLIENT_ID;
    const redirectUri = process.env.THREADS_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[threads.authorize] Missing THREADS_CLIENT_ID or THREADS_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'threads',
            missing: ['THREADS_CLIENT_ID', 'THREADS_REDIRECT_URI'],
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

    return oauthRedirect(request, `${THREADS_AUTH_URL}?${params.toString()}`);
}
