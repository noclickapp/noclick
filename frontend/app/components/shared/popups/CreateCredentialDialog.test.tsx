// @vitest-environment jsdom
// Opening an account (the command palette's credential, a resource's Manage) shows the account when it works; a broken
// one, or a Reconnect, opens the Connect dialog on its way back in.
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { CredentialInfo } from '~/types/socket-events.generated';

const cache = vi.hoisted(() => ({ rows: [] as Partial<CredentialInfo>[] }));
const navigateToAccount = vi.hoisted(() => vi.fn());

vi.mock('~/utils/credentialAutoSelect', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/utils/credentialAutoSelect')>()),
    getAllCredentialsFromCache: () => cache.rows,
    prefetchCredentials: async () => undefined,
}));
// The catalog the picker lists is loaded at runtime; here it holds Stripe alone.
vi.mock('~/hooks/useServiceCredentialOptions', () => ({
    useServiceCredentialOptions: () => [
        { value: 'automation-stripe', label: 'Stripe', primaryCredentialType: 'stripe_api_key', acceptedCredentialTypes: ['stripe_api_key'], Icon: () => null, iconColor: '' },
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
