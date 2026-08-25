// Slack OAuth authorize route.
// Redirects to Slack's consent screen to request user authorization.
// Slack uses OAuth 2.0 "Add to Slack" flow.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { type ActionFunctionArgs, type LoaderFunctionArgs } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';
import { oauthFormString, oauthPostFormData } from '~/lib/oauthPost.server';

const SLACK_AUTH_URL = 'https://slack.com/oauth/v2/authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'slack');
    const url = new URL(request.url);
    if (
        url.searchParams.has('client_id') ||
        url.searchParams.has('client_secret')
    ) {
        return new Response(
            'Custom OAuth credentials must be submitted securely. Please restart the connection.',
            { status: 400 }
        );
    }

    return startSlackOAuth(request, {
        credentialName: url.searchParams.get('name') || 'Slack',
        scopesParam:
            url.searchParams.get('scopes') ||
            'channels:read,chat:write,users:read',
        userScopesParam: url.searchParams.get('user_scopes') || 'chat:write',
        customClientId: null,
        customClientSecret: null,
    });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await oauthPostFormData(request);
    await applyInstanceOAuthEnv(request, 'slack');
    return startSlackOAuth(request, {
        credentialName: oauthFormString(formData, 'name') || 'Slack',
        scopesParam:
            oauthFormString(formData, 'scopes') ||
            'channels:read,chat:write,users:read',
        userScopesParam:
            oauthFormString(formData, 'user_scopes') || 'chat:write',
        customClientId: oauthFormString(formData, 'client_id'),
        customClientSecret: oauthFormString(formData, 'client_secret'),
    });
}

interface SlackAuthorizeInput {
    credentialName: string;
    scopesParam: string;
    userScopesParam: string;
    customClientId: string | null;
    customClientSecret: string | null;
}

async function startSlackOAuth(
    request: Request,
    {
        credentialName,
        scopesParam,
        userScopesParam,
        customClientId,
        customClientSecret,
    }: SlackAuthorizeInput
) {
    if (
        (customClientId || customClientSecret) &&
        !(customClientId && customClientSecret)
    ) {
        return new Response(
            'Enter both custom client ID and client secret, or leave both blank.',
            { status: 400 }
        );
    }

    const clientId = customClientId || process.env.SLACK_CLIENT_ID;
    const redirectUri = process.env.SLACK_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[slack.authorize] Missing client ID or SLACK_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'slack',
            missing: ['SLACK_CLIENT_ID', 'SLACK_REDIRECT_URI'],
        });
    }

    // oauthRedirect encrypts and browser-binds this state before it leaves the
    // application, so custom credentials are opaque on the provider redirect.
    const stateData: Record<string, unknown> = {
        credentialName,
        scopes: scopesParam.split(','),
        nonce: crypto.randomUUID(), // CSRF protection
        timestamp: Date.now(),
        // Store the origin of the app so the callback can relay back to the same origin
        // if SLACK_REDIRECT_URI is on a different origin (e.g. ngrok in development).
        mainOrigin: new URL(request.url).origin,
    };

    if (customClientId && customClientSecret) {
        stateData.customClientId = customClientId;
        stateData.customClientSecret = customClientSecret;
    }

    const state = Buffer.from(JSON.stringify(stateData)).toString('base64url');

    // Slack expects comma-separated scopes for bot tokens. user_scope is the
    // sibling param that triggers an authed_user xoxp- token in the response.
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopesParam,
        user_scope: userScopesParam,
        state: state,
    });

    const authUrl = `${SLACK_AUTH_URL}?${params.toString()}`;

    return oauthRedirect(request, authUrl);
}
