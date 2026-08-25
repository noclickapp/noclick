// Shopify OAuth authorize route.
// Redirects to Shopify's consent screen to request user authorization.
// Shopify uses shop-specific OAuth URLs: https://{shop}.myshopify.com/admin/oauth/authorize

import { oauthRedirect } from '~/lib/oauthFlow.server';
import { type ActionFunctionArgs, type LoaderFunctionArgs } from 'react-router';
import { createCookie } from 'react-router';
import crypto from 'crypto';
import { oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { applyInstanceOAuthEnv } from '~/lib/instanceOAuth.server';
import { oauthFormString, oauthPostFormData } from '~/lib/oauthPost.server';
import { serializeForInlineScript } from '~/lib/inlineScript.server';

const shopifyOAuthStateCookie = createCookie('shopify_oauth_state', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/api/auth/shopify',
    maxAge: 600, // 10 minutes
});

function normalizeShopInput(shopRaw: string): string {
    return shopRaw
        .trim()
        .toLowerCase()
        .replace(/^https?:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(/\.myshopify\.com$/, '');
}

function popupErrorHtml(message: string): string {
    const payload = serializeForInlineScript({
        type: 'shopify-oauth-callback',
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
    await applyInstanceOAuthEnv(request, 'shopify');
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

    return startShopifyOAuth(request, {
        credentialName: url.searchParams.get('name') || 'Shopify',
        shopRaw: url.searchParams.get('shop'),
        scopesParam:
            url.searchParams.get('scopes') || 'read_products,write_products',
        customClientId: null,
        customClientSecret: null,
    });
}

export async function action({ request }: ActionFunctionArgs) {
    const formData = await oauthPostFormData(request);
    await applyInstanceOAuthEnv(request, 'shopify');
    return startShopifyOAuth(request, {
        credentialName: oauthFormString(formData, 'name') || 'Shopify',
        shopRaw: oauthFormString(formData, 'shop'),
        scopesParam:
            oauthFormString(formData, 'scopes') ||
            'read_products,write_products',
        customClientId: oauthFormString(formData, 'customClientId'),
        customClientSecret: oauthFormString(formData, 'customClientSecret'),
    });
}

interface ShopifyAuthorizeInput {
    credentialName: string;
    shopRaw: string | null;
    scopesParam: string;
    customClientId: string | null;
    customClientSecret: string | null;
}

async function startShopifyOAuth(
    request: Request,
    {
        credentialName,
        shopRaw,
        scopesParam,
        customClientId,
        customClientSecret,
    }: ShopifyAuthorizeInput
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

    if (!shopRaw) {
        console.error('[shopify.authorize] Missing shop parameter');
        return new Response(
            popupErrorHtml('Shop parameter is required for Shopify OAuth'),
            {
                status: 400,
                headers: { 'Content-Type': 'text/html; charset=utf-8' },
            }
        );
    }

    const shop = normalizeShopInput(shopRaw);
    if (!/^[a-z0-9][a-z0-9-]*$/.test(shop)) {
        console.error('[shopify.authorize] Invalid shop format:', shopRaw);
        return new Response(
            popupErrorHtml(
                'Invalid Shopify store. Enter only the subdomain (for example: my-store).'
            ),
            {
                status: 400,
                headers: { 'Content-Type': 'text/html; charset=utf-8' },
            }
        );
    }

    // Use custom client ID if provided, otherwise use default from env
    const clientId = customClientId || process.env.SHOPIFY_CLIENT_ID;
    const redirectUri = process.env.SHOPIFY_REDIRECT_URI;

    if (!clientId || !redirectUri) {
        console.error(
            '[shopify.authorize] Missing SHOPIFY_CLIENT_ID or SHOPIFY_REDIRECT_URI env vars'
        );
        return oauthNotConfiguredResponse({
            request,
            provider: 'shopify',
            missing: ['SHOPIFY_CLIENT_ID', 'SHOPIFY_REDIRECT_URI'],
        });
    }

    // State now carries nonce only; credential metadata is stored in a short-lived HttpOnly cookie.
    const nonce = crypto.randomUUID();
    const state = Buffer.from(JSON.stringify({ nonce })).toString('base64url');
    const cookiePayload = {
        nonce,
        credentialName,
        shop,
        scopes: scopesParam.split(','),
        customClientId: customClientId || null,
        customClientSecret: customClientSecret || null,
        timestamp: Date.now(),
    };
    const cookieHeader = await shopifyOAuthStateCookie.serialize(
        JSON.stringify(cookiePayload)
    );

    // Shopify uses shop-specific authorization URL
    const authUrl = `https://${shop}.myshopify.com/admin/oauth/authorize`;

    // Shopify expects comma-separated scopes
    const params = new URLSearchParams({
        client_id: clientId,
        redirect_uri: redirectUri,
        scope: scopesParam, // Already comma-separated
        state: state,
    });

    const fullAuthUrl = `${authUrl}?${params.toString()}`;

    return oauthRedirect(request, fullAuthUrl, {
        headers: {
            'Set-Cookie': cookieHeader,
        },
    });
}
