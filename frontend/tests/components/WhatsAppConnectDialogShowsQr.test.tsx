// @vitest-environment happy-dom
// Connect on Connections means "add an account": the WhatsApp QR shows at once, with the numbers already connected
// listed under it, rather than behind a second button. Each open starts one QR, which a re-render, StrictMode or a
// trip to the Token tab and back never starts again, and a reconnect still waits for its click. Linking makes nothing
// on its own: once the scan lands the dialog offers the number an agent, and Create makes it and opens its channel.
import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

const state = vi.hoisted(() => ({ credentials: [] as Partial<CredentialInfo>[], send: vi.fn(), navigateToTab: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('~/lib/navigation', async (importOriginal) => ({
    ...(await importOriginal<typeof import('~/lib/navigation')>()),
    navigateToTab: state.navigateToTab,
}));
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
        credentialTier: 'pro',
        loadCredentials: async () => undefined,
        connect: vi.fn(),
        clearError: vi.fn(),
        planLimitError: null,
        error: null,
        isConnecting: false,
    }),
}));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null }] }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));

import { GlobalCreateCredentialDialog, openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';

const working = { id: 'wa-1', name: 'Shop line', credential_type: 'whatsapp_qr', access_type: 'owner', created_at: '2026-11-01T00:00:00Z', connection_healthy: true };
const dead = { ...working, id: 'wa-dead', name: 'Old line', connection_healthy: false, connection_hint: 'WhatsApp phone link is dead (session failed).' };

const sent = (name: string) => state.send.mock.calls.map(([event]) => event).filter((e) => e?.event_name === name);

beforeAll(async () => {
    await loadNodeSchemas(['automation-whatsapp']);
    await import('~/components/shared/popups/ConnectAppStep');
}, 60_000);
beforeEach(() => {
    state.credentials = [];
    state.navigateToTab.mockReset();
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

    it('a reconnect of a dead number still waits for its click', async () => {
        state.credentials = [working, dead];
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr', credentialId: 'wa-dead', reconnect: true }));

        expect(await screen.findByRole('button', { name: 'Reconnect WhatsApp' }, { timeout: 5000 })).toBeTruthy();
        expect(sent('whatsapp:qr:start')).toEqual([]);
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();
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

    it('offers the linked number an agent once the scan lands, and Create makes it and opens its channel', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const agent = { agent_id: 'a-1', name: 'WhatsApp', channel_id: 'ch-1', channel_name: 'whatsapp' };
        state.send.mockImplementation(async (event: { event_name?: string }) => {
            if (event?.event_name === 'whatsapp:qr:start') return { success: true, connection_id: 'conn-1', qr_code: 'QR' };
            if (event?.event_name === 'whatsapp:qr:status') return { success: true, status: 'connected', credential_id: 'wa-new', phone_number: '+12025550101' };
            if (event?.event_name === 'whatsapp:agent:status') return { success: true, available: true, agent: null };
            if (event?.event_name === 'whatsapp:agent:create') return { success: true, created: true, agent };
            return { success: true, reachable: true, account_label: '+1 202 555 0101' };
        });
        render(<GlobalCreateCredentialDialog />);
        await act(async () => openCreateCredential({ credentialType: 'whatsapp_qr' }));
        await screen.findByAltText('WhatsApp QR Code', {}, { timeout: 5000 });
        await act(async () => vi.advanceTimersByTimeAsync(5000));

        expect(await screen.findByText('Put an agent on this number?', {}, { timeout: 5000 })).toBeTruthy();
        expect(screen.getByText('It answers your WhatsApp messages for you and lives in its own channel, where you tell it what to do.')).toBeTruthy();
        // The scan's poll names the connection alone, and nothing is made until they say yes.
        expect(sent('whatsapp:qr:status')[0]).toEqual({ event_name: 'whatsapp:qr:status', connection_id: 'conn-1' });
        expect(sent('whatsapp:agent:status')).toEqual([{ event_name: 'whatsapp:agent:status', credential_id: 'wa-new' }]);
        expect(sent('whatsapp:agent:create')).toEqual([]);

        fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
        await waitFor(() => expect(state.navigateToTab).toHaveBeenCalledWith('work', { show: 'home', channel: 'ch-1', thread: null }));
        expect(sent('whatsapp:agent:create')).toEqual([{ event_name: 'whatsapp:agent:create', credential_id: 'wa-new' }]);
        await waitFor(() => expect(document.querySelector('[data-testid="create-credential-dialog"][data-state="open"]')).toBeNull());
    });
});
