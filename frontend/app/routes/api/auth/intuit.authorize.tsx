// QuickBooks (Intuit) OAuth authorize route.
// Redirects to Intuit's consent screen to request user authorization.
// Uses a short-lived HttpOnly cookie to bind the callback to the initiating tab.
// The whole flow lives under /api/auth/intuit/* because that is the redirect URI
// registered on the Intuit developer app.

import { oauthRedirect } from '~/lib/oauthFlow.server';
import {
    createCookie,
    type ActionFunctionArgs,
    type LoaderFunctionArgs,
} from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';
import { oauthFormString, oauthPostFormData } from '~/lib/oauthPost.server';
import { serializeForInlineScript } from '~/lib/inlineScript.server';

const QUICKBOOKS_AUTH_URL = 'https://appcenter.intuit.com/connect/oauth2';

const intuitOAuthStateCookie = createCookie('intuit_oauth_state', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/api/auth/intuit',
    maxAge: 600,
});

const QUICKBOOKS_DEFAULT_SCOPES = [
    'com.intuit.quickbooks.accounting',
    'openid',
    'profile',
    'email',
].join(',');

function popupErrorHtml(message: string): string {
    const payload = serializeForInlineScript({
        type: 'quickbooks-oauth-callback',
        success: false,
        error: message,
    });
    return `<!doctype html><html><body><script>
if (window.opener) {
  window.opener.postMessage(${payload}, window.location.origin);
}
window.close();
</script></body></html>`;
}

export async function loader({ request }: LoaderFunctionArgs) {
    // Self-hosted: an OAuth app saved in Settings shows up as env vars here.
    await applyInstanceOAuthEnv(request, 'intuit');
    const url = new URL(request.url);
    if (
        url.searchParams.has('customClientId') ||
        url.searchParams.has('customClientSecret')
    ) {
        return new Response(
            popupErrorHtml(
                'Custom OAuth credentials must be submitted securely. Please restart the connection.'
            ),
            {
                status: 400,
                headers: { 'Content-Type': 'text/html; charset=utf-8' },
            }
        );
    }

    return startIntuitOAuth(request, {
        scopesParam:
            url.searchParams.get('scopes') || QUICKBOOKS_DEFAULT_SCOPES,
        customClientId: null,
        customClientSecret: null,
    });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await oauthPostFormData(request);
    await applyInstanceOAuthEnv(request, 'intuit');
    return startIntuitOAuth(request, {
        scopesParam:
            oauthFormString(formData, 'scopes') || QUICKBOOKS_DEFAULT_SCOPES,
        customClientId: oauthFormString(formData, 'customClientId'),
        customClientSecret: oauthFormString(formData, 'customClientSecret'),
    });
}

interface IntuitAuthorizeInput {
    scopesParam: string;
    customClientId: string | null;
    customClientSecret: string | null;
}

async function startIntuitOAuth(
    request: Request,
    { scopesParam, customClientId, customClientSecret }: IntuitAuthorizeInput
) {
    if (
        (customClientId || customClientSecret) &&
        !(customClientId && customClientSecret)
    ) {
        return new Response(
            popupErrorHtml(
                'Enter both custom client ID and client secret, or leave both blank.'
            ),
            {
                status: 400,
                headers: { 'Content-Type': 'text/html; charset=utf-8' },
            }
        );
    }

    const clientId =
        customClientId ||
        process.env.QUICKBOOKS_CLIENT_ID ||
        process.env.INTUIT_CLIENT_ID;
    const redirectUri =
        process.env.QUICKBOOKS_REDIRECT_URI || process.env.INTUIT_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[intuit.authorize] Missing QuickBooks/Intuit OAuth env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'quickbooks',
            missing: [
                'QUICKBOOKS_CLIENT_ID',
                'INTUIT_CLIENT_ID',
                'QUICKBOOKS_REDIRECT_URI',
                'INTUIT_REDIRECT_URI',
            ],
        });
    }

    const scopes = scopesParam
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    const nonce = crypto.randomUUID();
    const state = Buffer.from(JSON.stringify({ nonce })).toString('base64url');
    const cookieHeader = await intuitOAuthStateCookie.serialize(
        JSON.stringify({
            nonce,
            scopes,
            customClientId: customClientId || null,
            customClientSecret: customClientSecret || null,
            timestamp: Date.now(),
        })
    );

    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        response_type: 'code',
        scope: scopes.join(' '),
        state,
    });

    return oauthRedirect(
        request,
        `${QUICKBOOKS_AUTH_URL}?${params.toString()}`,
        {
            headers: {
                'Set-Cookie': cookieHeader,
            },
        }
    );
}
