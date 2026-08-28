import crypto from 'crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { verifyShopifyIdToken } from '~/lib/shopifyIdToken.server';

const mocks = vi.hoisted(() => ({
    installed: vi.fn(),
    poolEnd: vi.fn(),
}));

vi.mock('~/cloud/lib/shopify-install-status.server', () => ({
    hasPublicShopifyInstall: mocks.installed,
}));

vi.mock('~/cloud/lib/subscription', () => ({
    createPool: () => ({ query: vi.fn(), end: mocks.poolEnd }),
}));

import { action } from '~/routes/api/auth/shopify.app.session';

const SECRET = 'shopify-secret';
const CLIENT_ID = 'shopify-client-id';
const NOW = 1_800_000_000;

function makeToken(overrides: Record<string, unknown> = {}, secret = SECRET) {
    const header = Buffer.from(
        JSON.stringify({ alg: 'HS256', typ: 'JWT' })
    ).toString('base64url');
    const payload = Buffer.from(
        JSON.stringify({
            iss: 'https://review-store.myshopify.com/admin',
            dest: 'https://review-store.myshopify.com',
            aud: CLIENT_ID,
            sub: '42',
            exp: NOW + 60,
            nbf: NOW - 1,
            ...overrides,
        })
    ).toString('base64url');
    const signature = crypto
        .createHmac('sha256', secret)
        .update(`${header}.${payload}`)
        .digest('base64url');
    return `${header}.${payload}.${signature}`;
}

function makeCurrentToken() {
    const now = Math.floor(Date.now() / 1000);
    return makeToken({ exp: now + 60, nbf: now - 1 });
}

describe('Shopify ID token verification', () => {
    it('accepts a valid App Bridge token', () => {
        expect(
            verifyShopifyIdToken(makeToken(), SECRET, CLIENT_ID, NOW)
        ).toMatchObject({
            aud: CLIENT_ID,
            dest: 'https://review-store.myshopify.com',
        });
    });

    it.each([
        ['wrong signature', makeToken({}, 'wrong-secret')],
        ['expired token', makeToken({ exp: NOW })],
        ['future token', makeToken({ nbf: NOW + 1 })],
        ['wrong audience', makeToken({ aud: 'another-app' })],
        [
            'mismatched issuer',
            makeToken({ iss: 'https://another-store.myshopify.com/admin' }),
        ],
        ['non-Shopify destination', makeToken({ dest: 'https://example.com' })],
    ])('rejects a %s', (_name, token) => {
        expect(verifyShopifyIdToken(token, SECRET, CLIENT_ID, NOW)).toBeNull();
    });
});

describe('Shopify embedded session endpoint', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        process.env.SHOPIFY_CLIENT_SECRET = SECRET;
        process.env.SHOPIFY_CLIENT_ID = CLIENT_ID;
        mocks.installed.mockResolvedValue(true);
        mocks.poolEnd.mockResolvedValue(undefined);
    });

    it('authenticates the user and installed store without cookies', async () => {
        const response = await action({
            request: new Request(
                'https://www.noclick.com/api/auth/shopify/app/session',
                {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${makeCurrentToken()}` },
                }
            ),
            params: {},
            context: {},
        } as never);

        expect(response.status).toBe(204);
        expect(response.headers.get('Cache-Control')).toBe('no-store');
        expect(mocks.installed).toHaveBeenCalledWith(
            expect.anything(),
            'review-store.myshopify.com'
        );
        expect(mocks.poolEnd).toHaveBeenCalledOnce();
    });

    it('rejects an invalid token before querying the install', async () => {
        await expect(
            action({
                request: new Request(
                    'https://www.noclick.com/api/auth/shopify/app/session',
                    {
                        method: 'POST',
                        headers: { Authorization: 'Bearer invalid' },
                    }
                ),
                params: {},
                context: {},
            } as never)
        ).rejects.toMatchObject({ status: 401 });
        expect(mocks.installed).not.toHaveBeenCalled();
    });

    it('rejects a valid user token for an uninstalled store', async () => {
        mocks.installed.mockResolvedValue(false);

        await expect(
            action({
                request: new Request(
                    'https://www.noclick.com/api/auth/shopify/app/session',
                    {
                        method: 'POST',
                        headers: {
                            Authorization: `Bearer ${makeCurrentToken()}`,
                        },
                    }
                ),
                params: {},
                context: {},
            } as never)
        ).rejects.toMatchObject({ status: 403 });
        expect(mocks.poolEnd).toHaveBeenCalledOnce();
    });
});
