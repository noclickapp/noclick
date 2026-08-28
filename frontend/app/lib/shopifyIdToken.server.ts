import crypto from 'crypto';

export interface ShopifyIdTokenPayload {
    aud: string;
    dest: string;
    exp: number;
    iss: string;
    nbf: number;
    sub?: string;
}

interface ShopifyIdTokenHeader {
    alg: string;
    typ?: string;
}

function decodeBase64UrlJson<T>(value: string): T | null {
    try {
        return JSON.parse(
            Buffer.from(value, 'base64url').toString('utf8')
        ) as T;
    } catch {
        return null;
    }
}

/**
 * Verify the short-lived ID token (formerly session token) issued by App
 * Bridge. The token authenticates the Shopify user and store; it is never sent
 * to Shopify's Admin API.
 */
export function verifyShopifyIdToken(
    token: string,
    secret: string,
    clientId: string,
    nowSeconds = Math.floor(Date.now() / 1000)
): ShopifyIdTokenPayload | null {
    if (!token || !secret || !clientId) return null;

    const parts = token.split('.');
    if (parts.length !== 3 || parts.some((part) => !part)) return null;

    const [encodedHeader, encodedPayload, encodedSignature] = parts;
    const header = decodeBase64UrlJson<ShopifyIdTokenHeader>(encodedHeader);
    const payload = decodeBase64UrlJson<ShopifyIdTokenPayload>(encodedPayload);
    if (!header || !payload || header.alg !== 'HS256') return null;

    let suppliedSignature: Buffer;
    try {
        suppliedSignature = Buffer.from(encodedSignature, 'base64url');
    } catch {
        return null;
    }
    const expectedSignature = crypto
        .createHmac('sha256', secret)
        .update(`${encodedHeader}.${encodedPayload}`, 'utf8')
        .digest();
    if (
        suppliedSignature.length !== expectedSignature.length ||
        !crypto.timingSafeEqual(suppliedSignature, expectedSignature)
    ) {
        return null;
    }

    if (
        payload.aud !== clientId ||
        !Number.isFinite(payload.exp) ||
        !Number.isFinite(payload.nbf) ||
        payload.exp <= nowSeconds ||
        payload.nbf > nowSeconds
    ) {
        return null;
    }

    try {
        const issuer = new URL(payload.iss);
        const destination = new URL(payload.dest);
        if (
            issuer.protocol !== 'https:' ||
            destination.protocol !== 'https:' ||
            issuer.hostname !== destination.hostname ||
            !destination.hostname.endsWith('.myshopify.com')
        ) {
            return null;
        }
    } catch {
        return null;
    }

    return payload;
}
