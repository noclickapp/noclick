// Tests for the Shopify authorize route's store-name handling: pasting the
// admin URL yields the handle, a custom domain (what store owners naturally
// type — the Aug 2026 "error pops up instantly" support case) is resolved to
// its canonical *.myshopify.com handle by reading the live storefront, and an
// unresolvable input still fails loudly with the format error, never a guess.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/oauthFlow.server', () => ({
    oauthRedirect: vi.fn((_req: Request, url: string) => ({ redirectedTo: url })),
}));
vi.mock('~/lib/oauthSetupPage.server', () => ({
    oauthNotConfiguredResponse: vi.fn(() => new Response('not configured', { status: 500 })),
}));
vi.mock('~/lib/instanceOAuth.server', () => ({
    applyInstanceOAuthEnv: vi.fn(async () => {}),
}));
vi.mock('~/lib/oauthPost.server', () => ({
    oauthFormString: vi.fn(),
    oauthPostFormData: vi.fn(),
}));
vi.mock('~/lib/inlineScript.server', () => ({
    serializeForInlineScript: vi.fn((v: unknown) => JSON.stringify(v)),
}));

import { oauthRedirect } from '~/lib/oauthFlow.server';
import {
    loader,
    normalizeShopInput,
    resolveShopFromDomain,
} from '~/routes/api/auth/shopify.authorize';

function storefrontHtml(handle: string): string {
    return `<html><head><link rel="preconnect" href="https://${handle}.myshopify.com">
<script>Shopify.shop = "${handle}.myshopify.com";</script></head>
<body><a href="https://${handle}.myshopify.com/cart">cart</a>
<a href="https://some-other-store.myshopify.com/partner">partner</a></body></html>`;
}

describe('normalizeShopInput', () => {
    it('strips protocol, path, and the myshopify suffix', () => {
        expect(normalizeShopInput('https://Pupngp-K1.myshopify.com/admin')).toBe('pupngp-k1');
        expect(normalizeShopInput('  my-store  ')).toBe('my-store');
    });

    it('pulls the handle out of a pasted admin URL', () => {
        expect(normalizeShopInput('https://admin.shopify.com/store/pupngp-k1')).toBe('pupngp-k1');
        expect(normalizeShopInput('admin.shopify.com/store/pupngp-k1/settings')).toBe('pupngp-k1');
    });

    it('leaves a custom domain intact for the resolver', () => {
        expect(normalizeShopInput('www.ohamillinc.com')).toBe('www.ohamillinc.com');
    });
});

describe('resolveShopFromDomain', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('returns the most-referenced handle from the storefront HTML', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => new Response(storefrontHtml('pupngp-k1'), { status: 200 }))
        );
        expect(await resolveShopFromDomain('ohamillinc.com')).toBe('pupngp-k1');
    });

    it('returns null for a non-OK response and a network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 404 })));
        expect(await resolveShopFromDomain('ohamillinc.com')).toBe(null);
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => {
                throw new Error('dns');
            })
        );
        expect(await resolveShopFromDomain('ohamillinc.com')).toBe(null);
    });

    it('refuses to fetch anything that is not a bare hostname', async () => {
        const fetchSpy = vi.fn();
        vi.stubGlobal('fetch', fetchSpy);
        expect(await resolveShopFromDomain('evil.com:8080')).toBe(null);
        expect(await resolveShopFromDomain('host/../path')).toBe(null);
        expect(fetchSpy).not.toHaveBeenCalled();
    });
});

describe('loader shop resolution wiring', () => {
    beforeEach(() => {
        process.env.SHOPIFY_CLIENT_ID = 'test-client-id';
        process.env.SHOPIFY_REDIRECT_URI = 'https://noclick.com/api/auth/shopify/callback';
        vi.mocked(oauthRedirect).mockClear();
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('resolves a custom domain to its handle before redirecting', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(async () => new Response(storefrontHtml('pupngp-k1'), { status: 200 }))
        );
        const result = (await loader({
            request: new Request('https://noclick.com/api/auth/shopify/authorize?shop=ohamillinc.com&name=Shopify'),
            params: {},
            context: {},
        } as never)) as unknown as { redirectedTo: string };
        expect(result.redirectedTo).toContain('https://pupngp-k1.myshopify.com/admin/oauth/authorize');
    });

    it('fails loudly with the format error when the domain does not resolve', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response('not shopify', { status: 200 })));
        const result = (await loader({
            request: new Request('https://noclick.com/api/auth/shopify/authorize?shop=ohamillinc.com&name=Shopify'),
            params: {},
            context: {},
        } as never)) as Response;
        expect(result.status).toBe(400);
        expect(await result.text()).toContain('admin.shopify.com/store/xxxx');
        expect(oauthRedirect).not.toHaveBeenCalled();
    });
});
