// PostHog OAuth authorize route (public client + PKCE, CIMD registration).
// Generates the PKCE verifier/challenge, stashes the verifier in `state`, and
// redirects to PostHog's region-agnostic consent screen. The client_id is a CIMD
// document URL (POSTHOG_CLIENT_ID) — no client secret.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const POSTHOG_OAUTH_HOST =
    process.env.POSTHOG_OAUTH_HOST || 'https://oauth.posthog.com';

const DEFAULT_SCOPES = [
    'openid',
    'email',
    'project:read',
    'organization:read',
    'user:read',
    'insight:read',
    'insight:write',
    'dashboard:read',
    'dashboard:write',
    'feature_flag:read',
    'feature_flag:write',
    'experiment:read',
    'experiment:write',
    'query:read',
    'person:read',
    'person:write',
    'cohort:read',
    'cohort:write',
    'annotation:read',
    'annotation:write',
    'survey:read',
    'survey:write',
    'action:read',
    'action:write',
    'session_recording:read',
    'session_recording:write',
    'group:read',
    'organization_member:read',
    'organization_member:write',
    'event_definition:read',
    'property_definition:read',
    'hog_function:read',
    'hog_function:write',
    'notebook:read',
    'notebook:write',
    'early_access_feature:read',
    'early_access_feature:write',
    'batch_export:read',
    'activity_log:read',
];

function generateCodeVerifier(): string {
    return crypto.randomBytes(64).toString('base64url').slice(0, 128);
}

function generateCodeChallenge(verifier: string): string {
    return crypto.createHash('sha256').update(verifier).digest('base64url');
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'posthog');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || '';

    const clientId = process.env.POSTHOG_CLIENT_ID; // the CIMD document URL
    const redirectUri = process.env.POSTHOG_REDIRECT_URI;
    if (!clientId || !redirectUri) {
        console.error(
            '[posthog.authorize] Missing POSTHOG_CLIENT_ID or POSTHOG_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'posthog',
            missing: ['POSTHOG_CLIENT_ID', 'POSTHOG_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        ? scopesParam
              .split(' ')
              .map((s) => s.trim())
              .filter(Boolean)
        : DEFAULT_SCOPES;

    const codeVerifier = generateCodeVerifier();
    const codeChallenge = generateCodeChallenge(codeVerifier);

    // Verifier round-trips through PostHog inside `state` (base64url) so the
    // callback can hand it to the token exchange. Public client → no secret.
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            codeVerifier,
            nonce: crypto.randomUUID(),
            timestamp: Date.now(),
        })
    ).toString('base64url');

    const params = new URLSearchParams({
        response_type: 'code',
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopes.join(' '),
        state,
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
    });

    return oauthRedirect(
        request,
        `${POSTHOG_OAUTH_HOST.replace(/\/$/, '')}/oauth/authorize/?${params.toString()}`
    );
}
