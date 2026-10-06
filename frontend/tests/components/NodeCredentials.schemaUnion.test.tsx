// @vitest-environment jsdom
// Renders the real credential panel and manual field components with generated provider definitions.
// Saved credential selection and OAuth routing are inspected with account/socket boundaries stubbed; no provider operation or browser is used.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { dripCredentialSchema, mauticCredentialSchema } from '../fixtures/credentialUnionSchemas';

const state = vi.hoisted(() => ({ credentials: [] as any[], flags: [] as string[], send: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => state.flags }));
vi.mock('valtio', () => ({ useSnapshot: () => ({ internalUser: false }) }));
vi.mock('~/lib/debugToolsState', () => ({ debugToolsState: {} }));
vi.mock('~/hooks/useOrgContext', () => ({ useOrgContext: () => [{ id: null, role: null }] }));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));
vi.mock('~/utils/credentialIcons', () => ({ getCredentialIcon: () => ({ Icon: () => null }) }));
vi.mock('~/utils/oauthProviders', () => ({ getProviderConfig: (provider: string) => ({ name: provider, Icon: () => null }) }));
vi.mock('~/utils/credentialAutoSelect', () => ({
    invalidateCredentialsCache: vi.fn(), removeCredentialsFromCache: vi.fn(),
    isInjectedDisplayCredential: () => false, isConnectionDropped: () => false,
}));
vi.mock('~/hooks/useCredentialOAuth', () => ({ useCredentialOAuth: () => ({
    availableCredentials: state.credentials, loading: false, loadCredentials: vi.fn(),
    connect: state.connect, connectOrgConsent: vi.fn(), isConnecting: false,
    connectingProvider: null, error: null, planLimitError: null, credentialTier: 'pro',
    clearError: vi.fn(), pendingSelection: null, resolvePendingSelection: vi.fn(), cancelConnect: vi.fn(),
}) }));
vi.mock('~/components/credential/OAuthConnectForm', () => ({ OAuthConnectForm: (props: any) => (
    <div data-testid="oauth-route" data-provider={props.provider} data-type={props.credentialType} data-scopes={JSON.stringify(props.scopes)} />
) }));
vi.mock('~/components/workflow/OAuthCredentialForm', () => ({ OAuthCredentialForm: () => null }));
vi.mock('~/components/workflow/WhatsAppQRCredentialForm', () => ({ WhatsAppQRCredentialForm: () => null }));
vi.mock('~/components/workflow/MCPCredentialForm', () => ({ MCPCredentialForm: () => null }));
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));

const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');
const { NODE_SCHEMAS } = await import('~/utils/nodeSchemas');
const fixtureType = 'automation-credential-union-render-fixture';

beforeEach(() => { state.credentials = []; state.flags = []; state.send.mockClear(); state.connect.mockClear(); });
afterEach(() => { cleanup(); delete NODE_SCHEMAS[fixtureType]; vi.unstubAllEnvs(); });

function row(label: string) {
    const element = screen.getByText(label, { exact: true }).closest('.space-y-2');
    if (!element) throw new Error(`Missing credential row: ${label}`);
    return within(element as HTMLElement);
}

describe('NodeCredentials nested generated unions', () => {
    it('renders both Drip methods, keeps OAuth routing, and selects by the real discriminator', async () => {
        const schema = JSON.parse(JSON.stringify(dripCredentialSchema));
        schema.properties.credentials.anyOf[0].oneOf.reverse();
        NODE_SCHEMAS[fixtureType] = schema;
        state.credentials = [
            { id: 'saved-oauth', name: 'Saved OAuth', credential_type: 'drip_oauth' },
            { id: 'saved-token', name: 'Saved API token', credential_type: 'drip_api_token' },
        ];
        const onChange = vi.fn();
        render(<NodeCredentials nodeType={fixtureType} credentialIds={{ drip_oauth: 'saved-oauth', stale_other_type: 'foreign' }} onChange={onChange} />);
        await screen.findByText('Drip API Token', { exact: true });
        expect(screen.getAllByTestId('credential-dropdown')).toHaveLength(2);
        expect(screen.getAllByTestId('credential-dropdown')[0]).toBe(row('Drip OAuth').getByTestId('credential-dropdown'));
        expect(screen.queryByText('No credentials needed')).toBeNull();
        const oauth = screen.getByTestId('oauth-route');
        expect(oauth.getAttribute('data-provider')).toBe('drip');
        expect(oauth.getAttribute('data-type')).toBe('drip_oauth');
        expect(oauth.getAttribute('data-scopes')).toBe('["public"]');
        fireEvent.click(row('Drip API Token').getByTestId('credential-dropdown'));
        fireEvent.click(await row('Drip API Token').findByRole('button', { name: 'Saved API token' }));
        expect(onChange).toHaveBeenLastCalledWith(
            { drip_oauth: 'saved-oauth', drip_api_token: 'saved-token' },
            { 'saved-token': { id: 'saved-token', name: 'Saved API token', credential_type: 'drip_api_token' } },
        );
        fireEvent.click(row('Drip API Token').getByRole('button', { name: 'Create another' }));
        expect(row('Drip API Token').getByText('API Token', { exact: true })).toBeTruthy();
        expect(document.querySelector('[data-field="api_token"] input')?.getAttribute('type')).toBe('password');
        expect(document.querySelector('[data-field="credential_type"]')).toBeNull();
        expect(state.send).not.toHaveBeenCalled();
        expect(state.connect).not.toHaveBeenCalled();
    });

    it('renders Mautic manual OAuth2 fields and selects its saved credential without an OAuth popup', async () => {
        NODE_SCHEMAS[fixtureType] = mauticCredentialSchema;
        state.credentials = [{ id: 'saved-mautic', name: 'Saved Mautic user token', credential_type: 'mautic_oauth2' }];
        const onChange = vi.fn();
        render(<NodeCredentials nodeType={fixtureType} onChange={onChange} />);
        await screen.findByText('Mautic OAuth2', { exact: true });
        expect(screen.getByText('Mautic Basic', { exact: true })).toBeTruthy();
        expect(screen.queryByTestId('oauth-route')).toBeNull();
        fireEvent.click(row('Mautic OAuth2').getByTestId('credential-dropdown'));
        fireEvent.click(await row('Mautic OAuth2').findByRole('button', { name: 'Saved Mautic user token' }));
        expect(onChange.mock.calls.at(-1)?.[0]).toEqual({ mautic_oauth2: 'saved-mautic' });
        fireEvent.click(row('Mautic OAuth2').getByRole('button', { name: 'Create another' }));
        expect(row('Mautic OAuth2').getByText('Client Secret', { exact: true })).toBeTruthy();
        expect(document.querySelector('[data-field="refresh_token"] input')?.getAttribute('type')).toBe('password');
        expect(row('Mautic OAuth2').getByText('Mautic Installation URL', { exact: true })).toBeTruthy();
        expect(state.send).not.toHaveBeenCalled();
        expect(state.connect).not.toHaveBeenCalled();
    });

    it('keeps hidden nested alternatives out and shows a valid inline method beside malformed leaves', async () => {
        const leaf = dripCredentialSchema.$defs.DripAPITokenCredential;
        NODE_SCHEMAS[fixtureType] = { properties: { credentials: { anyOf: [
            { oneOf: [{ ...leaf, 'x-credential-hidden': true }, { ...leaf, title: 42 }, { ...leaf, description: {} }, { ...leaf, 'x-oauth-provider': 42 }] },
            { ...mauticCredentialSchema.$defs.MauticBasicCredential }, { type: 'null' },
        ] } } };
        render(<NodeCredentials nodeType={fixtureType} />);
        await screen.findByText('Mautic Basic', { exact: true });
        expect(screen.queryByText('Drip API Token', { exact: true })).toBeNull();
        expect(row('Mautic Basic').getByRole('button', { name: 'Create new' })).toBeTruthy();
        expect(state.send).not.toHaveBeenCalled();
    });

    it.each([false, true])('preserves preview-flag visibility for a nested credential (enabled=%s)', async enabled => {
        vi.stubEnv('DEV', false);
        state.flags = enabled ? ['credential-preview'] : [];
        NODE_SCHEMAS[fixtureType] = { properties: { credentials: { anyOf: [{ oneOf: [
            { ...dripCredentialSchema.$defs.DripAPITokenCredential, 'x-credential-hidden': true, 'x-credential-preview-flag': 'credential-preview' },
            mauticCredentialSchema.$defs.MauticBasicCredential,
        ] }, { type: 'null' }] } } };
        render(<NodeCredentials nodeType={fixtureType} />);
        await screen.findByText('Mautic Basic', { exact: true });
        expect(Boolean(screen.queryByText('Drip API Token', { exact: true }))).toBe(enabled);
        expect(state.send).not.toHaveBeenCalled();
    });

    it.each(['ref', 'inline'])('preserves existing direct-model visibility semantics (%s)', async shape => {
        const leaf = { ...mauticCredentialSchema.$defs.MauticBasicCredential, 'x-credential-hidden': true };
        NODE_SCHEMAS[fixtureType] = { $defs: { Leaf: leaf }, properties: {
            credentials: shape === 'ref' ? { $ref: '#/$defs/Leaf' } : leaf,
        } };
        render(<NodeCredentials nodeType={fixtureType} />);
        await screen.findByText('Mautic Basic', { exact: true });
        expect(row('Mautic Basic').getByRole('button', { name: 'Create new' })).toBeTruthy();
    });
});
