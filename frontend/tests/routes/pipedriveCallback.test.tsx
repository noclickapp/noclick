// @vitest-environment jsdom
// Standalone installs must not pretend to be editor popups or report a saved
// connection merely because an authorization code reached the browser.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const state = vi.hoisted(() => ({ data: {} as Record<string, unknown> }));
vi.mock('react-router', async () => ({
    ...(await vi.importActual<typeof import('react-router')>('react-router')),
    useLoaderData: () => state.data,
}));
vi.mock('~/lib/supabase', () => ({
    requireAuth: vi.fn(),
    createServiceRoleClient: vi.fn(),
}));
vi.mock('~/lib/hostedDefaults', () => ({
    apiBaseUrl: () => 'https://api.example.test',
}));

import PipedriveOAuthCallback from '~/routes/api/auth/pipedrive.callback';

describe('Pipedrive callback UI', () => {
    beforeEach(() => {
        window.opener = null;
    });
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
        vi.useRealTimers();
        window.opener = null;
    });

    it('shows the actual standalone cancellation and a clean restart link', async () => {
        state.data = {
            success: false,
            mode: 'install',
            error: 'Pipedrive installation was cancelled. No connection was saved.',
        };
        render(<PipedriveOAuthCallback />);
        expect(
            await screen.findByText(
                'Pipedrive installation was cancelled. No connection was saved.'
            )
        ).toBeTruthy();
        expect(
            screen
                .getByRole('link', { name: 'Restart Pipedrive installation' })
                .getAttribute('href')
        ).toBe('/api/auth/pipedrive/install');
    });

    it('does not send install failures to an unrelated Marketplace opener', async () => {
        const postMessage = vi.fn();
        window.opener = { postMessage };
        state.data = {
            success: false,
            mode: 'install',
            error: 'Could not save the connection.',
        };
        render(<PipedriveOAuthCallback />);
        expect(
            await screen.findByText('Could not save the connection.')
        ).toBeTruthy();
        expect(postMessage).not.toHaveBeenCalled();
    });

    it('offers standalone recovery if a popup lost its opener', async () => {
        state.data = { success: true, code: 'fixture-code' };
        render(<PipedriveOAuthCallback />);
        await waitFor(() =>
            expect(
                screen.getByText(/editor window is no longer available/)
            ).toBeTruthy()
        );
        expect(screen.queryByText(/Connected Successfully/)).toBeNull();
        expect(
            screen.getByRole('link', { name: 'Restart Pipedrive installation' })
        ).toBeTruthy();
    });

    it('delivers popup authorization without claiming credential persistence', () => {
        vi.useFakeTimers();
        const postMessage = vi.fn();
        const close = vi.spyOn(window, 'close').mockImplementation(() => {});
        window.opener = { postMessage };
        state.data = { success: true, code: 'fixture-code', scopes: [] };
        render(<PipedriveOAuthCallback />);
        expect(postMessage).toHaveBeenCalledWith(
            { type: 'pipedrive-oauth-callback', ...state.data },
            window.location.origin
        );
        expect(screen.getByText('Authorization received')).toBeTruthy();
        expect(screen.queryByText(/Connected Successfully/)).toBeNull();
        vi.advanceTimersByTime(1500);
        expect(close).toHaveBeenCalledOnce();
    });
});
