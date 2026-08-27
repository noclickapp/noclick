import { describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/shopifyHmac.server', () => ({
    verifyShopifyQueryHmac: vi.fn(() => true),
}));

import { verifyShopifyQueryHmac } from '~/lib/shopifyHmac.server';
import { loader } from '~/routes/api/auth/shopify.install';

function load(url: string) {
    return loader({
        request: new Request(url),
        params: {},
        context: {},
    } as never);
}

describe('Shopify App Store install entry point', () => {
    it('starts Shopify OAuth immediately without a NoClick login redirect', async () => {
        const response = (await load(
            'https://www.noclick.com/api/auth/shopify/install?shop=review-store.myshopify.com&hmac=signed'
        )) as Response;

        expect(response.status).toBe(302);
        const location = response.headers.get('Location');
        expect(location).toMatch(/^\/api\/auth\/shopify\/authorize\?/);
        expect(location).toContain('shop=review-store');
        expect(location).toContain('mode=install');
        expect(location).not.toContain('/auth/login');
    });

    it('rejects an invalid Shopify request signature', async () => {
        vi.mocked(verifyShopifyQueryHmac).mockReturnValueOnce(false);

        await expect(
            load(
                'https://www.noclick.com/api/auth/shopify/install?shop=review-store.myshopify.com&hmac=invalid'
            )
        ).rejects.toMatchObject({ status: 401 });
    });

    it('rejects a malformed shop even when the request is signed', async () => {
        await expect(
            load(
                'https://www.noclick.com/api/auth/shopify/install?shop=bad.example.com&hmac=signed'
            )
        ).rejects.toMatchObject({ status: 400 });
    });
});
