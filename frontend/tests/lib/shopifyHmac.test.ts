import crypto from 'crypto';
import { describe, expect, it } from 'vitest';
import { verifyShopifyQueryHmac } from '~/lib/shopifyHmac.server';

function signedUrl(params: Record<string, string>, secret = 'shopify-secret') {
    const message = Object.entries(params)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, value]) => `${key}=${value}`)
        .join('&');
    const hmac = crypto
        .createHmac('sha256', secret)
        .update(message)
        .digest('hex');
    const url = new URL('https://www.noclick.com/api/auth/shopify/callback');
    for (const [key, value] of Object.entries(params)) {
        url.searchParams.set(key, value);
    }
    url.searchParams.set('hmac', hmac);
    return url;
}

describe('verifyShopifyQueryHmac', () => {
    it('accepts an authentic Shopify query independent of parameter order', () => {
        const url = signedUrl({
            timestamp: '1787790000',
            shop: 'merchant.myshopify.com',
            code: 'oauth-code',
            state: 'nonce',
        });
        expect(verifyShopifyQueryHmac(url, 'shopify-secret')).toBe(true);
    });

    it('rejects missing, malformed, tampered, and wrong-secret signatures', () => {
        const url = signedUrl({
            shop: 'merchant.myshopify.com',
            code: 'oauth-code',
        });
        expect(verifyShopifyQueryHmac(url, 'wrong-secret')).toBe(false);
        url.searchParams.set('shop', 'attacker.myshopify.com');
        expect(verifyShopifyQueryHmac(url, 'shopify-secret')).toBe(false);
        url.searchParams.delete('hmac');
        expect(verifyShopifyQueryHmac(url, 'shopify-secret')).toBe(false);
        url.searchParams.set('hmac', 'not-a-signature');
        expect(verifyShopifyQueryHmac(url, 'shopify-secret')).toBe(false);
    });
});
