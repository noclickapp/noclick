// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
const state = vi.hoisted(() => ({ send: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('~/hooks/useCredentialOAuth', () => ({ useCredentialOAuth: () => ({ availableCredentials: [], loading: false, loadCredentials: vi.fn(), initiateOAuth: state.connect, oauthConnecting: null }) }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null, subscription_tier: null, isPersonalWorkspace: true }, vi.fn()] }));
vi.mock('~/components/workflow/OAuthCredentialForm', () => ({ OAuthCredentialForm: () => <div data-testid="oauth-route" /> }));
vi.mock('~/components/credential/OAuthConnectForm', () => ({ OAuthConnectForm: () => <div data-testid="oauth-route" /> }));
vi.mock('~/components/workflow/WhatsAppQRCredentialForm', () => ({ WhatsAppQRCredentialForm: () => null }));
vi.mock('~/components/workflow/MCPCredentialForm', () => ({ MCPCredentialForm: () => null }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));
const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');
const { loadNodeSchemas } = await import('~/utils/nodeSchemas');
beforeAll(() => loadNodeSchemas(['automation-123formbuilder']));
beforeEach(() => { state.send.mockClear(); state.connect.mockClear(); });
afterEach(cleanup);

it('mounts the native token family without OAuth', async () => {
    render(<NodeCredentials nodeType="automation-123formbuilder" onChange={vi.fn()} />);
    const token = await screen.findByLabelText(/API v2 token/i);
    expect(token.getAttribute('type')).toBe('password');
    expect(screen.queryByTestId('oauth-route')).toBeNull(); expect(state.connect).not.toHaveBeenCalled();
});

it('uses the actual shared/public form and submits the selected region with the token', () => {
    const save = vi.fn(async () => null);
    const fields = [
        { name: 'region', label: 'Account Region', type: 'select', required: true, options: [{ value: '', label: 'Choose region' }, { value: 'us', label: 'US' }, { value: 'eu', label: 'EU' }] },
        { name: 'token', label: 'API v2 Token', type: 'password', required: true },
    ];
    const { container } = render(<CredentialCreatePanel app="123FormBuilder" fields={fields} onSave={save} saveLabel="Provide" />);
    fireEvent.change(container.querySelector('[data-field="region"] select')!, { target: { value: 'eu' } });
    const input = container.querySelector('[data-field="token"] input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'synthetic-private-token' } });
    expect(input.type).toBe('password'); fireEvent.click(screen.getByRole('button', { name: 'Show secret' }));
    expect(input.type).toBe('text');
    fireEvent.click(screen.getByRole('button', { name: 'Provide' }));
    expect(save).toHaveBeenCalledWith('', { region: 'eu', token: 'synthetic-private-token' });
    expect(state.connect).not.toHaveBeenCalled(); expect(state.send).not.toHaveBeenCalled();
});
