// Atlassian OAuth authorize route.
// Redirects to Atlassian's consent screen to request user authorization.
// Atlassian uses standard OAuth 2.0 (3LO) flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { encodeAtlassianOAuthState } from '~/utils/atlassianOAuthState.server';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const ATLASSIAN_AUTH_URL = 'https://auth.atlassian.com/authorize';
// Fallback only — the caller normally forwards the credential schema's
// x-oauth-scopes, derived from backend/nodes/scopes/jira.py. Keep in sync.
const DEFAULT_ATLASSIAN_SCOPES = [
    'read:jira-work',
    'write:jira-work',
    'read:jira-user',
    'manage:jira-project',
    'manage:jira-configuration',
    'manage:jira-webhook',
    'read:project:jira',
    'read:issue-details:jira',
    'read:jql:jira',
    'read:board-scope:jira-software',
    'read:sprint:jira-software',
    'write:sprint:jira-software',
    'delete:sprint:jira-software',
    'read:epic:jira-software',
    'write:epic:jira-software',
    'offline_access',
];

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'atlassian');
    const url = new URL(request.url);
    const credentialName = url.searchParams.get('name') || 'Jira';
    const scopesParam =
        url.searchParams.get('scopes') || DEFAULT_ATLASSIAN_SCOPES.join(',');
    const jiraSite = url.searchParams.get('jiraSite') || '';

    const clientId = process.env.ATLASSIAN_CLIENT_ID;
    const redirectUri =
        process.env.ATLASSIAN_REDIRECT_URI ||
        `${url.origin}/api/auth/atlassian/callback`;

    if (!clientId) {
        console.error(
            '[atlassian.authorize] Missing ATLASSIAN_CLIENT_ID env var'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'atlassian',
            missing: ['ATLASSIAN_CLIENT_ID', 'ATLASSIAN_REDIRECT_URI'],
        });
    }

    // State carries the opener origin so callbacks still reach the editor when
    // Atlassian redirects to a configured callback on a different host.
    let state: string;
    try {
        state = encodeAtlassianOAuthState({
            credentialName,
            scopes: scopesParam.split(','),
            jiraSite,
            appOrigin: url.origin,
            redirectUri,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        });
    } catch (e) {
        console.error('[atlassian.authorize] Failed to encode OAuth state:', e);
        return oauthNotConfiguredResponse({
            request,
            provider: 'atlassian',
            missing: ['ATLASSIAN_CLIENT_ID', 'ATLASSIAN_REDIRECT_URI'],
        });
    }

    // Atlassian expects space-separated scopes
    const spaceSeparatedScopes = scopesParam.split(',').join(' ');

    const params = new URLSearchParams({
        audience: 'api.atlassian.com',
        client_id: clientId,
        scope: spaceSeparatedScopes,
        redirect_uri: redirectUri,
        state: state,
        response_type: 'code',
        prompt: 'consent',
    });

    const authUrl = `${ATLASSIAN_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
