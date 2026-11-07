// @vitest-environment happy-dom
// Renders the real native Secret Key form and optional protected product witness.
// Account/socket boundaries are synthetic; editing does not authenticate a provider or prove project identity.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import schema from '~/schemas/nodes/qonversion.json';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

const state = vi.hoisted(() => ({ credentials: [] as any[], flags: [] as string[], send: vi.fn(), connect: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => state.flags }));
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
vi.mock('~/components/workflow/CredentialRequestActions', () => ({ CredentialRequestActions: () => null, INLINE_ACTION: '' }));
vi.mock('~/components/credential/PhoneNumberPurchaseForm', () => ({ PhoneNumberPurchaseForm: () => null }));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({ DeleteConfirmPopup: () => null }));
vi.mock('~/components/shared/popups/ShareDialog', () => ({ ShareDialog: () => null }));
vi.mock('~/components/utils/UpgradePopup', () => ({ UpgradePopup: () => null }));

const { NodeCredentials } = await import('~/components/workflow/NodeCredentials');

beforeAll(async () => { await loadNodeSchemas(['automation-qonversion']); });
beforeEach(()=>{state.credentials=[];state.flags=[];state.send.mockClear();state.connect.mockClear();});
afterEach(()=>{cleanup();vi.unstubAllEnvs();});

describe('actual Qonversion credential form',()=>{
    it('selects the native Secret Key family and renders password/witness without an SDK OAuth route',async()=>{
        state.credentials=[{id:'foreign',name:'Foreign',credential_type:'slack_oauth'},{id:'qon-native',name:'Fixture Qonversion',credential_type:'qonversion_secret_key'}];
        const onChange=vi.fn();
        render(<NodeCredentials nodeType="automation-qonversion" onChange={onChange}/>);
        fireEvent.click(await screen.findByTestId('credential-dropdown'));
        expect(screen.queryByRole('button',{name:'Foreign'})).toBeNull();
        fireEvent.click(await screen.findByRole('button',{name:'Fixture Qonversion'}));
        expect(onChange.mock.calls.at(-1)?.[0]).toEqual({qonversion_secret_key:'qon-native'});
        fireEvent.click(screen.getByRole('button',{name:'Connect another account'}));
        const secret=document.querySelector('[data-field="secret_key"] input') as HTMLInputElement;
        expect(secret.getAttribute('type')).toBe('password');
        fireEvent.change(secret,{target:{value:'sk_synthetic_form_key'}});
        fireEvent.click(screen.getByRole('button',{name:'More options'}));
        expect(document.querySelector('[data-field="witness_product_id"]')).not.toBeNull();
        expect(document.querySelector('[data-field="credential_type"]')).toBeNull();
        expect(screen.queryByTestId('oauth-route')).toBeNull();
        expect(schema.$defs.QonversionSecretKeyCredential['x-credential-instructions']).toContain('not project/account identity');
        expect(state.send).not.toHaveBeenCalled();expect(state.connect).not.toHaveBeenCalled();
    });
});
