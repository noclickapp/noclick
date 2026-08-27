// Shopify App Store entry point. Shopify requires installs to begin provider
// authentication immediately, so NoClick authentication is deferred until the
// callback. The callback preserves Shopify's signed code in its `next` URL
// while the merchant signs in, then exchanges and persists the grant server-side.

import { redirect, type LoaderFunctionArgs } from 'react-router';
import { SHOPIFY_APP_SCOPES_PARAM } from '~/lib/shopifyScopes';
import { verifyShopifyQueryHmac } from '~/lib/shopifyHmac.server';
import { normalizeShopInput } from './shopify.authorize';

export async function loader({ request }: LoaderFunctionArgs) {
    const url = new URL(request.url);
    const shopifySecret = process.env.SHOPIFY_CLIENT_SECRET || '';
    if (!verifyShopifyQueryHmac(url, shopifySecret)) {
        throw new Response('Invalid Shopify request signature.', {
            status: 401,
        });
    }

    const shop = normalizeShopInput(url.searchParams.get('shop') || '');
    if (!/^[a-z0-9][a-z0-9-]*$/.test(shop)) {
        throw new Response('A valid Shopify store is required.', {
            status: 400,
        });
    }

    const authorize = new URL('/api/auth/shopify/authorize', url.origin);
    authorize.searchParams.set('shop', shop);
    authorize.searchParams.set('name', 'Shopify');
    authorize.searchParams.set('scopes', SHOPIFY_APP_SCOPES_PARAM);
    authorize.searchParams.set('mode', 'install');
    return redirect(`${authorize.pathname}${authorize.search}`);
}
