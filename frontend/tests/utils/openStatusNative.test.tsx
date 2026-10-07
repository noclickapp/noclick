// @vitest-environment jsdom
// UNRUN native schema/selection and real mounted public credential privacy.
// The generated schema is an explicit future prerequisite; no mocks replace it.
import { render, cleanup, fireEvent, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OpenStatusNode } from '~/components/workflow/nodes/OpenStatusNode';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { NODE_SCHEMAS, getNodeCredentialInfo, filterConfigForExecution } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('valtio', () => ({ useSnapshot: () => ({ internalUser: false }) }));
vi.mock('~/lib/debugToolsState', () => ({ debugToolsState: {} }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null }] }));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));
vi.mock('~/utils/credentialIcons', () => ({ getCredentialIcon: () => ({ Icon: () => null }) }));
vi.mock('~/utils/oauthProviders', () => ({ getProviderConfig: (provider: string) => ({ name: provider, Icon: () => null }) }));
vi.mock('~/hooks/useCredentialOAuth', () => ({ useCredentialOAuth: () => ({
    availableCredentials: [], loading: false, loadCredentials: vi.fn(), connect: boundary.connect,
    connectOrgConsent: vi.fn(), isConnecting: false, connectingProvider: null, error: null,
    planLimitError: null, credentialTier: 'pro', clearError: vi.fn(), pendingSelection: null,
    resolvePendingSelection: vi.fn(), cancelConnect: vi.fn(),
}) }));
vi.mock('~/components/credential/OAuthConnectForm', () => ({ OAuthConnectForm: () => <div data-testid="oauth-route" /> }));
vi.mock('~/components/workflow/OAuthCredentialForm', () => ({ OAuthCredentialForm: () => null }));
vi.mock('~/components/workflow/WhatsAppQRCredentialForm', () => ({ WhatsAppQRCredentialForm: () => null }));
vi.mock('~/components/workflow/MCPCredentialForm', () => ({ MCPCredentialForm: () => null }));
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));
const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');
const { autoSelectCredentialFromCache, invalidateCredentialsCache, upsertCredentialsIntoCache, removeCredentialsFromCache } = await import('~/utils/credentialAutoSelect');
afterEach(() => { cleanup(); removeCredentialsFromCache(['synthetic-openstatus-own', 'synthetic-openstatus-other']); invalidateCredentialsCache(); vi.clearAllMocks(); });

it('wires exactly thirteen closed read operations and dependent page ancestry', () => {
    const schema: any = NODE_SCHEMAS['automation-openstatus'];
    expect(CREDENTIAL_TYPE_MAP.OpenStatusApiKeyCredential).toBe('openstatus_api_key');
    expect(getNodeCredentialInfo('automation-openstatus')?.acceptedTypes).toEqual(['openstatus_api_key']);
    expect(humanizeCredentialLabel('OpenStatusApiKey')).toBe('OpenStatus API Key');
    const operations = Object.values(schema.$defs).map((d: any) => d.properties?.operation?.const).filter(Boolean).sort();
    expect(operations).toEqual(['get_maintenance','get_monitor','get_monitor_status','get_monitor_summary','get_page_component',
        'get_page_components','get_page_overall_status','get_status_page','get_status_report','list_maintenances','list_monitors',
        'list_status_pages','list_status_reports']);
    const cfg: any = Object.values(schema.$defs).find((d: any) => d.properties?.operation?.const === 'get_page_component');
    expect(cfg.properties.component_id['x-dynamic-options'].depends_on).toEqual(['page_id']);
    expect(cfg.properties.include_names.default).toBe(false);
    const cred = schema.$defs.OpenStatusApiKeyCredential;
    expect(cred.required).toEqual(['api_key']);
    expect(cred.properties.api_key['ui:sensitive']).toBe(true);
    expect(cred['x-oauth-provider']).toBeUndefined();
    expect(cred.properties.refresh_token).toBeUndefined();
    expect(filterConfigForExecution('automation-openstatus', { operation: 'get_page_component', page_id: 'page-1',
        component_id: 'component-1', url: 'https://private.invalid', body: 'private', rpc: 'CreateMonitor' }))
        .toEqual({ operation: 'get_page_component', page_id: 'page-1', component_id: 'component-1' });
});

it('renders the unchanged official checked-in vector asset', () => {
    const { container } = render(<OpenStatusNode.Icon />);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/openstatus.svg');
});

it('selects only the owned current native key family through the actual cache', () => {
    invalidateCredentialsCache();
    upsertCredentialsIntoCache([{ id: 'synthetic-openstatus-other', name: 'Other', credential_type: 'slack_oauth', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-openstatus')).toEqual({});
    upsertCredentialsIntoCache([{ id: 'synthetic-openstatus-own', name: 'Native', credential_type: 'openstatus_api_key', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-openstatus')).toEqual({ openstatus_api_key: 'synthetic-openstatus-own' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('keeps the actual public provide key field private after revealing it', () => {
    const save = vi.fn().mockResolvedValue(null);
    const schema: any = NODE_SCHEMAS['automation-openstatus'];
    const { container } = render(<CredentialCreatePanel label="OpenStatus API Key" schema={schema.$defs.OpenStatusApiKeyCredential}
        fields={[{ name: 'api_key', label: 'API Key', type: 'password', required: true }]} onSave={save} hideName saveLabel="Provide" />);
    const input = container.querySelector('input[type=password]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'synthetic-private-key' } });
    expect(input.closest('.ph-mask.ph-no-capture')).not.toBeNull();
    fireEvent.click(input.closest('[data-field]')!.querySelector('button')!);
    expect(input.type).toBe('text'); expect(input.closest('.ph-mask.ph-no-capture')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Provide' }));
    expect(save).toHaveBeenCalledWith('', { api_key: 'synthetic-private-key' });
    expect(boundary.send).not.toHaveBeenCalled();
});

it('mounts the native editor credential form without OAuth or key issuance', async () => {
    render(<NodeCredentials nodeType="automation-openstatus" onChange={vi.fn()} />);
    const label = await screen.findByText('OpenStatus API Key', { exact: true });
    expect(label.closest('.ph-mask.ph-no-capture')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Create new' }));
    expect(document.querySelector('[data-field="api_key"] input')).not.toBeNull();
    expect(document.querySelector('[data-field="refresh_token"]')).toBeNull();
    expect(screen.queryByTestId('oauth-route')).toBeNull();
    expect(boundary.connect).not.toHaveBeenCalled();
});
