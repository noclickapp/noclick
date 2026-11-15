// @vitest-environment happy-dom
// The accounts the coordinator asks to connect in a turn are one card, a row each, connected in the chat and never in
// a new tab: each row runs the coordinator's own credential request (the token in the tool's link). A sign-in connects
// straight from its row, in a popup window whose result the request exchanges; a key or a QR code opens the Connections
// dialog drawn over the same request, so a key is judged and saved by the request and a QR code is minted only when
// asked for. A row is in on the request's own result: the save's reply here, or the credential_request:fulfilled frame
// the backend sends the owner's user room (fed here exactly as the relay delivers it: the event's JSON with its name as
// `type`). Once every row is in, the card folds to one line.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CredentialInfo } from '~/types/socket-events.generated';

const store = vi.hoisted(() => ({ credentials: [] as CredentialInfo[], loaded: true }));

// The account's credentials, re-read whenever the app announces a change (as the real list does); `loaded` turns
// true once the first read answered.
vi.mock('~/hooks/useCachedCredentialList', async () => {
    const { CREDENTIALS_CHANGED_EVENT } = await import('~/components/shared/popups/CreateCredentialDialog');
    return {
        useCredentialList: () => {
            const [list, setList] = useState({ credentials: store.credentials, loaded: store.loaded });
            useEffect(() => {
                const reread = () => setList({ credentials: [...store.credentials], loaded: store.loaded });
                window.addEventListener(CREDENTIALS_CHANGED_EVENT, reread);
                return () => window.removeEventListener(CREDENTIALS_CHANGED_EVENT, reread);
            }, []);
            return list;
        },
    };
});
vi.mock('~/components/shell/connections/accounts', () => ({
    useCatalogServices: () => [
        { value: 'automation-whatsapp', label: 'WhatsApp', primaryCredentialType: 'whatsapp_qr', acceptedCredentialTypes: ['whatsapp_qr', 'whatsapp_access_token'] },
        { value: 'automation-stripe', label: 'Stripe', primaryCredentialType: 'stripe_api_key', acceptedCredentialTypes: ['stripe_api_key', 'stripe_oauth'] },
        { value: 'automation-linear', label: 'Linear', primaryCredentialType: 'linear_oauth', acceptedCredentialTypes: ['linear_oauth', 'linear_pat'] },
        { value: 'automation-instagram', label: 'Instagram', primaryCredentialType: 'instagram_oauth', acceptedCredentialTypes: ['instagram_oauth', 'instagram_login'] },
        { value: 'automation-supabase', label: 'Supabase', primaryCredentialType: 'supabase_oauth', acceptedCredentialTypes: ['supabase_oauth', 'supabase_api_key'] },
        { value: 'automation-twilio', label: 'Twilio', primaryCredentialType: 'twilio_api_key', acceptedCredentialTypes: ['twilio_api_key'] },
        { value: 'automation-gmail', label: 'Gmail', primaryCredentialType: 'google_gmail_oauth', acceptedCredentialTypes: ['google_gmail_oauth'] },
    ],
}));

import { TurnCards } from '~/components/coordinator/toolCards';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

// Each ask's request: its token (and so its provide URL) and its id.
const A = { token: 'a'.repeat(64), request: '6f1c2d3e-4b5a-4968-8776-1a2b3c4d5e6f' };
const B = { token: 'b'.repeat(64), request: '7a2d3e4f-5c6b-4a79-9887-2b3c4d5e6f70' };
const C = { token: 'c'.repeat(64), request: '8b3e4f50-6d7c-4b8a-a998-3c4d5e6f7081' };
type Ask = typeof A;

const provideUrl = (ask: Ask) => `https://noclick.com/credential/provide/${ask.token}`;

function connectCall(credentialType: string, ask: Ask = A, id = 'step-1', message = 'So I can work in it for you.'): CoordinatorToolCall {
    return {
        id,
        tool: 'connect_credential',
        args: { credential_type: credentialType, message },
        result: { status: 'pending', request_id: ask.request, url: provideUrl(ask), auto_resume: true },
        running: false,
        startedAt: Date.now() - 5_000,
    };
}

// The request as GET /credential-request/{token} answers it.
function details(credentialType: string, methods: Record<string, unknown>[]) {
    return {
        credential_type: credentialType, requester_name: 'Dhruv', requester_email: 'owner@example.com', message: 'Connect it',
        is_oauth: false, requires_pkce: false, credential_fields: [], available_methods: methods, status: 'pending', expires_at: '',
    };
}

const method = (credential_type: string, label: string, method_kind: string, more: Record<string, unknown> = {}) => ({
    credential_type, label, method_kind, is_oauth: method_kind === 'oauth', credential_fields: [], ...more,
});

const TWILIO_KEY = method('twilio_api_key', 'TwilioApiKey', 'api_key', {
    credential_url: 'https://console.twilio.com',
    credential_fields: [
        { name: 'account_sid', label: 'Account SID', type: 'text', required: true },
        { name: 'api_key_secret', label: 'API key secret', type: 'password', required: true },
    ],
});
const LINEAR_SIGN_IN = method('linear_oauth', 'LinearOAuth', 'oauth', { oauth_provider: 'linear', oauth_scopes: ['read', 'write'] });
const GMAIL_SIGN_IN = method('google_gmail_oauth', 'Gmail', 'oauth', { oauth_provider: 'google', oauth_scopes: ['https://www.googleapis.com/auth/gmail.modify'] });

type Route = (init?: RequestInit) => Response;
let routes: Record<string, Route>;
let fetcher: ReturnType<typeof vi.fn>;
let socket: MockSocket;
let teardown: () => void;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** Answer `METHOD /credential-request/{token}{path}` for one ask's request. */
function on(verb: string, path: string, route: Route, ask: Ask = A) {
    routes[`${verb} ${ask.token}${path}`] = route;
}

function requests(path: string, ask: Ask = A): RequestInit[] {
    return fetcher.mock.calls.filter(([url]) => String(url).endsWith(`/api/credential-request/${ask.token}${path}`)).map(([, init]) => init as RequestInit);
}

// The card's forms load on demand; load them once up front so each test waits on the card, not the bundler.
beforeAll(async () => {
    await import('~/components/coordinator/cards/ConnectRequest');
}, 60_000);

beforeEach(() => {
    store.credentials = [];
    store.loaded = true;
    routes = {};
    fetcher = vi.fn(async (url: string, init?: RequestInit) => {
        // A self-hosted instance's OAuth app for a provider, as GET /api/public/oauth-app/{provider} answers it.
        const app = /\/api\/public\/oauth-app\/([^/?#]+)/.exec(String(url))?.[1];
        const [, rest = String(url)] = String(url).split('/api/credential-request/');
        const key = app ? `GET oauth-app:${app}` : `${init?.method ?? 'GET'} ${rest}`;
        const route = routes[key];
        if (!route) throw new Error(`Unexpected request: ${key}`);
        return route(init);
    });
    vi.stubGlobal('fetch', fetcher);
    vi.stubGlobal('open', vi.fn(() => ({ closed: false, close: vi.fn() })));
    ({ socket, teardown } = installMockSocket());
});
afterEach(() => {
    cleanup();
    teardown();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

function show(...calls: CoordinatorToolCall[]) {
    return render(<TurnCards calls={calls} />);
}

const rowOf = (name: string) => screen.getByTestId(`connect-row:${name}`);
const dialog = () => screen.queryByTestId('coordinator-connect-dialog');

function credential(fields: Partial<CredentialInfo>): CredentialInfo {
    return { id: 'cred-1', name: 'Account', credential_type: 'whatsapp_qr', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...fields } as CredentialInfo;
}

/** A row's button, once the row has read its request (the row drawn before that is replaced). */
const buttonIn = (name: string, label: string) => waitFor(() => within(rowOf(name)).getByRole('button', { name: label }));

async function signInLinear() {
    const signIn = await buttonIn('Linear', 'Sign in');
    await act(async () => fireEvent.click(signIn));
}

async function linearCallback() {
    await act(async () => {
        window.dispatchEvent(new MessageEvent('message', {
            origin: window.location.origin,
            data: { type: 'linear-oauth-callback', success: true, code: 'code-1', redirectUri: 'https://noclick.com/api/auth/linear/callback', scopes: ['read', 'write'] },
        }));
    });
}

describe('a turn’s accounts to connect', () => {
    function threeAsks() {
        on('GET', '', () => json(details('twilio_api_key', [TWILIO_KEY])), A);
        on('GET', '', () => json(details('linear_oauth', [LINEAR_SIGN_IN])), B);
        on('GET', '', () => json(details('google_gmail_oauth', [GMAIL_SIGN_IN])), C);
        return [connectCall('twilio_api_key', A, 'step-1'), connectCall('linear_oauth', B, 'step-2'), connectCall('google_gmail_oauth', C, 'step-3')];
    }

    it('are one card, a row each with how it connects and its one button', async () => {
        show(...threeAsks());
        await buttonIn('Gmail', 'Sign in');
        expect(screen.getAllByTestId('coordinator-connect')).toHaveLength(1);
        expect(screen.getByText('Connect 3 accounts')).toBeTruthy();
        expect(screen.getByText('0 of 3 done')).toBeTruthy();
        expect(within(rowOf('Twilio')).getByText(/^API key$/i)).toBeTruthy();
        expect(within(rowOf('Twilio')).getByRole('button', { name: 'Add key' })).toBeTruthy();
        expect(within(rowOf('Linear')).getByText('Sign in with Linear')).toBeTruthy();
        expect(within(rowOf('Gmail')).getByText('Sign in with Google')).toBeTruthy();
        // Nothing is open, minted or saved by drawing the card, and nothing on it leaves the chat.
        expect(dialog()).toBeNull();
        expect(screen.queryByText('Paste it here')).toBeNull();
        expect(document.querySelector('a[href*="/credential/provide/"]')).toBeNull();
        expect(fetcher.mock.calls.every(([, init]) => (init?.method ?? 'GET') === 'GET')).toBe(true);
    });

    it('signs a row in from its own button, in a popup window and no dialog, and counts it in', async () => {
        on('POST', '/provide', () => json({ status: 'success', credential_id: 'cred-linear' }), B);
        show(...threeAsks());
        await signInLinear();
        expect(window.open).toHaveBeenCalledTimes(1);
        expect(String(vi.mocked(window.open).mock.calls[0][0])).toMatch(/^\/api\/auth\/linear\/authorize\?/);
        expect(dialog()).toBeNull();
        expect(within(rowOf('Linear')).getByText(/Finish in the Linear window/)).toBeTruthy();

        store.credentials = [credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear', metadata: { email: 'owner@example.com' } })];
        await linearCallback();
        await waitFor(() => expect(requests('/provide', B)).toHaveLength(1));
        expect(JSON.parse(String(requests('/provide', B)[0].body))).toMatchObject({ credential_type: 'linear_oauth', oauth_code: 'code-1' });
        await waitFor(() => expect(within(rowOf('Linear')).getByText('owner@example.com')).toBeTruthy());
        expect(within(rowOf('Linear')).getByText('Connected')).toBeTruthy();
        expect(screen.getByText('1 of 3 done')).toBeTruthy();
        expect(dialog()).toBeNull();
    });

    it('opens a key in the Connections dialog over its own request, and the save completes that request', async () => {
        on('POST', '/provide', () => json({ status: 'success', credential_id: 'cred-twilio', verification: { reachable: true, account_label: 'AC…7f3e' } }), A);
        const copied = vi.fn(async () => {});
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: copied }, configurable: true });
        show(...threeAsks());
        const add = await buttonIn('Twilio', 'Add key');
        await act(async () => fireEvent.click(add));

        const popup = screen.getByTestId('coordinator-connect-dialog');
        expect(within(popup).getByRole('heading', { name: 'Connect Twilio' })).toBeTruthy();
        // A key reads as its steps: get it (with a button to where), then paste it, then Connect.
        expect(within(popup).getByText('Paste it here')).toBeTruthy();
        expect(within(popup).getByRole('link', { name: /Open console\.twilio\.com/ }).getAttribute('href')).toBe('https://console.twilio.com');

        // Asking someone else hands them this request's own link, so whoever connects it wakes NoClick.
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Ask someone who can' })));
        expect(within(popup).getByRole('heading', { name: 'Ask someone to connect Twilio' })).toBeTruthy();
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Copy a link instead' })));
        expect(copied).toHaveBeenCalledWith(provideUrl(A));
        expect(socket.hasSent('credential:request:create')).toBe(false);
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect it yourself instead' })));

        fireEvent.change(popup.querySelector('[data-field="account_sid"] input') as HTMLInputElement, { target: { value: 'AC123' } });
        fireEvent.change(popup.querySelector('[data-field="api_key_secret"] input') as HTMLInputElement, { target: { value: 'secret' } });
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect' })));
        expect(await within(popup).findByRole('heading', { name: 'Twilio is connected' })).toBeTruthy();
        expect(within(popup).getByText('Connected as AC…7f3e')).toBeTruthy();
        expect(JSON.parse(String(requests('/provide', A)[0].body))).toEqual({ credential_data: { account_sid: 'AC123', api_key_secret: 'secret' }, credential_type: 'twilio_api_key' });
        // The row behind it is in already; Done closes back to the card.
        expect(within(rowOf('Twilio')).getByText('AC…7f3e')).toBeTruthy();
        expect(screen.getByText('1 of 3 done')).toBeTruthy();
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Done' })));
        expect(dialog()).toBeNull();
        expect(within(rowOf('Twilio')).getByText('Connected')).toBeTruthy();
    });

    it('folds to one line once every account is in, keeping the dialog on what the last one proved', async () => {
        on('POST', '/provide', () => json({ status: 'success', credential_id: 'cred-twilio', verification: { reachable: true, account_label: 'AC…7f3e' } }), A);
        show(...threeAsks());
        await buttonIn('Gmail', 'Sign in');
        store.credentials = [
            credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear', metadata: { email: 'owner@example.com' } }),
            credential({ id: 'cred-gmail', credential_type: 'google_gmail_oauth', name: 'Gmail', metadata: { email: 'sam@example.com' } }),
        ];
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: B.request, credential_id: 'cred-linear', credential_type: 'linear_oauth' }));
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: C.request, credential_id: 'cred-gmail', credential_type: 'google_gmail_oauth' }));
        expect(screen.getByText('2 of 3 done')).toBeTruthy();

        await act(async () => fireEvent.click(within(rowOf('Twilio')).getByRole('button', { name: 'Add key' })));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        fireEvent.change(popup.querySelector('[data-field="account_sid"] input') as HTMLInputElement, { target: { value: 'AC123' } });
        fireEvent.change(popup.querySelector('[data-field="api_key_secret"] input') as HTMLInputElement, { target: { value: 'secret' } });
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText('Twilio, Linear and Gmail are connected')).toBeTruthy();
        expect(screen.queryByTestId('coordinator-connect')).toBeNull();
        expect(within(screen.getByTestId('coordinator-connect-dialog')).getByRole('heading', { name: 'Twilio is connected' })).toBeTruthy();
        await act(async () => fireEvent.click(within(screen.getByTestId('coordinator-connect-dialog')).getByRole('button', { name: 'Done' })));
        expect(dialog()).toBeNull();
        expect(screen.getByText('Twilio, Linear and Gmail are connected')).toBeTruthy();
    });

    it('opens with an account fulfilled before a reload already in, the rest still to connect', async () => {
        threeAsks();
        store.credentials = [credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear', metadata: { email: 'owner@example.com' }, created_at: '2026-01-01T00:00:00Z' })];
        on('GET', '', () => json({ detail: { message: 'This credential request has already been fulfilled', status: 'fulfilled', credential_id: 'cred-linear' } }, 410), B);
        show(connectCall('twilio_api_key', A, 'step-1'), connectCall('linear_oauth', B, 'step-2'), connectCall('google_gmail_oauth', C, 'step-3'));
        await waitFor(() => expect(within(rowOf('Linear')).getByText('owner@example.com')).toBeTruthy());
        expect(screen.getByText('1 of 3 done')).toBeTruthy();
        expect(within(rowOf('Twilio')).getByRole('button', { name: 'Add key' })).toBeTruthy();
        expect(within(rowOf('Gmail')).getByRole('button', { name: 'Sign in' })).toBeTruthy();
    });

    it('opens as its one line after a reload when every account is in, without reading a request', async () => {
        store.credentials = [
            credential({ id: 'cred-twilio', credential_type: 'twilio_api_key', name: 'Twilio' }),
            credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear' }),
        ];
        show(connectCall('twilio_api_key', A, 'step-1'), connectCall('linear_oauth', B, 'step-2'));
        expect(screen.getByText('Twilio and Linear are connected')).toBeTruthy();
        expect(fetcher).not.toHaveBeenCalled();
    });
});

describe('one account to connect', () => {
    it('shows the WhatsApp QR code only once asked, in the dialog, and closes it when the request is fulfilled', async () => {
        on('GET', '', () => json(details('whatsapp_qr', [
            method('whatsapp_qr', 'WhatsAppQR', 'qr_scan'),
            method('whatsapp_access_token', 'WhatsAppAccessToken', 'api_key', { credential_fields: [{ name: 'access_token', label: 'Access Token', type: 'password', required: true }] }),
        ])));
        on('POST', '/qr/start', () => json({ success: true, connection_id: 'conn-1', qr_code: 'UVJDT0RF' }));
        show(connectCall('whatsapp_qr'));

        const ask = await screen.findByRole('button', { name: 'Show QR code' });
        expect(screen.getByText('Connect an account')).toBeTruthy();
        expect(within(rowOf('WhatsApp')).getByText('Scan a QR code')).toBeTruthy();
        // What it's for, in the coordinator's words.
        expect(screen.getByText('So I can work in it for you.')).toBeTruthy();
        // Nothing on the card leaves the chat, and no code is held open just by drawing it.
        expect(document.querySelector(`a[href*="/credential/provide/"]`)).toBeNull();
        expect(requests('/qr/start')).toHaveLength(0);

        await act(async () => fireEvent.click(ask));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        const qr = await within(popup).findByAltText('WhatsApp QR Code');
        expect(qr.getAttribute('src')).toBe('data:image/png;base64,UVJDT0RF');
        expect(requests('/qr/start')).toHaveLength(1);
        // The request's other way in is a switch in the dialog, not a second form on the card.
        expect(within(popup).getAllByRole('tab')).toHaveLength(2);
        expect(window.open).not.toHaveBeenCalled();

        // The scan happened on the phone: the backend tells the owner's pages the request is fulfilled.
        store.credentials = [credential({ id: 'cred-wa', name: '+1 415 555 0142' })];
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: 'another-request', credential_id: 'cred-x', credential_type: 'whatsapp_qr' }));
        expect(screen.getByAltText('WhatsApp QR Code')).toBeTruthy();
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: A.request, credential_id: 'cred-wa', credential_type: 'whatsapp_qr' }));
        expect(await screen.findByText('WhatsApp connected · +1 415 555 0142')).toBeTruthy();
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();
        expect(dialog()).toBeNull();
    });

    it('saves a key through the request, keeps a refusal under the fields, and folds with what the check proved', async () => {
        on('GET', '', () => json(details('stripe_api_key', [
            method('stripe_api_key', 'StripeApiKey', 'api_key', {
                credential_url: 'https://dashboard.stripe.com/apikeys',
                credential_fields: [{ name: 'api_key', label: 'Secret key', type: 'password', required: true }],
            }),
            method('stripe_oauth', 'StripeOAuth', 'oauth', { oauth_provider: 'stripe' }),
        ])));
        let accepted = false;
        on('POST', '/provide', () =>
            accepted
                ? json({ status: 'success', credential_id: 'cred-stripe', verification: { reachable: true, noun: 'customers', samples: [{ label: 'Acme Corp' }, { label: 'Northwind' }], total: 2 } })
                : json({ detail: { message: 'Invalid API Key provided: sk_live_****bad', field_errors: { api_key: 'Invalid API Key provided: sk_live_****bad' }, hint: 'The provider refused the key.' } }, 400));
        show(connectCall('stripe_api_key'));

        // The way asked for leads the row, though a sign-in leads the request's list.
        const add = await buttonIn('Stripe', 'Add key');
        await act(async () => fireEvent.click(add));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        await within(popup).findByText('Secret key');
        const field = popup.querySelector('[data-field="api_key"] input') as HTMLInputElement;
        expect(within(popup).getByText('Paste it here')).toBeTruthy();
        expect(within(popup).getByRole('link', { name: /Open dashboard\.stripe\.com/ }).getAttribute('href')).toBe('https://dashboard.stripe.com/apikeys');
        // The sign-in is the dialog's other way in.
        expect(within(popup).getByRole('tab', { name: 'Sign in' })).toBeTruthy();
        // The dialog names the account; the key form adds no heading of its own.
        expect(screen.queryByText('New Credential')).toBeNull();

        fireEvent.change(field, { target: { value: 'sk_live_bad' } });
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect' })));
        expect(await within(popup).findByText('Invalid API Key provided: sk_live_****bad')).toBeTruthy();
        expect(within(popup).getByText('The provider refused the key.')).toBeTruthy();
        // The row behind the dialog (hidden from the accessibility tree while it's open) waits on.
        expect(within(rowOf('Stripe')).getByRole('button', { name: 'Add key', hidden: true })).toBeTruthy();

        accepted = true;
        fireEvent.change(field, { target: { value: 'sk_live_good' } });
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText('Stripe connected · customers: Acme Corp, Northwind')).toBeTruthy();
        expect(within(popup).getByRole('heading', { name: 'Stripe is connected' })).toBeTruthy();
        const sent = requests('/provide').map((init) => JSON.parse(String(init.body)));
        expect(sent.at(-1)).toEqual({ credential_data: { api_key: 'sk_live_good' }, credential_type: 'stripe_api_key' });
        expect(screen.queryByTestId('coordinator-connect')).toBeNull();
    });

    it('signs in through a popup window from its row, never a tab, and the request exchanges what it hands back', async () => {
        on('GET', '', () => json(details('linear_oauth', [LINEAR_SIGN_IN])));
        on('POST', '/provide', () => json({ status: 'success', credential_id: 'cred-linear' }));
        show(connectCall('linear_oauth'));

        await signInLinear();
        expect(window.open).toHaveBeenCalledTimes(1);
        const [url, target, features] = vi.mocked(window.open).mock.calls[0];
        expect(String(url)).toMatch(/^\/api\/auth\/linear\/authorize\?/);
        expect(target).toBe('linear-oauth');
        expect(features).toContain('popup=yes');
        expect(dialog()).toBeNull();

        store.credentials = [credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear', metadata: { email: 'owner@example.com' } })];
        await linearCallback();
        await waitFor(() => expect(requests('/provide')).toHaveLength(1));
        expect(JSON.parse(String(requests('/provide')[0].body))).toMatchObject({
            credential_type: 'linear_oauth', oauth_code: 'code-1', redirect_uri: 'https://noclick.com/api/auth/linear/callback',
        });
        expect(await screen.findByText('Linear connected · owner@example.com')).toBeTruthy();
    });

    it('says so on its row when the browser blocks the sign-in window', async () => {
        vi.stubGlobal('open', vi.fn(() => null));
        on('GET', '', () => json(details('linear_oauth', [method('linear_oauth', 'LinearOAuth', 'oauth', { oauth_provider: 'linear' })])));
        show(connectCall('linear_oauth'));
        await signInLinear();
        expect(within(rowOf('Linear')).getByText(/Popup was blocked/)).toBeTruthy();
        expect(within(rowOf('Linear')).getByRole('button', { name: 'Try again' })).toBeTruthy();
        expect(requests('/provide')).toHaveLength(0);
    });

    it('opens a self-hosted sign-in in the dialog, on its own OAuth app’s form, while the instance has none', async () => {
        vi.stubEnv('VITE_NOCLICK_LOCAL', '1');
        vi.stubEnv('VITE_API_URL', 'https://api.example.test');
        routes['GET oauth-app:linear'] = () => json({ detail: 'No OAuth app' }, 404);
        on('GET', '', () => json(details('linear_oauth', [LINEAR_SIGN_IN])));
        show(connectCall('linear_oauth'));
        const signIn = await waitFor(() => {
            const button = within(rowOf('Linear')).getByRole('button', { name: 'Sign in' }) as HTMLButtonElement;
            expect(button.disabled).toBe(false);
            return button;
        });
        await act(async () => fireEvent.click(signIn));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        expect(await within(popup).findByText('Connect through your own Linear OAuth app')).toBeTruthy();
        expect(window.open).not.toHaveBeenCalled();
    });

    it.each([
        ['instagram_oauth', 'Instagram', method('instagram_oauth', 'InstagramOAuth', 'oauth')],
        ['supabase_oauth', 'Supabase', method('supabase_oauth', 'SupabaseOAuth', 'oauth', { oauth_provider: 'supabase' })],
    ])('sends a %s sign-in the card can’t finish to Connections', async (type, name, signIn) => {
        on('GET', '', () => json(details(type, [signIn])));
        const tabs: unknown[] = [];
        const onTab = (e: Event) => tabs.push((e as CustomEvent).detail);
        window.addEventListener('noclick:switch-tab', onTab);
        show(connectCall(type));
        const open = await buttonIn(name, 'Open Connections');
        expect(within(rowOf(name)).getByText('Connect it in Connections, then tell NoClick')).toBeTruthy();
        expect(screen.queryByText(/shared link/)).toBeNull();
        fireEvent.click(open);
        window.removeEventListener('noclick:switch-tab', onTab);
        expect(tabs).toEqual([{ tab: 'connections' }]);
        expect(window.open).not.toHaveBeenCalled();
    });

    it('leads with the way in that was asked for, and the dialog switches to the request’s others in place', async () => {
        on('GET', '', () => json(details('whatsapp_qr', [
            method('whatsapp_access_token', 'WhatsAppAccessToken', 'api_key', { credential_fields: [{ name: 'access_token', label: 'Access Token', type: 'password', required: true }] }),
            method('whatsapp_qr', 'WhatsAppQR', 'qr_scan'),
        ])));
        on('POST', '/qr/start', () => json({ success: true, connection_id: 'conn-1', qr_code: 'UVJDT0RF' }));
        show(connectCall('whatsapp_qr'));
        const toQr = await screen.findByRole('button', { name: 'Show QR code' });
        expect(screen.queryByText('Access token')).toBeNull();
        await act(async () => fireEvent.click(toQr));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        expect(within(popup).getByRole('tab', { name: 'QR code' }).getAttribute('data-state')).toBe('active');
        const toToken = within(popup).getAllByRole('tab').find((tab) => tab.textContent !== 'QR code')!;
        await act(async () => {
            fireEvent.mouseDown(toToken);
            fireEvent.click(toToken);
        });
        expect(within(popup).getByText('Access token')).toBeTruthy();
    });

    it('opens as its receipt after a reload when the request was fulfilled, even by a re-scan that repaired an older account', async () => {
        // A WhatsApp re-scan of a phone already connected updates that credential in place: nothing new was made.
        store.credentials = [credential({ id: 'cred-old', name: '+1 415 555 0142', created_at: '2026-01-01T00:00:00Z' })];
        on('GET', '', () => json({ detail: { message: 'This credential request has already been fulfilled', status: 'fulfilled', credential_id: 'cred-old' } }, 410));
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('WhatsApp connected · +1 415 555 0142')).toBeTruthy();
        expect(screen.queryByText(/in time/)).toBeNull();
    });

    it('counts an account made through another of the app’s ways in as the answer', async () => {
        store.credentials = [credential({ id: 'cred-token', credential_type: 'whatsapp_access_token', name: 'Business line' })];
        show(connectCall('whatsapp_qr'));
        expect(screen.getByText('WhatsApp connected · Business line')).toBeTruthy();
        expect(fetcher).not.toHaveBeenCalled();
    });

    it('reads the request only once the account list has answered', async () => {
        store.loaded = false;
        store.credentials = [];
        on('GET', '', () => json(details('whatsapp_qr', [method('whatsapp_qr', 'WhatsAppQR', 'qr_scan')])));
        show(connectCall('whatsapp_qr'));
        await act(async () => {});
        expect(fetcher).not.toHaveBeenCalled();
        expect(screen.queryByText('Connect an account')).toBeNull();
        store.loaded = true;
        await act(async () => window.dispatchEvent(new Event('noclick:credentials-changed')));
        expect(await screen.findByRole('button', { name: 'Show QR code' })).toBeTruthy();
        expect(requests('')).toHaveLength(1);
    });

    // A scan of a number an agent already answers stays that agent's: nothing new is connected, so the dialog says so
    // calmly, with nothing to retry, then and after a reload.
    it('says a scanned number stays with the agent that answers it, with nothing to retry', async () => {
        // Only the scan's poll runs on fake time; the card's own rendering keeps the real clock.
        vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
        try {
            const said = 'Your WhatsApp is connected again. WhatsApp already answers this number.';
            on('GET', '', () => json(details('whatsapp_qr', [
                method('whatsapp_qr', 'WhatsAppQR', 'qr_scan'),
                method('whatsapp_access_token', 'WhatsAppAccessToken', 'api_key'),
            ])));
            on('POST', '/qr/start', () => json({ success: true, connection_id: 'conn-1', qr_code: 'UVJDT0RF' }));
            on('POST', '/qr/status', () => json({ success: true, status: 'already_connected', message: said }));
            show(connectCall('whatsapp_qr'));
            const ask = await screen.findByRole('button', { name: 'Show QR code' });
            await act(async () => fireEvent.click(ask));
            await screen.findByAltText('WhatsApp QR Code');
            await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

            expect(await screen.findByText(said)).toBeTruthy();
            expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();
            expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
            await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
            expect(requests('/qr/status')).toHaveLength(1);
        } finally {
            vi.useRealTimers();
        }
    });

    it('opens a request that ended on a kept number with what it said', async () => {
        const said = 'Your WhatsApp is connected again. WhatsApp already answers this number.';
        on('GET', '', () => json({ detail: { message: 'This credential request has already been cancelled', status: 'cancelled', note: said } }, 410));
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText(said)).toBeTruthy();
        expect(screen.queryByText(/ask NoClick again/)).toBeNull();
    });

    it('says a cancelled request was cancelled', async () => {
        on('GET', '', () => json({ detail: { message: 'This credential request has already been cancelled', status: 'cancelled' } }, 410));
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('The request to connect WhatsApp was cancelled · ask NoClick again')).toBeTruthy();
    });

    it('offers another try when the request just couldn’t be read', async () => {
        let reads = 0;
        on('GET', '', () => (++reads === 1 ? json({ detail: 'down' }, 500) : json(details('whatsapp_qr', [method('whatsapp_qr', 'WhatsAppQR', 'qr_scan')]))));
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('Couldn’t load the way to connect WhatsApp')).toBeTruthy();
        await act(async () => fireEvent.click(within(rowOf('WhatsApp')).getByRole('button', { name: 'Try again' })));
        expect(await screen.findByRole('button', { name: 'Show QR code' })).toBeTruthy();
        expect(reads).toBe(2);
    });

    it.each([
        ['a newer request replaced it', 404, 404, 'A newer request to connect Stripe replaced this one · ask NoClick again'],
        ['it ran out of tries', 429, 429, 'Too many tries to connect Stripe · ask NoClick again'],
    ])('reads the request again when a save finds %s', async (_why, saveStatus, readStatus, said) => {
        let reads = 0;
        on('GET', '', () => (++reads === 1
            ? json(details('stripe_api_key', [method('stripe_api_key', 'StripeApiKey', 'api_key', { credential_fields: [{ name: 'api_key', label: 'Secret key', type: 'password', required: true }] })]))
            : json({ detail: 'gone' }, readStatus)));
        on('POST', '/provide', () => json({ detail: 'Credential request not found' }, saveStatus));
        show(connectCall('stripe_api_key'));
        const add = await buttonIn('Stripe', 'Add key');
        await act(async () => fireEvent.click(add));
        const popup = screen.getByTestId('coordinator-connect-dialog');
        await within(popup).findByText('Secret key');
        fireEvent.change(popup.querySelector('[data-field="api_key"] input') as HTMLInputElement, { target: { value: 'sk_live_x' } });
        await act(async () => fireEvent.click(within(popup).getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText(said)).toBeTruthy();
        expect(reads).toBe(2);
    });

    it('opens as its receipt when the account is already in, without reading the request', async () => {
        store.credentials = [credential({ id: 'cred-wa', name: '+1 415 555 0142' })];
        show(connectCall('whatsapp_qr'));
        expect(screen.getByText('WhatsApp connected · +1 415 555 0142')).toBeTruthy();
        expect(fetcher).not.toHaveBeenCalled();
    });

    it('says when the request expired, with no way in', async () => {
        on('GET', '', () => json({ detail: 'This credential request has expired' }, 410));
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('WhatsApp wasn’t connected in time · ask NoClick again')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Show QR code' })).toBeNull();
    });
});
