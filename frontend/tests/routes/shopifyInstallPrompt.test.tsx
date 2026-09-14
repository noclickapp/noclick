// @vitest-environment jsdom
// Verify the real embedded app's setup branch and top-level OAuth link.
// Missing installs must never render a connected status or start ID-token calls.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ loaderData: vi.fn() }));
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useLoaderData: mocks.loaderData,
}));
vi.mock('~/cloud/lib/subscription', () => ({ createPool: vi.fn() }));
vi.mock('~/cloud/lib/shopify-install-status.server', () => ({
    hasPublicShopifyInstall: vi.fn(),
}));
vi.mock('~/lib/shopifyHmac.server', () => ({
    verifyShopifyQueryHmac: vi.fn(),
}));

import ShopifyAppHome from '~/routes/api/auth/shopify.app';

describe('embedded Shopify install prompt', () => {
    afterEach(() => {
        cleanup();
        delete window.shopify;
        vi.unstubAllGlobals();
    });

    it('offers a first-party top-level authorization link without authenticating prematurely', () => {
        const authorizeUrl =
            'https://www.noclick.com/api/auth/shopify/authorize?shop=review-store&mode=install';
        mocks.loaderData.mockReturnValue({
            shop: 'review-store.myshopify.com',
            workspaceUrl: 'https://www.noclick.com/dashboard?tab=workflows',
            authorizeUrl,
        });
        const idToken = vi.fn();
        window.shopify = { idToken };
        render(<ShopifyAppHome />);

        const link = screen.getByRole('link', {
            name: 'Continue Shopify setup',
        });
        expect(link.getAttribute('href')).toBe(authorizeUrl);
        expect(link.getAttribute('target')).toBe('_top');
        expect(screen.getByRole('heading').textContent).toBe(
            'Connect your Shopify store'
        );
        expect(screen.queryByText('Your store is connected')).toBeNull();
        expect(
            screen.queryByRole('link', { name: 'Open NoClick workspace' })
        ).toBeNull();
        expect(idToken).not.toHaveBeenCalled();
    });

    it('retains the connected surface and separate workspace link for an installed store', () => {
        mocks.loaderData.mockReturnValue({
            shop: 'review-store.myshopify.com',
            workspaceUrl: 'https://www.noclick.com/dashboard?tab=workflows',
            authorizeUrl: null,
        });
        window.shopify = {
            idToken: vi.fn().mockResolvedValue('test-id-token'),
        };
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        );
        render(<ShopifyAppHome />);

        expect(
            screen.getByRole('heading', { name: 'Your store is connected' })
        ).toBeTruthy();
        expect(
            screen.queryByRole('link', { name: 'Continue Shopify setup' })
        ).toBeNull();
        expect(
            screen
                .getByRole('link', { name: 'Open NoClick workspace' })
                .getAttribute('target')
        ).toBe('_blank');
    });
});
