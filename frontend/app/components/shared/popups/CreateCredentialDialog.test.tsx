// @vitest-environment happy-dom
// Opening an account (the command palette's credential, a resource's Manage) shows the account when it works; a broken
// one, or a Reconnect, opens the Connect dialog on its way back in.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { CredentialInfo } from '~/types/socket-events.generated';

const cache = vi.hoisted(() => ({ rows: [] as Partial<CredentialInfo>[] }));
const navigateToAccount = vi.hoisted(() => vi.fn());

vi.mock('~/utils/credentialAutoSelect', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/utils/credentialAutoSelect')>()),
    getAllCredentialsFromCache: () => cache.rows,
    prefetchCredentials: async () => undefined,
}));
// The catalog the picker lists is loaded at runtime; here it holds Stripe and a retired service.
vi.mock('~/hooks/useServiceCredentialOptions', () => ({
    useServiceCredentialOptions: () => [
        { value: 'automation-stripe', label: 'Stripe', primaryCredentialType: 'stripe_api_key', acceptedCredentialTypes: ['stripe_api_key'], Icon: () => null, iconColor: '', listed: true },
        { value: 'automation-humanloop', label: 'Humanloop', primaryCredentialType: 'humanloop_api_key', acceptedCredentialTypes: ['humanloop_api_key'], Icon: () => null, iconColor: '', listed: false },
    ],
}));
vi.mock('~/lib/navigation', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/lib/navigation')>()),
    navigateToAccount,
}));

import { GlobalCreateCredentialDialog, openCreateCredential } from './CreateCredentialDialog';

// The connect step loads lazily; load it once up front so a busy machine doesn't decide the test.
beforeAll(async () => {
    await import('./ConnectAppStep');
}, 60_000);

afterEach(() => {
    cleanup();
    navigateToAccount.mockReset();
});

const stripe = (fields: Partial<CredentialInfo>): Partial<CredentialInfo> => ({ id: 'cred-1', name: 'Stripe', credential_type: 'stripe_api_key', access_type: 'owner', ...fields });
const dialogOpen = () => !!document.querySelector('[data-testid="create-credential-dialog"][data-state="open"]');

describe('opening an existing account', () => {
    it('shows a working account on its page', async () => {
        cache.rows = [stripe({})];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'stripe_api_key', credentialId: 'cred-1' }));
        expect(navigateToAccount).toHaveBeenCalledWith('cred-1');
        expect(dialogOpen()).toBe(false);
    });

    it('opens the Connect dialog for a broken one', async () => {
        cache.rows = [stripe({ revoked_at: '2026-10-17T00:00:00Z' })];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'stripe_api_key', credentialId: 'cred-1' }));
        expect(navigateToAccount).not.toHaveBeenCalled();
        expect(await screen.findByTestId('create-credential-dialog')).toBeTruthy();
    });

    it('reconnects a working account it is asked to, on its own way in', async () => {
        cache.rows = [stripe({})];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'stripe_api_key', credentialId: 'cred-1', reconnect: true }));
        expect(navigateToAccount).not.toHaveBeenCalled();
        expect(await screen.findByText('Connect Stripe')).toBeTruthy();
        expect(await screen.findByText('Paste it here', {}, { timeout: 5000 })).toBeTruthy();
    });
});

describe('the picker’s search', () => {
    it('clears with its ✕, keeping focus in the box', async () => {
        cache.rows = [];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential());
        const box = screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search apps' });
        expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull();
        fireEvent.change(box, { target: { value: 'zz' } });
        expect(await screen.findByText('Nothing matches “zz”.')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
        expect(box.value).toBe('');
        expect(document.activeElement).toBe(box);
        expect((await screen.findAllByTestId('credential-service-row')).map((row) => row.textContent)).toEqual(['Stripe']);
    });

    it('clears on Escape first, and only an empty one closes the dialog', async () => {
        cache.rows = [];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential());
        const box = screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search apps' });
        fireEvent.change(box, { target: { value: 'str' } });
        fireEvent.keyDown(box, { key: 'Escape' });
        expect(box.value).toBe('');
        expect(dialogOpen()).toBe(true);
        fireEvent.keyDown(box, { key: 'Escape' });
        await waitFor(() => expect(dialogOpen()).toBe(false));
    });
});

describe('a retired service', () => {
    it('is not offered in the picker', async () => {
        cache.rows = [];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential());
        const rows = await screen.findAllByTestId('credential-service-row');
        expect(rows.map((row) => row.textContent)).toEqual(['Stripe']);
    });

    it('still reconnects an account already connected to it', async () => {
        cache.rows = [{ id: 'cred-2', name: 'Humanloop', credential_type: 'humanloop_api_key', access_type: 'owner', revoked_at: '2026-10-17T00:00:00Z' }];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'humanloop_api_key', credentialId: 'cred-2' }));
        expect(await screen.findByText('Connect Humanloop')).toBeTruthy();
    });
});
