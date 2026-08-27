import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    cookieParse: vi.fn(),
    oauthCallbackUrl: vi.fn(),
    verifyShopifyQueryHmac: vi.fn(),
}));

vi.mock('react-router', async () => {
    const actual =
        await vi.importActual<typeof import('react-router')>('react-router');
    return {
        ...actual,
        createCookie: () => ({
            parse: mocks.cookieParse,
            serialize: vi.fn(),
        }),
    };
});

vi.mock('~/lib/oauthFlow.server', () => ({
    oauthCallbackUrl: mocks.oauthCallbackUrl,
}));

vi.mock('~/lib/shopifyHmac.server', () => ({
    verifyShopifyQueryHmac: mocks.verifyShopifyQueryHmac,
}));

vi.mock('~/lib/serverSecrets', () => ({
    getCookieSecret: () => 'cookie-secret',
}));

vi.mock('~/lib/supabase', () => ({
    requireAuth: vi.fn(),
}));

vi.mock('~/lib/hostedDefaults', () => ({
    apiBaseUrl: () => 'https://api.noclick.test',
}));

import { loader } from '~/routes/api/auth/shopify.callback';
import { requireAuth } from '~/lib/supabase';

describe('Shopify OAuth callback HMAC verification', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        process.env.SHOPIFY_CLIENT_SECRET = 'shopify-secret';
        mocks.cookieParse.mockResolvedValue(
            JSON.stringify({
                nonce: 'nonce',
                shop: 'review-store',
                customClientSecret: null,
                mode: 'popup',
            })
        );
        mocks.verifyShopifyQueryHmac.mockReturnValue(false);
    });

    it('verifies the signed URL before decrypting the OAuth state', async () => {
        const requestUrl = new URL(
            'https://www.noclick.com/api/auth/shopify/callback'
        );
        requestUrl.searchParams.set('code', 'oauth-code');
        requestUrl.searchParams.set('shop', 'review-store.myshopify.com');
        requestUrl.searchParams.set('state', 'sealed-state');
        requestUrl.searchParams.set('hmac', 'signed-hmac');

        const decryptedUrl = new URL(requestUrl);
        decryptedUrl.searchParams.set(
            'state',
            Buffer.from(JSON.stringify({ nonce: 'nonce' })).toString(
                'base64url'
            )
        );
        mocks.oauthCallbackUrl.mockResolvedValue(decryptedUrl);

        const result = await loader({
            request: new Request(requestUrl),
            params: {},
            context: {},
        } as never);

        expect(result).toEqual({
            success: false,
            error: 'Invalid Shopify request signature.',
        });
        expect(mocks.verifyShopifyQueryHmac).toHaveBeenCalledOnce();
        const [verifiedUrl] = mocks.verifyShopifyQueryHmac.mock.calls[0] as [
            URL,
            string,
        ];
        expect(verifiedUrl.searchParams.get('state')).toBe('sealed-state');
    });

    it('returns completed installs to the embedded Shopify Admin app', async () => {
        process.env.SHOPIFY_REDIRECT_URI =
            'https://www.noclick.com/api/auth/shopify/callback';
        process.env.SHOPIFY_CLIENT_ID = 'public-client-id';
        mocks.cookieParse.mockResolvedValue(
            JSON.stringify({
                nonce: 'nonce',
                shop: 'review-store',
                scopes: ['read_products'],
                customClientSecret: null,
                mode: 'install',
            })
        );
        mocks.verifyShopifyQueryHmac.mockReturnValue(true);
        vi.mocked(requireAuth).mockResolvedValue({
            session: { access_token: 'noclick-session' },
            headers: new Headers(),
        } as never);
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ success: true }), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                })
            )
        );

        const requestUrl = new URL(
            'https://www.noclick.com/api/auth/shopify/callback'
        );
        requestUrl.searchParams.set('code', 'oauth-code');
        requestUrl.searchParams.set('shop', 'review-store.myshopify.com');
        requestUrl.searchParams.set('state', 'sealed-state');
        requestUrl.searchParams.set('hmac', 'signed-hmac');
        const decryptedUrl = new URL(requestUrl);
        decryptedUrl.searchParams.set(
            'state',
            Buffer.from(JSON.stringify({ nonce: 'nonce' })).toString(
                'base64url'
            )
        );
        mocks.oauthCallbackUrl.mockResolvedValue(decryptedUrl);

        const response = (await loader({
            request: new Request(requestUrl),
            params: {},
            context: {},
        } as never)) as Response;

        expect(response.status).toBe(302);
        expect(response.headers.get('Location')).toBe(
            'https://admin.shopify.com/store/review-store/apps/public-client-id'
        );
        vi.unstubAllGlobals();
    });
});
