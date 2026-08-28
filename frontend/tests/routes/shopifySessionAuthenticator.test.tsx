// @vitest-environment jsdom

import { render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ShopifySessionAuthenticator } from '~/routes/api/auth/shopify.app';

describe('ShopifySessionAuthenticator', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
        delete window.shopify;
    });

    it('sends a fresh App Bridge ID token to the first-party backend', async () => {
        const idToken = vi.fn().mockResolvedValue('signed-id-token');
        const fetchSpy = vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 204 }));
        window.shopify = { idToken };
        vi.stubGlobal('fetch', fetchSpy);

        render(<ShopifySessionAuthenticator />);

        await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());
        expect(idToken).toHaveBeenCalledOnce();
        expect(fetchSpy).toHaveBeenCalledWith(
            '/api/auth/shopify/app/session',
            expect.objectContaining({
                method: 'POST',
                headers: { Authorization: 'Bearer signed-id-token' },
                credentials: 'omit',
            })
        );
    });
});
