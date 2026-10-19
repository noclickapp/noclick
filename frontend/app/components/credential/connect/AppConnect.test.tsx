// @vitest-environment jsdom
// A scanned or bought number is asked what it holds before it lands, as a sign-in is, and the form says it's checking
// meanwhile rather than sitting on the finished scan or purchase.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';

const probe = vi.hoisted(() => ({ resolve: undefined as unknown as (verification: CredentialTestConnectionResponse | null) => void }));

vi.mock('~/hooks/useConnectionProbe', () => ({
    probeConnection: vi.fn(() => new Promise<CredentialTestConnectionResponse | null>((resolve) => (probe.resolve = resolve))),
}));
vi.mock('~/hooks/useCredentialOAuth', () => ({
    useCredentialOAuth: () => ({
        availableCredentials: [],
        credentialTier: 'free',
        loadCredentials: async () => undefined,
        connect: vi.fn(),
        clearError: vi.fn(),
        planLimitError: null,
        error: null,
        isConnecting: false,
    }),
}));
vi.mock('~/components/workflow/WhatsAppQRCredentialForm', () => ({
    WhatsAppQRCredentialForm: ({ onCredentialCreated }: { onCredentialCreated: (id: string) => void }) => (
        <button type="button" onClick={() => onCredentialCreated('cred-qr')}>
            Scanned
        </button>
    ),
}));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({
    PhoneNumberPurchaseForm: ({ onCredentialCreated }: { onCredentialCreated: (id: string, number: string) => void }) => (
        <button type="button" onClick={() => onCredentialCreated('cred-number', '+14155550123')}>
            Bought
        </button>
    ),
}));

import { AppConnect } from './AppConnect';

afterEach(cleanup);

describe('AppConnect', () => {
    it.each([
        ['automation-whatsapp', 'WhatsApp', 'Scanned', 'Checking with WhatsApp…', 'cred-qr'],
        ['automation-phone', 'Phone', 'Bought', 'Checking your new number…', 'cred-number'],
    ])('checks a %s account before it lands', async (nodeType, app, finish, checking, id) => {
        const onConnected = vi.fn();
        render(<AppConnect nodeType={nodeType} app={app} ask={false} onConnected={onConnected} />);
        fireEvent.click(screen.getByRole('button', { name: finish }));

        expect(screen.getByRole('status').textContent).toBe(checking);
        expect(screen.queryByRole('button', { name: finish })).toBeNull();
        expect(onConnected).not.toHaveBeenCalled();

        await act(async () => probe.resolve({ success: true, reachable: true } as CredentialTestConnectionResponse));
        expect(onConnected).toHaveBeenCalledWith(expect.objectContaining({ id }), expect.objectContaining({ reachable: true }));
        expect(screen.queryByText(checking)).toBeNull();
    });
});
