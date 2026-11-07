// @vitest-environment jsdom
import React from 'react';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import OAuthCallback from '~/routes/api/auth/oauth.$provider.callback';
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useLoaderData: () => ({ provider: 'example', success: true, code: 'code' }),
}));
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

it('shows a retry error if the connecting window is gone', async () => {
    vi.stubGlobal('opener', null);
    render(<OAuthCallback />);
    await waitFor(() =>
        expect(screen.getByText(/connection window was lost/)).toBeTruthy()
    );
    expect(screen.queryByText(/Completing connection/)).toBeNull();
});

it('delivers the callback and closes when the connecting window exists', async () => {
    const postMessage = vi.fn();
    vi.stubGlobal('opener', { postMessage });
    const close = vi.spyOn(window, 'close').mockImplementation(() => {});
    render(<OAuthCallback />);
    await waitFor(() =>
        expect(postMessage).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'example-oauth-callback',
                code: 'code',
            }),
            window.location.origin
        )
    );
    expect(close).toHaveBeenCalledOnce();
});
