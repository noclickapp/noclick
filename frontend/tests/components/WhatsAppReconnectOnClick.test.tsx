// @vitest-environment happy-dom
// The WhatsApp node's credential panel through the real AppConnect and QR form. A reconnect restarts the failed
// session at WAHooks, which logs the phone out, so opening a node whose number died must never start one: only the
// Reconnect click does. A QR shows unasked only when the user has no number at all.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

const state = vi.hoisted(() => ({ credentials: [] as Record<string, unknown>[], send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));
vi.mock('~/lib/debugToolsState', () => ({ debugToolsState: {} }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null }] }));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));
vi.mock('~/utils/credentialIcons', () => ({ getCredentialIcon: () => ({ Icon: () => null }) }));
vi.mock('~/utils/oauthProviders', () => ({ getProviderConfig: (provider: string) => ({ name: provider, Icon: () => null }) }));
vi.mock('~/utils/credentialAutoSelect', () => ({
    invalidateCredentialsCache: vi.fn(), removeCredentialsFromCache: vi.fn(), isInjectedDisplayCredential: () => false,
    isConnectionDropped: (c: { connection_healthy?: boolean | null }) => c.connection_healthy === false,
}));
vi.mock('~/hooks/useCredentialOAuth', () => ({ useCredentialOAuth: () => ({
    availableCredentials: state.credentials, loading: false, loadCredentials: vi.fn(),
    connect: vi.fn(), connectOrgConsent: vi.fn(), isConnecting: false,
    connectingProvider: null, error: null, planLimitError: null, credentialTier: 'pro',
    clearError: vi.fn(), pendingSelection: null, resolvePendingSelection: vi.fn(), cancelConnect: vi.fn(),
}) }));
vi.mock('~/components/credential/OAuthConnectForm', () => ({ OAuthConnectForm: () => null }));
vi.mock('~/components/workflow/OAuthCredentialForm', () => ({ OAuthCredentialForm: () => null }));
vi.mock('~/components/workflow/MCPCredentialForm', () => ({ MCPCredentialForm: () => null }));
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null, INLINE_ACTION: '' }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));

const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');

const qrStarts = () => state.send.mock.calls.map(([event]) => event).filter((e) => e?.event_name === 'whatsapp:qr:start');
const dead = { id: 'wa-dead', name: 'WhatsApp +1 555 0100', credential_type: 'whatsapp_qr', access_type: 'owner', connection_healthy: false, connection_hint: 'WhatsApp phone link is dead (session failed).' };

beforeAll(async () => { await loadNodeSchemas(['automation-whatsapp']); });
beforeEach(() => {
    state.credentials = [];
    state.send.mockReset();
    state.send.mockImplementation(async (event: { event_name?: string }) =>
        event?.event_name === 'whatsapp:qr:start' ? { success: true, connection_id: 'conn-1', qr_code: 'QR' } : { success: true });
});
afterEach(cleanup);

describe('WhatsApp reconnect starts only on a click', () => {
    it('opening a node whose attached number died shows Reconnect and starts nothing', async () => {
        state.credentials = [dead];
        render(<NodeCredentials nodeType="automation-whatsapp" credentialIds={{ whatsapp_qr: 'wa-dead' }} onChange={vi.fn()} />);
        const button = await screen.findByRole('button', { name: 'Reconnect WhatsApp' });
        expect(screen.getByText('Shows a new QR code to scan with the same phone.')).toBeTruthy();
        expect(qrStarts()).toEqual([]);
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();

        fireEvent.click(button);
        await waitFor(() => expect(qrStarts()).toEqual([{ event_name: 'whatsapp:qr:start', reconnect_credential_id: 'wa-dead' }]));
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
    });

    it('a dead number that is not attached keeps the panel from minting a QR unasked', async () => {
        state.credentials = [dead];
        render(<NodeCredentials nodeType="automation-whatsapp" onChange={vi.fn()} />);
        fireEvent.click(await screen.findByRole('button', { name: 'Connect another account' }));
        expect(await screen.findByRole('button', { name: 'Connect a different WhatsApp number' })).toBeTruthy();
        expect(qrStarts()).toEqual([]);
    });

    it('with no WhatsApp number at all, the QR shows straight away (a fresh connection, no reconnect)', async () => {
        render(<NodeCredentials nodeType="automation-whatsapp" onChange={vi.fn()} />);
        expect(await screen.findByAltText('WhatsApp QR Code')).toBeTruthy();
        expect(qrStarts()).toEqual([{ event_name: 'whatsapp:qr:start' }]);
    });
});
