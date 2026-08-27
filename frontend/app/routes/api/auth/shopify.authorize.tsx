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
import { getCookieSecret } from '~/lib/serverSecrets';

const shopifyOAuthStateCookie = createCookie('shopify_oauth_state', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/api/auth/shopify',
    maxAge: 600, // 10 minutes
    secrets: [getCookieSecret('shopify-oauth-state')],
});

export function normalizeShopInput(shopRaw: string): string {
    const trimmed = shopRaw.trim().toLowerCase();
    // Pasting the admin URL is a natural move — pull the handle straight out.
    const adminMatch = trimmed.match(
        /admin\.shopify\.com\/store\/([a-z0-9][a-z0-9-]*)/
    );
    if (adminMatch) return adminMatch[1];
    return trimmed
        .replace(/^https?:\/\//, '')
        .replace(/\/.*$/, '')
        .replace(/\.myshopify\.com$/, '');
}

// Store owners think in their custom domain ("ohamillinc.com"), not the
// myshopify handle behind it. A Shopify storefront names its canonical
// *.myshopify.com domain throughout its HTML, so a domain-shaped input is
// resolved by reading it from the live storefront; null means the caller
// surfaces the explicit format error, never a guess.
export async function resolveShopFromDomain(
    domain: string
): Promise<string | null> {
    if (
        !/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(
            domain
        )
    ) {
        return null;
    }
    let html: string;
    try {
        const res = await fetch(`https://${domain}/`, {
            redirect: 'follow',
            signal: AbortSignal.timeout(6000),
            headers: { accept: 'text/html' },
        });
        if (!res.ok) return null;
        html = (await res.text()).slice(0, 1_000_000);
    } catch {
        return null;
    }
    // Most-frequent handle wins: a storefront references its own domain many
    // times (Shopify.shop, preconnects), a stray link to another store once.
    const counts = new Map<string, number>();
    for (const match of html.matchAll(
        /([a-z0-9][a-z0-9-]*)\.myshopify\.com/g
    )) {
        counts.set(match[1], (counts.get(match[1]) ?? 0) + 1);
    }
    let best: string | null = null;
    for (const [handle, count] of counts) {
        if (best === null || count > (counts.get(best) ?? 0)) best = handle;
    }
    return best;
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
        mode: url.searchParams.get('mode') === 'install' ? 'install' : 'popup',
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
        mode: 'popup',
    });
}

interface ShopifyAuthorizeInput {
    credentialName: string;
    shopRaw: string | null;
    scopesParam: string;
    customClientId: string | null;
    customClientSecret: string | null;
    mode: 'popup' | 'install';
}

async function startShopifyOAuth(
    request: Request,
    {
        credentialName,
        shopRaw,
        scopesParam,
        customClientId,
        customClientSecret,
        mode,
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

    let shop = normalizeShopInput(shopRaw);
    if (shop.includes('.')) {
        shop = (await resolveShopFromDomain(shop)) ?? shop;
    }
    if (!/^[a-z0-9][a-z0-9-]*$/.test(shop)) {
        console.error('[shopify.authorize] Invalid shop format:', shopRaw);
        return new Response(
            popupErrorHtml(
                'Could not find a Shopify store for that name. Enter your store handle — the "xxxx" in xxxx.myshopify.com, shown in your Shopify admin URL as admin.shopify.com/store/xxxx.'
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
        mode,
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
