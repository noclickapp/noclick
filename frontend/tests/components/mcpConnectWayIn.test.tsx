// @vitest-environment happy-dom
// Connecting an app through its own MCP server (credential kind `mcp`, backend nodes/oauth/mcp_connect.py) is one way
// in on every surface: the node panel (NodeCredentials over AppConnect, on the socket) and a shared provide link
// (CredentialMethodConnect, over its HTTP transport). Both start the connect, open the sign-in, hear the callback on
// its state's channel (never another attempt's), and finish with the sealed flow.
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import {
    afterEach,
    beforeAll,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { oauthChannelName } from '~/lib/oauthChannel';
import { MCP_CALLBACK_TYPE } from '~/lib/mcpCallback';

const state = vi.hoisted(() => ({
    send: vi.fn(),
    popup: { location: { href: '' }, close: vi.fn() },
}));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: state.send }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));
vi.mock('~/lib/debugToolsState', () => ({ debugToolsState: {} }));
vi.mock('~/hooks/useOrgContext', () => ({
    useOrgContext: () => [{ id: null, role: null }],
}));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));
vi.mock('~/utils/credentialIcons', () => ({
    getCredentialIcon: () => ({ Icon: () => null }),
}));
vi.mock('~/utils/credentialAutoSelect', () => ({
    invalidateCredentialsCache: vi.fn(),
    removeCredentialsFromCache: vi.fn(),
    isInjectedDisplayCredential: () => false,
    isConnectionDropped: () => false,
}));
vi.mock('~/hooks/useCredentialOAuth', () => ({
    useCredentialOAuth: () => ({
        availableCredentials: [],
        loading: false,
        loadCredentials: vi.fn(),
        connect: vi.fn(),
        connectOrgConsent: vi.fn(),
        isConnecting: false,
        connectingProvider: null,
        error: null,
        planLimitError: null,
        credentialTier: 'pro',
        clearError: vi.fn(),
        pendingSelection: null,
        resolvePendingSelection: vi.fn(),
        cancelConnect: vi.fn(),
    }),
}));
vi.mock('~/components/workflow/CredentialRequestActions', () => ({
    CredentialRequestActions: () => null,
    AskSomeoneForm: () => null,
    INLINE_ACTION: '',
}));
vi.mock('~/components/shared/popups/DeleteConfirmPopup', () => ({
    DeleteConfirmPopup: () => null,
}));
vi.mock('~/components/shared/popups/ShareDialog', () => ({
    ShareDialog: () => null,
}));
vi.mock('~/components/utils/UpgradePopup', () => ({
    UpgradePopup: () => null,
}));

const { NodeCredentials } = await import(
    '~/components/workflow/NodeCredentials'
);
const { CredentialMethodConnect } = await import(
    '~/components/credential/CredentialMethodConnect'
);

const STATE = '7f37925e-dc12-42de-a2e2-4a8aa24bb33e';
const VERIFIED = {
    reachable: true,
    samples: [{ label: 'search_designs' }],
    noun: 'tools',
};

/** The sign-in window coming back: the callback route posts on the state's channel. */
function signedIn(state: string, code = 'the-code') {
    const channel = new BroadcastChannel(oauthChannelName('mcp', state));
    channel.postMessage({
        type: MCP_CALLBACK_TYPE,
        success: true,
        code,
        state,
    });
    channel.close();
}

beforeAll(async () => {
    await loadNodeSchemas(['automation-canva']);
});
beforeEach(() => {
    // As production shows it: a dev server also reveals a sign-in still under the provider's review.
    vi.stubEnv('DEV', false);
    state.send.mockReset();
    state.popup = { location: { href: '' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockImplementation(
        () => state.popup as unknown as Window
    );
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

describe('connecting through an app’s own MCP server', () => {
    it('is the node panel’s way into Canva while Canva’s own sign-in waits on its review', async () => {
        state.send.mockImplementation(async (event: { event_name: string }) => {
            if (event.event_name === 'credential:list')
                return { credentials: [] };
            if (event.event_name === 'mcp:connect:start')
                return {
                    success: true,
                    kind: 'oauth',
                    flow: 'sealed',
                    state: STATE,
                    authorization_url:
                        'https://www.canva.com/api/oauth/authorize?x=1',
                };
            if (event.event_name === 'mcp:connect:finish')
                return {
                    success: true,
                    credential: {
                        id: 'cred-mcp',
                        name: 'Canva (MCP)',
                        credential_type: 'canva_mcp',
                    },
                    verification: VERIFIED,
                };
            return {};
        });
        const onChange = vi.fn();
        render(
            <NodeCredentials nodeType="automation-canva" onChange={onChange} />
        );

        // No tab to pick: the MCP way is the one Canva offers now, and it says what it gives and doesn't.
        expect(
            await screen.findByText(
                /Through Canva's MCP server: agents get Canva's tools\. Workflow steps and triggers need Canva's own sign-in\./
            )
        ).toBeTruthy();
        fireEvent.click(
            screen.getByRole('button', { name: 'Continue with Canva' })
        );

        await waitFor(() =>
            expect(state.popup.location.href).toBe(
                'https://www.canva.com/api/oauth/authorize?x=1'
            )
        );
        expect(state.send).toHaveBeenCalledWith(
            expect.objectContaining({
                event_name: 'mcp:connect:start',
                credential_type: 'canva_mcp',
                redirect_uri: `${window.location.origin}/api/auth/mcp/callback`,
            })
        );
        expect(screen.getByText(/Finish in the Canva window\./)).toBeTruthy();

        // Another attempt's callback is not this one's.
        await act(async () => signedIn('00000000-0000-4000-8000-000000000000'));
        expect(state.send).not.toHaveBeenCalledWith(
            expect.objectContaining({ event_name: 'mcp:connect:finish' })
        );

        await act(async () => signedIn(STATE));
        await waitFor(() =>
            expect(state.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    event_name: 'mcp:connect:finish',
                    credential_type: 'canva_mcp',
                    flow: 'sealed',
                    code: 'the-code',
                    state: STATE,
                })
            )
        );
        await waitFor(() => expect(onChange).toHaveBeenCalled());
        expect(onChange.mock.calls.at(-1)?.[0]).toEqual(
            expect.objectContaining({ canva_mcp: 'cred-mcp' })
        );
    });

    it('runs over a provide link’s own endpoints, as the requester', async () => {
        const fetched: { url: string; body: Record<string, unknown> }[] = [];
        vi.stubGlobal(
            'fetch',
            vi.fn(async (url: string, init: RequestInit) => {
                const body = JSON.parse(String(init.body));
                fetched.push({ url, body });
                const answer = url.endsWith('/mcp/start')
                    ? {
                          kind: 'oauth',
                          flow: 'sealed',
                          state: STATE,
                          authorization_url:
                              'https://mcp.notion.com/authorize?x=1',
                      }
                    : {
                          status: 'success',
                          credential_id: 'cred-link',
                          verification: VERIFIED,
                      };
                return new Response(JSON.stringify(answer), { status: 200 });
            })
        );
        const onProvided = vi.fn();
        render(
            <CredentialMethodConnect
                method={{
                    credential_type: 'notion_mcp',
                    label: 'Notion MCP',
                    method_kind: 'mcp',
                    is_oauth: false,
                    credential_fields: [],
                    mcp_server: 'https://mcp.notion.com/mcp',
                }}
                apiBase="https://api.example"
                token="TOKEN"
                serviceName="Notion"
                onProvided={onProvided}
            />
        );
        fireEvent.click(
            screen.getByRole('button', { name: 'Continue with Notion' })
        );
        await waitFor(() =>
            expect(state.popup.location.href).toBe(
                'https://mcp.notion.com/authorize?x=1'
            )
        );
        expect(fetched[0]).toEqual({
            url: 'https://api.example/api/credential-request/TOKEN/mcp/start',
            body: {
                credential_type: 'notion_mcp',
                redirect_uri: `${window.location.origin}/api/auth/mcp/callback`,
            },
        });

        await act(async () => signedIn(STATE));
        await waitFor(() => expect(onProvided).toHaveBeenCalledWith(VERIFIED));
        expect(fetched[1]).toEqual({
            url: 'https://api.example/api/credential-request/TOKEN/mcp/finish',
            body: {
                credential_type: 'notion_mcp',
                flow: 'sealed',
                code: 'the-code',
                state: STATE,
            },
        });
    });

    it('says a refusal in the server’s words and opens nothing', async () => {
        state.send.mockImplementation(async (event: { event_name: string }) =>
            event.event_name === 'mcp:connect:start'
                ? {
                      success: false,
                      error: "Canva's MCP server refused NoClick's sign-in: Invalid redirect URI.",
                  }
                : { credentials: [] }
        );
        render(
            <NodeCredentials nodeType="automation-canva" onChange={vi.fn()} />
        );
        fireEvent.click(
            await screen.findByRole('button', { name: 'Continue with Canva' })
        );
        expect(
            await screen.findByText(
                "Canva's MCP server refused NoClick's sign-in: Invalid redirect URI."
            )
        ).toBeTruthy();
        expect(state.popup.close).toHaveBeenCalled();
    });

    it('asks for the key a server takes instead of a sign-in', async () => {
        state.send.mockImplementation(async (event: { event_name: string }) => {
            if (event.event_name === 'mcp:connect:start')
                return { success: true, kind: 'key', flow: 'sealed' };
            if (event.event_name === 'mcp:connect:finish')
                return {
                    success: true,
                    credential: {
                        id: 'cred-key',
                        name: 'Canva (MCP)',
                        credential_type: 'canva_mcp',
                    },
                    verification: VERIFIED,
                };
            return { credentials: [] };
        });
        const onChange = vi.fn();
        render(
            <NodeCredentials nodeType="automation-canva" onChange={onChange} />
        );
        fireEvent.click(
            await screen.findByRole('button', { name: 'Continue with Canva' })
        );
        const key = (await screen.findByPlaceholderText(
            'The key Canva gave you'
        )) as HTMLInputElement;
        expect(key.getAttribute('type')).toBe('password');
        fireEvent.change(key, { target: { value: 'sk-123' } });
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() =>
            expect(state.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    event_name: 'mcp:connect:finish',
                    flow: 'sealed',
                    api_key: 'sk-123',
                })
            )
        );
        await waitFor(() => expect(onChange).toHaveBeenCalled());
    });
});
