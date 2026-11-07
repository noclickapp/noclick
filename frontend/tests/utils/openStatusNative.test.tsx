// @vitest-environment happy-dom
// OpenStatus schema, native-key cache and mounted editor contracts.
// The real generated schemas keep registration and editor behavior in sync.
import { render, cleanup, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { OpenStatusNode } from '~/components/workflow/nodes/OpenStatusNode';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('valtio', async (importOriginal) => ({ ...await importOriginal<typeof import('valtio')>(), useSnapshot: () => ({ internalUser: false, configured: [] }) }));
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
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null, INLINE_ACTION: '' }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));
const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');
const { invalidateCredentialsCache, upsertCredentialsIntoCache, removeCredentialsFromCache } = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
await loadAllNodeSchemas();
afterEach(() => { cleanup(); removeCredentialsFromCache(['synthetic-openstatus-own', 'synthetic-openstatus-other']); invalidateCredentialsCache(); vi.clearAllMocks(); });

it('wires exactly thirteen closed read operations and dependent page ancestry', () => {
    const schema: any = NODE_SCHEMAS['automation-openstatus'];
    expect(CREDENTIAL_TYPE_MAP.OpenStatusApiKeyCredential).toBe('openstatus_api_key');
    expect(getNodeCredentialInfo('automation-openstatus')?.acceptedTypes).toEqual(['openstatus_api_key']);
    expect(humanizeCredentialLabel('OpenStatusApiKey')).toBe('Open Status API Key');
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
    for (const field of ['url', 'body', 'rpc']) expect(cfg.properties).not.toHaveProperty(field);
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

it('mounts the native editor credential form without OAuth or key issuance', async () => {
    render(<NodeCredentials nodeType="automation-openstatus" onChange={vi.fn()} />);
    const input = await screen.findByLabelText('API key');
    expect(input.getAttribute('type')).toBe('password');
    expect(screen.getByRole('button', { name: 'Connect' })).toBeTruthy();
    expect(document.querySelector('[data-field="api_key"] input')).not.toBeNull();
    expect(document.querySelector('[data-field="refresh_token"]')).toBeNull();
    expect(screen.queryByTestId('oauth-route')).toBeNull();
    expect(boundary.connect).not.toHaveBeenCalled();
});
