import type { ActionFunctionArgs } from 'react-router';
import { createPool } from '~/cloud/lib/subscription';
import { hasPublicShopifyInstall } from '~/cloud/lib/shopify-install-status.server';
import { verifyShopifyIdToken } from '~/lib/shopifyIdToken.server';

export async function action({ request }: ActionFunctionArgs) {
    const authorization = request.headers.get('Authorization') || '';
    const token = authorization.match(/^Bearer\s+(.+)$/i)?.[1] || '';
    const payload = verifyShopifyIdToken(
        token,
        process.env.SHOPIFY_CLIENT_SECRET || '',
        process.env.SHOPIFY_CLIENT_ID || ''
    );
    if (!payload) {
        throw new Response('Invalid Shopify ID token.', { status: 401 });
    }

    const shop = new URL(payload.dest).hostname;
    const pool = createPool();
    let installed = false;
    try {
        installed = await hasPublicShopifyInstall(pool, shop);
    } finally {
        await pool.end();
    }
    if (!installed) {
        throw new Response('Shopify app is not installed for this store.', {
            status: 403,
        });
    }

    return new Response(null, {
        status: 204,
        headers: { 'Cache-Control': 'no-store' },
    });
}
