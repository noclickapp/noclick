// @vitest-environment happy-dom
// Connect on Connections means "add an account": the WhatsApp QR shows at once, with the numbers already connected
// listed under it, rather than behind a second button. Each open starts one QR, which a re-render, StrictMode or a
// trip to the Token tab and back never starts again; a dead number's reconnect repairs that number, and a node that
// can pick a working number shows no QR until "Connect another account" asks for one.
import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

const state = vi.hoisted(() => ({ credentials: [] as Partial<CredentialInfo>[], send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('~/utils/credentialAutoSelect', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/utils/credentialAutoSelect')>()),
    getAllCredentialsFromCache: () => state.credentials,
    prefetchCredentials: async () => undefined,
}));
vi.mock('~/hooks/useServiceCredentialOptions', () => ({
    useServiceCredentialOptions: () => [
        {
            value: 'automation-whatsapp',
            label: 'WhatsApp',
            primaryCredentialType: 'whatsapp_qr',
            acceptedCredentialTypes: ['whatsapp_qr', 'whatsapp_access_token'],
            Icon: () => null,
            iconColor: '',
            listed: true,
        },
    ],
}));
vi.mock('~/hooks/useCredentialOAuth', () => ({
    useCredentialOAuth: () => ({
        availableCredentials: state.credentials,
        loading: false,
        credentialTier: 'pro',
        loadCredentials: async () => undefined,
        connect: vi.fn(),
        connectOrgConsent: vi.fn(),
        connectingProvider: null,
        clearError: vi.fn(),
        planLimitError: null,
        error: null,
        isConnecting: false,
        pendingSelection: null,
        resolvePendingSelection: vi.fn(),
        cancelConnect: vi.fn(),
    }),
}));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null }] }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));

import { GlobalCreateCredentialDialog, openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import { NodeCredentials } from '~/components/workflow/NodeCredentials';

const working = { id: 'wa-1', name: 'Shop line', credential_type: 'whatsapp_qr', access_type: 'owner', created_at: '2026-11-01T00:00:00Z', connection_healthy: true };
const dead = { ...working, id: 'wa-dead', name: 'Old line', connection_healthy: false, connection_hint: 'WhatsApp phone link is dead (session failed).' };

const sent = (name: string) => state.send.mock.calls.map(([event]) => event).filter((e) => e?.event_name === name);

beforeAll(async () => {
    await loadNodeSchemas(['automation-whatsapp']);
    await import('~/components/shared/popups/ConnectAppStep');
}, 60_000);
beforeEach(() => {
    state.credentials = [];
    state.send.mockReset();
    state.send.mockImplementation(async (event: { event_name?: string }) =>
        event?.event_name === 'whatsapp:qr:start' ? { success: true, connection_id: 'conn-1', qr_code: 'QR' } : { success: true, status: 'scan_qr' }
    );
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('Connect WhatsApp from Connections', () => {
    it('shows a QR at once when a number is already connected, and lists that number under it', async () => {
        state.credentials = [working];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr' }));

        expect(await screen.findByAltText('WhatsApp QR Code', {}, { timeout: 5000 })).toBeTruthy();
        expect(sent('whatsapp:qr:start')).toEqual([{ event_name: 'whatsapp:qr:start' }]);
        expect(screen.queryByRole('button', { name: 'Connect a different WhatsApp number' })).toBeNull();
        expect(screen.getByText('Already connected')).toBeTruthy();
        expect(screen.getByText('Shop line')).toBeTruthy();
    });

    it('starts one QR per open, under StrictMode and across a trip to the Token tab and back', async () => {
        state.credentials = [working];
        render(
            <StrictMode>
                <GlobalCreateCredentialDialog />
            </StrictMode>
        );
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr' }));
        const qr = await screen.findByAltText('WhatsApp QR Code', {}, { timeout: 5000 });

        // Radix tabs select on mouse down.
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Token' }), { button: 0 });
        await waitFor(() => expect(screen.getByRole('tab', { name: 'Token' }).getAttribute('aria-selected')).toBe('true'));
        expect(qr.closest('[role="tabpanel"]')?.hasAttribute('hidden')).toBe(true);

        fireEvent.mouseDown(screen.getByRole('tab', { name: 'QR code' }), { button: 0 });
        await waitFor(() => expect(screen.getByRole('tab', { name: 'QR code' }).getAttribute('aria-selected')).toBe('true'));
        expect(screen.getByAltText('WhatsApp QR Code')).toBe(qr);
        expect(qr.closest('[role="tabpanel"]')?.hasAttribute('hidden')).toBe(false);
        expect(sent('whatsapp:qr:start')).toHaveLength(1);
    });

    it('a reconnect of a dead number repairs that number rather than adding one', async () => {
        state.credentials = [working, dead];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr', credentialId: 'wa-dead', reconnect: true }));

        expect(await screen.findByAltText('WhatsApp QR Code', {}, { timeout: 5000 })).toBeTruthy();
        expect(sent('whatsapp:qr:start')).toEqual([{ event_name: 'whatsapp:qr:start', reconnect_credential_id: 'wa-dead' }]);
    });

    it('closed while the QR loads, nothing polls for its scan', async () => {
        let answer: (value: unknown) => void = () => undefined;
        state.send.mockImplementation((event: { event_name?: string }) =>
            event?.event_name === 'whatsapp:qr:start' ? new Promise((resolve) => (answer = resolve)) : Promise.resolve({ success: true, status: 'scan_qr' })
        );
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr' }));
        await waitFor(() => expect(sent('whatsapp:qr:start')).toHaveLength(1), { timeout: 5000 });

        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        await waitFor(() => expect(screen.queryByText('Loading QR code...')).toBeNull());
        vi.useFakeTimers();
        await act(async () => answer({ success: true, connection_id: 'conn-1', qr_code: 'QR' }));
        await act(async () => vi.advanceTimersByTimeAsync(30_000));
        expect(sent('whatsapp:qr:status')).toEqual([]);
    });
});

// A node needs a number, and one that works can be picked: a QR shown beside it invites a re-scan that rebinds it.
// Asking to connect another is asking for one.
describe('a node with a working number', () => {
    it('mints nothing until Connect another account', async () => {
        state.credentials = [working];
        render(<NodeCredentials nodeType="automation-whatsapp" credentialIds={{ whatsapp_qr: 'wa-1' }} onChange={vi.fn()} />);
        const connect = await screen.findByRole('button', { name: 'Connect another account' });
        expect(sent('whatsapp:qr:start')).toEqual([]);
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();

        fireEvent.click(connect);
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
        expect(sent('whatsapp:qr:start')).toEqual([{ event_name: 'whatsapp:qr:start' }]);
    });

    // Picking among numbers already connected is no ask to add one: a revoked attached number beside a working one
    // opens the connect panel, but the QR waits behind its button.
    it('keeps its QR behind a button while it can pick one', async () => {
        state.credentials = [{ ...working, id: 'wa-revoked', name: 'Gone line', revoked_at: '2026-11-01T00:00:00Z' }, working];
        render(<NodeCredentials nodeType="automation-whatsapp" credentialIds={{ whatsapp_qr: 'wa-revoked' }} onChange={vi.fn()} />);
        expect(await screen.findByRole('button', { name: 'Connect a different WhatsApp number' })).toBeTruthy();
        expect(sent('whatsapp:qr:start')).toEqual([]);
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();
    });
});
