import crypto from 'crypto';

/**
 * Verify the hexadecimal HMAC Shopify adds to app-entry and OAuth callback
 * query strings. URLSearchParams exposes the decoded key/value pairs that
 * Shopify signs; ordering is canonicalized by key before hashing.
 */
export function verifyShopifyQueryHmac(url: URL, secret: string): boolean {
    const supplied = url.searchParams.get('hmac') || '';
    if (!/^[a-f0-9]{64}$/i.test(supplied) || !secret) return false;

    const message = [...url.searchParams.entries()]
        .filter(([key]) => key !== 'hmac' && key !== 'signature')
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, value]) => `${key}=${value}`)
        .join('&');
    const expected = crypto
        .createHmac('sha256', secret)
        .update(message, 'utf8')
        .digest('hex');

    return crypto.timingSafeEqual(
        Buffer.from(supplied, 'hex'),
        Buffer.from(expected, 'hex')
    );
}
