// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
const state = vi.hoisted(() => ({ send: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('~/lib/analyticsClient', () => ({ useAnalyticsActiveFeatureFlags: () => [] }));
vi.mock('~/hooks/useCredentialOAuth', () => ({ useCredentialOAuth: () => ({ credentials: [], loading: false, fetchCredentials: vi.fn(), fetchAllCredentials: vi.fn(), initiateOAuth: state.connect, oauthConnecting: null }) }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => ({ orgId: null, orgs: [], isOrgAdmin: false }) }));
vi.mock('~/components/workflow/OAuthCredentialForm', () => ({ OAuthCredentialForm: () => <div data-testid="oauth-route" /> }));
vi.mock('~/components/credential/OAuthConnectForm', () => ({ OAuthConnectForm: () => <div data-testid="oauth-route" /> }));
vi.mock('~/components/workflow/WhatsAppQRCredentialForm', () => ({ WhatsAppQRCredentialForm: () => null }));
vi.mock('~/components/workflow/MCPCredentialForm', () => ({ MCPCredentialForm: () => null }));
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));
const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');
const { NODE_SCHEMAS } = await import('~/utils/nodeSchemas');
beforeEach(() => { state.send.mockClear(); state.connect.mockClear(); });
afterEach(cleanup);

it('mounts the native token family with provider-scoped capture exclusion and no OAuth', async () => {
    const { container } = render(<NodeCredentials nodeType="automation-123formbuilder" onChange={vi.fn()} />);
    await screen.findByText('123FormBuilder Token', { exact: true });
    expect(container.firstElementChild?.classList.contains('ph-mask')).toBe(true);
    expect(container.firstElementChild?.classList.contains('ph-no-capture')).toBe(true);
    expect(screen.queryByTestId('oauth-route')).toBeNull(); expect(state.connect).not.toHaveBeenCalled();
});

it('uses the actual shared/public form and keeps the revealed token excluded while submitting the selected region', () => {
    const schema: any = (NODE_SCHEMAS['automation-123formbuilder'] as any).$defs.FormBuilder123TokenCredential;
    const save = vi.fn(async () => null);
    const fields = [
        { name: 'region', label: 'Account Region', type: 'select', required: true, options: [{ value: '', label: 'Choose region' }, { value: 'us', label: 'US' }, { value: 'eu', label: 'EU' }] },
        { name: 'token', label: 'API v2 Token', type: 'password', required: true },
    ];
    const { container } = render(<CredentialCreatePanel label="123FormBuilder" schema={schema} fields={fields} hideName onSave={save} saveLabel="Provide" />);
    fireEvent.change(container.querySelector('[data-field="region"] select')!, { target: { value: 'eu' } });
    const input = container.querySelector('[data-field="token"] input') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'synthetic-private-token' } });
    expect(input.type).toBe('password'); fireEvent.click(screen.getByRole('button', { name: 'Show secret' }));
    expect(input.type).toBe('text'); expect(input.closest('.ph-mask.ph-no-capture')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Provide' }));
    expect(save).toHaveBeenCalledWith('', { region: 'eu', token: 'synthetic-private-token' });
    expect(state.connect).not.toHaveBeenCalled(); expect(state.send).not.toHaveBeenCalled();
});
