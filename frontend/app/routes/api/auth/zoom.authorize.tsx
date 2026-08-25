// Zoom OAuth authorize route.
// Redirects to Zoom's consent screen to request user authorization.
// Zoom uses standard OAuth 2.0 (authorization_code) with granular scopes.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { redirect, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';

const ZOOM_AUTH_URL = 'https://zoom.us/oauth/authorize';

// Default granular scopes. NodeCredentials pulls the canonical list from the
// credential schema's x-oauth-scopes (see backend/nodes/zoom_node.py:
// ZoomOAuthCredential) and passes it via the ?scopes= param (comma-separated) —
// this default only triggers for callers that forgot to.
const ZOOM_DEFAULT_SCOPES = [
    'meeting:read:meeting',
    'meeting:write:meeting',
    'meeting:read:list_meetings',
    'meeting:read:list_registrants',
    'meeting:write:registrant',
    'meeting:read:invitation',
    'meeting:read:past_meeting',
    'meeting:read:list_past_participants',
    'webinar:read:webinar',
    'webinar:write:webinar',
    'webinar:read:list_webinars',
    'webinar:read:list_registrants',
    'webinar:write:registrant',
    'user:read:user',
    'user:write:user',
    'user:read:list_users',
    'cloud_recording:read:list_user_recordings',
    'cloud_recording:read:list_account_recordings',
    'cloud_recording:read:list_recording_files',
    'cloud_recording:delete:meeting_recordings',
    'phone:read:list_call_logs',
    'chat_message:write:message',
].join(',');

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'zoom');
    const url = new URL(request.url);
    const scopesParam = url.searchParams.get('scopes') || ZOOM_DEFAULT_SCOPES;

    const clientId = process.env.ZOOM_CLIENT_ID;
    const redirectUri = process.env.ZOOM_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[zoom.authorize] Missing ZOOM_CLIENT_ID or ZOOM_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'zoom',
            missing: ['ZOOM_CLIENT_ID', 'ZOOM_REDIRECT_URI'],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

    // State contains metadata to pass through OAuth flow; base64url encoded so
    // it survives the URL round-trip. appOrigin records where the opener page
    // lives: Zoom requires an HTTPS redirect (a tunnel in local dev), so the
    // callback lands on a different origin and must bounce back before its
    // postMessage can reach the opener.
    const state = Buffer.from(
        JSON.stringify({
            scopes,
            appOrigin: url.origin,
            nonce: crypto.randomUUID(), // CSRF protection
            timestamp: Date.now(),
        })
    ).toString('base64url');

    // Zoom expects space-delimited scopes.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    const authUrl = `${ZOOM_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
