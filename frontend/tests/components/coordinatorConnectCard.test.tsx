// @vitest-environment jsdom
// An account the coordinator asks to connect is connected on its card, never in a new tab: the card runs the
// coordinator's own credential request (the token in the tool's link) through the provide page's connect UI, so a
// key is judged and saved by the request, a QR code is minted only when asked for, and a sign-in opens in a popup
// window whose result the request exchanges. The card folds to its receipt on the request's own result: the save's
// reply here, or the credential_request:fulfilled frame the backend sends the owner's user room (fed here exactly as
// the relay delivers it: the event's JSON with its name as `type`).
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
    ],
}));

import { TurnCards } from '~/components/coordinator/toolCards';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

const TOKEN = 'a'.repeat(64);
const REQUEST = '6f1c2d3e-4b5a-4968-8776-1a2b3c4d5e6f';
const BASE = `/api/credential-request/${TOKEN}`;

function connectCall(credentialType: string, message = 'So I can work in it for you.'): CoordinatorToolCall {
    return {
        id: 'step-1',
        tool: 'connect_credential',
        args: { credential_type: credentialType, message },
        result: { status: 'pending', request_id: REQUEST, url: `https://noclick.com/credential/provide/${TOKEN}`, auto_resume: true },
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

type Route = (init?: RequestInit) => Response;
let routes: Record<string, Route>;
let fetcher: ReturnType<typeof vi.fn>;
let socket: MockSocket;
let teardown: () => void;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function requests(path: string): RequestInit[] {
    return fetcher.mock.calls.filter(([url]) => String(url).endsWith(BASE + path)).map(([, init]) => init as RequestInit);
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
        const key = `${init?.method ?? 'GET'} ${String(url).split(BASE)[1] ?? url}`;
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
});

function show(call: CoordinatorToolCall) {
    return render(<TurnCards calls={[call]} />);
}

function credential(fields: Partial<CredentialInfo>): CredentialInfo {
    return { id: 'cred-1', name: 'Account', credential_type: 'whatsapp_qr', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...fields } as CredentialInfo;
}

describe('a connect card', () => {
    it('shows the WhatsApp QR code on the card only once asked, and folds when the request is fulfilled', async () => {
        routes['GET '] = () => json(details('whatsapp_qr', [
            method('whatsapp_qr', 'WhatsAppQR', 'qr_scan'),
            method('whatsapp_access_token', 'WhatsAppAccessToken', 'api_key', { credential_fields: [{ name: 'access_token', label: 'Access Token', type: 'password', required: true }] }),
        ]));
        routes['POST /qr/start'] = () => json({ success: true, connection_id: 'conn-1', qr_code: 'UVJDT0RF' });
        show(connectCall('whatsapp_qr'));

        const card = await screen.findByRole('button', { name: 'Show QR code' });
        expect(screen.getByText('Connect WhatsApp')).toBeTruthy();
        // Nothing on the card leaves the chat, and no code is held open just by drawing it.
        expect(document.querySelector(`a[href*="/credential/provide/"]`)).toBeNull();
        expect(requests('/qr/start')).toHaveLength(0);
        // The request's other way in is a quiet switch, not a second form.
        expect(screen.getByRole('button', { name: 'Use a WhatsApp Access Token instead' })).toBeTruthy();

        await act(async () => fireEvent.click(card));
        const qr = await screen.findByAltText('WhatsApp QR Code');
        expect(qr.getAttribute('src')).toBe('data:image/png;base64,UVJDT0RF');
        expect(requests('/qr/start')).toHaveLength(1);
        expect(window.open).not.toHaveBeenCalled();

        // The scan happened on the phone: the backend tells the owner's pages the request is fulfilled.
        store.credentials = [credential({ id: 'cred-wa', name: '+1 415 555 0142' })];
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: 'another-request', credential_id: 'cred-x', credential_type: 'whatsapp_qr' }));
        expect(screen.getByAltText('WhatsApp QR Code')).toBeTruthy();
        await act(async () => socket.serverEmit('credential_request:fulfilled', { type: 'credential_request:fulfilled', request_id: REQUEST, credential_id: 'cred-wa', credential_type: 'whatsapp_qr' }));
        expect(await screen.findByText('WhatsApp connected · +1 415 555 0142')).toBeTruthy();
        expect(screen.queryByAltText('WhatsApp QR Code')).toBeNull();
    });

    it('saves a key through the request, keeps a refusal under the fields, and folds with what the check proved', async () => {
        routes['GET '] = () => json(details('stripe_api_key', [
            method('stripe_api_key', 'StripeApiKey', 'api_key', {
                credential_url: 'https://dashboard.stripe.com/apikeys',
                credential_fields: [{ name: 'api_key', label: 'Secret key', type: 'password', required: true }],
            }),
            method('stripe_oauth', 'StripeOAuth', 'oauth', { oauth_provider: 'stripe' }),
        ]));
        let accepted = false;
        routes['POST /provide'] = () =>
            accepted
                ? json({ status: 'success', credential_id: 'cred-stripe', verification: { reachable: true, noun: 'customers', samples: [{ label: 'Acme Corp' }, { label: 'Northwind' }], total: 2 } })
                : json({ detail: { message: 'Invalid API Key provided: sk_live_****bad', field_errors: { api_key: 'Invalid API Key provided: sk_live_****bad' }, hint: 'The provider refused the key.' } }, 400);
        show(connectCall('stripe_api_key'));

        await screen.findByText('Secret key');
        const field = document.querySelector('[data-field="api_key"] input') as HTMLInputElement;
        // A key reads as its steps on the card too: get it (with a button to where), then paste it.
        expect(screen.getByText('Paste it here')).toBeTruthy();
        expect(screen.getByRole('link', { name: /Open dashboard\.stripe\.com/ }).getAttribute('href')).toBe('https://dashboard.stripe.com/apikeys');
        expect(screen.getByRole('button', { name: 'Sign in with Stripe instead' })).toBeTruthy();
        // The card names the account; the key form adds no heading of its own.
        expect(screen.queryByText('New Credential')).toBeNull();

        fireEvent.change(field, { target: { value: 'sk_live_bad' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText('Invalid API Key provided: sk_live_****bad')).toBeTruthy();
        expect(screen.getByText('The provider refused the key.')).toBeTruthy();
        expect(screen.getByTestId('coordinator-connect-form')).toBeTruthy();

        accepted = true;
        fireEvent.change(field, { target: { value: 'sk_live_good' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText('Stripe connected · customers: Acme Corp, Northwind')).toBeTruthy();
        const sent = requests('/provide').map((init) => JSON.parse(String(init.body)));
        expect(sent.at(-1)).toEqual({ credential_data: { api_key: 'sk_live_good' }, credential_type: 'stripe_api_key' });
        expect(screen.queryByTestId('coordinator-connect-form')).toBeNull();
    });

    it('signs in through a popup window, never a tab, and the request exchanges what it hands back', async () => {
        routes['GET '] = () => json(details('linear_oauth', [method('linear_oauth', 'LinearOAuth', 'oauth', { oauth_provider: 'linear', oauth_scopes: ['read', 'write'] })]));
        routes['POST /provide'] = () => json({ status: 'success', credential_id: 'cred-linear' });
        show(connectCall('linear_oauth'));

        const signIn = await screen.findByRole('button', { name: /Continue with Linear/ });
        await act(async () => fireEvent.click(signIn));
        expect(window.open).toHaveBeenCalledTimes(1);
        const [url, target, features] = vi.mocked(window.open).mock.calls[0];
        expect(String(url)).toMatch(/^\/api\/auth\/linear\/authorize\?/);
        expect(target).toBe('linear-oauth');
        expect(features).toContain('popup=yes');

        store.credentials = [credential({ id: 'cred-linear', credential_type: 'linear_oauth', name: 'Linear', metadata: { email: 'owner@example.com' } })];
        await act(async () => {
            window.dispatchEvent(new MessageEvent('message', {
                origin: window.location.origin,
                data: { type: 'linear-oauth-callback', success: true, code: 'code-1', redirectUri: 'https://noclick.com/api/auth/linear/callback', scopes: ['read', 'write'] },
            }));
        });
        await waitFor(() => expect(requests('/provide')).toHaveLength(1));
        expect(JSON.parse(String(requests('/provide')[0].body))).toMatchObject({
            credential_type: 'linear_oauth', oauth_code: 'code-1', redirect_uri: 'https://noclick.com/api/auth/linear/callback',
        });
        expect(await screen.findByText('Linear connected · owner@example.com')).toBeTruthy();
    });

    it('says so on the card when the browser blocks the sign-in window', async () => {
        vi.stubGlobal('open', vi.fn(() => null));
        routes['GET '] = () => json(details('linear_oauth', [method('linear_oauth', 'LinearOAuth', 'oauth', { oauth_provider: 'linear' })]));
        show(connectCall('linear_oauth'));
        const signIn = await screen.findByRole('button', { name: /Continue with Linear/ });
        await act(async () => fireEvent.click(signIn));
        const form = screen.getByTestId('coordinator-connect-form');
        expect(within(form).getByText(/Popup was blocked/)).toBeTruthy();
        expect(requests('/provide')).toHaveLength(0);
    });

    it.each([
        ['instagram_oauth', 'Instagram', method('instagram_oauth', 'InstagramOAuth', 'oauth')],
        ['supabase_oauth', 'Supabase', method('supabase_oauth', 'SupabaseOAuth', 'oauth', { oauth_provider: 'supabase' })],
    ])('sends a %s sign-in the card can’t finish to Connections', async (type, name, signIn) => {
        routes['GET '] = () => json(details(type, [signIn]));
        const tabs: unknown[] = [];
        const onTab = (e: Event) => tabs.push((e as CustomEvent).detail);
        window.addEventListener('noclick:switch-tab', onTab);
        show(connectCall(type));
        expect(await screen.findByText(`Signing in to ${name} needs a step that only runs in Connections. Connect it there, then tell NoClick it’s done.`)).toBeTruthy();
        expect(screen.queryByText(/shared link/)).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Open Connections' }));
        window.removeEventListener('noclick:switch-tab', onTab);
        expect(tabs).toEqual([{ tab: 'connections' }]);
        expect(window.open).not.toHaveBeenCalled();
    });

    it('leads with the way in that was asked for, and switches to the request’s others in place', async () => {
        routes['GET '] = () => json(details('whatsapp_qr', [
            method('whatsapp_access_token', 'WhatsAppAccessToken', 'api_key', { credential_fields: [{ name: 'access_token', label: 'Access Token', type: 'password', required: true }] }),
            method('whatsapp_qr', 'WhatsAppQR', 'qr_scan'),
        ]));
        show(connectCall('whatsapp_qr'));
        const toToken = await screen.findByRole('button', { name: 'Use a WhatsApp Access Token instead' });
        expect(screen.queryByText('Access token')).toBeNull();
        await act(async () => fireEvent.click(toToken));
        expect(screen.getByText('Access token')).toBeTruthy();
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Scan a QR code instead' })));
        expect(screen.getByRole('button', { name: 'Show QR code' })).toBeTruthy();
        expect(requests('/qr/start')).toHaveLength(0);
    });

    it('opens as its receipt after a reload when the request was fulfilled, even by a re-scan that repaired an older account', async () => {
        // A WhatsApp re-scan of a phone already connected updates that credential in place: nothing new was made.
        store.credentials = [credential({ id: 'cred-old', name: '+1 415 555 0142', created_at: '2026-01-01T00:00:00Z' })];
        routes['GET '] = () => json({ detail: { message: 'This credential request has already been fulfilled', status: 'fulfilled', credential_id: 'cred-old' } }, 410);
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
        routes['GET '] = () => json(details('whatsapp_qr', [method('whatsapp_qr', 'WhatsAppQR', 'qr_scan')]));
        show(connectCall('whatsapp_qr'));
        await act(async () => {});
        expect(fetcher).not.toHaveBeenCalled();
        expect(screen.queryByText('Connect WhatsApp')).toBeNull();
        store.loaded = true;
        await act(async () => window.dispatchEvent(new Event('noclick:credentials-changed')));
        expect(await screen.findByRole('button', { name: 'Show QR code' })).toBeTruthy();
        expect(requests('')).toHaveLength(1);
    });

    it('says a cancelled request was cancelled', async () => {
        routes['GET '] = () => json({ detail: { message: 'This credential request has already been cancelled', status: 'cancelled' } }, 410);
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('The request to connect WhatsApp was cancelled · ask NoClick again')).toBeTruthy();
    });

    it.each([
        ['a newer request replaced it', 404, 404, 'A newer request to connect Stripe replaced this one · ask NoClick again'],
        ['it ran out of tries', 429, 429, 'Too many tries to connect Stripe · ask NoClick again'],
    ])('reads the request again when a save finds %s', async (_why, saveStatus, readStatus, said) => {
        let reads = 0;
        routes['GET '] = () => (++reads === 1
            ? json(details('stripe_api_key', [method('stripe_api_key', 'StripeApiKey', 'api_key', { credential_fields: [{ name: 'api_key', label: 'Secret key', type: 'password', required: true }] })]))
            : json({ detail: 'gone' }, readStatus));
        routes['POST /provide'] = () => json({ detail: 'Credential request not found' }, saveStatus);
        show(connectCall('stripe_api_key'));
        await screen.findByText('Secret key');
        fireEvent.change(document.querySelector('[data-field="api_key"] input') as HTMLInputElement, { target: { value: 'sk_live_x' } });
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect' })));
        expect(await screen.findByText(said)).toBeTruthy();
        expect(reads).toBe(2);
    });

    it('opens as its receipt when the account is already in, without reading the request', async () => {
        store.credentials = [credential({ id: 'cred-wa', name: '+1 415 555 0142' })];
        show(connectCall('whatsapp_qr'));
        expect(screen.getByText('WhatsApp connected · +1 415 555 0142')).toBeTruthy();
        expect(fetcher).not.toHaveBeenCalled();
    });

    it('says when the request expired, with no form', async () => {
        routes['GET '] = () => json({ detail: 'This credential request has expired' }, 410);
        show(connectCall('whatsapp_qr'));
        expect(await screen.findByText('WhatsApp wasn’t connected in time · ask NoClick again')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Show QR code' })).toBeNull();
    });
});

// A platform agent's connect link (the coordinator's connections_create, its link inside the connection) is the same
// card: with the owner in the chat it's connected right here, never sent to them (an expired Linear sign-in got
// "I emailed you a fresh secure link", 2026-10-18), and never the bare "waiting on you" of the operation behind it.
describe('a platform connect link', () => {
    const OPERATION = '0b6a1f0e-4f3c-4d6e-9a51-1f2d3c4b5a69';

    function platformConnectCall(): CoordinatorToolCall {
        const link = { id: 'link-1', url: `https://noclick.com/credential/provide/${TOKEN}`, expires_at: '', operation_id: OPERATION };
        return {
            id: 'step-2',
            tool: 'noclick__api_call',
            args: { operation: 'connections_create', arguments: { name: 'linear', integration: 'linear', reason: 'So the agent can open Linear tickets.' } },
            result: {
                success: true, job_id: 'job-1', operation_id: OPERATION, status: 'awaiting_human',
                response: { object: 'connection', name: 'linear', integration: 'linear', credential_type: 'linear_oauth', status: 'pending', connect_link: link },
                next: 'It waits on a person.',
            },
            running: false,
            startedAt: Date.now() - 5_000,
        };
    }

    beforeAll(async () => {
        await import('~/cloud/bootstrap');
        await import('~/cloud/components/coordinator/hostedChat');
    }, 60_000);

    it('connects on its card, over the link’s own request, with what it’s for', async () => {
        routes['GET '] = () => json(details('linear_oauth', [method('linear_oauth', 'LinearOAuth', 'oauth', { oauth_provider: 'linear' })]));
        show(platformConnectCall());
        expect(await screen.findByRole('button', { name: /Continue with Linear/ })).toBeTruthy();
        expect(screen.getByText('Connect Linear')).toBeTruthy();
        expect(screen.getByText('So the agent can open Linear tickets.')).toBeTruthy();
        expect(screen.queryByText('Needs you')).toBeNull();
        expect(document.querySelector(`a[href*="/credential/provide/"]`)).toBeNull();
    });
});
