// @vitest-environment happy-dom
// The step form acting as one of the account's keys, as this app serves it: every scene of its lab (lab/scenes.ts), its
// settings and its accounts, opened over fixtures that refuse what only the account's signed-in owner may do
// (screens/console/ownerOnly.ts) exactly as the API refuses a key, and none of them asks for one. What every scene
// calls, as the owner and as a key, is kept in stepFormCalls.txt (`npx vitest run -u` writes it again), which NoClick's
// own tests call on its real API as a key and hold to the table. And what the form does with what it reads: every
// request goes through the app's client (none off its origin), no secret the account holds is in anything it reads or
// sends, and an account is chosen by its id and connected at NoClick's connect page, never by sending its values.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { SceneView } from './lab/StepFormLab';
import { SCENES, sceneSearch, type StepFormScene } from './lab/scenes';
import { SECRETS } from './fixtures/world';

/** How long no new call must appear before a scene's calls are taken as all it makes. */
const QUIET_MS = 800;

interface Call {
    method: string;
    path: string;
    body: Record<string, unknown>;
    answer: Promise<string>;
}

/** Requests that left the app's client: a `fetch` of its own, an XHR, a socket. */
const offClient: string[] = [];

beforeEach(() => {
    offClient.length = 0;
    vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
        offClient.push(`fetch ${String(input)}`);
        return Promise.reject(new Error('the form reached the network outside its client'));
    });
    vi.stubGlobal(
        'WebSocket',
        class {
            constructor(url: string) {
                offClient.push(`WebSocket ${url}`);
                throw new Error('no sockets');
            }
        }
    );
    vi.stubGlobal(
        'EventSource',
        class {
            constructor(url: string) {
                offClient.push(`EventSource ${url}`);
                throw new Error('no event streams');
            }
        }
    );
    const open = XMLHttpRequest.prototype.open;
    vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(function (this: XMLHttpRequest, ...args: Parameters<typeof open>) {
        offClient.push(`XHR ${String(args[1])}`);
        return open.apply(this, args);
    });
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

function recorder() {
    const calls: Call[] = [];
    let waiting = 0;
    return {
        calls,
        get waiting() {
            return waiting;
        },
        observe: (method: string, path: string, answered: Promise<Response>, body: Record<string, unknown>) => {
            waiting += 1;
            const answer = answered.then((response) => response.clone().text());
            void answer.finally(() => (waiting -= 1));
            calls.push({ method, path, body, answer });
        },
    };
}

function draw(scene: StepFormScene, actsAs: 'owner' | 'key', observe: ReturnType<typeof recorder>['observe']) {
    const router = createMemoryRouter([{ path: '*', element: <SceneView scene={scene} actsAs={actsAs} observe={observe} /> }], {
        initialEntries: [`/step-form-lab${sceneSearch(scene)}`],
    });
    return render(<RouterProvider router={router} />);
}

/** Waits until the scene has called everything it calls: no call it hasn't made before for a while, all answered. */
async function settled(record: ReturnType<typeof recorder>) {
    let seen = -1;
    let quietSince = 0;
    await waitFor(
        () => {
            const distinct = new Set(record.calls.map(asLine)).size;
            if (record.waiting > 0 || distinct !== seen) quietSince = Date.now();
            seen = distinct;
            expect(Date.now() - quietSince).toBeGreaterThanOrEqual(QUIET_MS);
        },
        { timeout: 15_000, interval: 50 }
    );
}

async function open(scene: StepFormScene, actsAs: 'owner' | 'key') {
    const record = recorder();
    draw(scene, actsAs, record.observe);
    await settled(record);
    cleanup();
    return record.calls;
}

/** Every key anywhere in `value`. */
function keysIn(value: unknown): string[] {
    if (Array.isArray(value)) return value.flatMap(keysIn);
    if (!value || typeof value !== 'object') return [];
    return Object.entries(value).flatMap(([key, inner]) => [key, ...keysIn(inner)]);
}

/** Holds that nothing the form read or sent carries a secret the account holds, nor a credential's data, at any depth. */
async function holdsNoSecret(calls: Call[]) {
    for (const call of calls) {
        const sent = JSON.stringify(call.body);
        const read = await call.answer;
        for (const secret of Object.values(SECRETS)) {
            expect(sent, `${asLine(call)} sent a secret`).not.toContain(secret);
            expect(read, `${asLine(call)} read a secret`).not.toContain(secret);
        }
        const keys = keysIn(call.body);
        for (const key of ['credential_id', 'credentialIds', 'credential_ids', 'credential_data', 'data', 'token', 'api_key']) {
            expect(keys, `${asLine(call)} sent ${key}`).not.toContain(key);
        }
    }
}

/** A tab a click opened, where the form sends it. */
function stubTabs() {
    const tabs: { location: { href: string }; closed: boolean; opener: unknown; close: () => void }[] = [];
    vi.stubGlobal('open', () => {
        const tab = { location: { href: 'about:blank' }, closed: false, opener: null as unknown, close: () => undefined };
        tabs.push(tab);
        return tab;
    });
    return tabs;
}

const scene = (id: string) => SCENES.find((s) => s.id === id)!;

describe('the step form acting as a key', () => {
    it('opens every scene without asking for what only the account’s owner may do', { timeout: 300_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const each of SCENES) {
            for (const actsAs of ['owner', 'key'] as const) {
                const calls = await open(each, actsAs);
                await holdsNoSecret(calls);
                for (const call of calls) {
                    called.add(asLine(call));
                    if (actsAs === 'key' && isOwnerOnly(call.method, call.path)) refused.push(`${each.id}: ${asLine(call)}`);
                }
            }
        }
        expect(refused).toEqual([]);
        expect(offClient).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./stepFormCalls.txt');
    });

    it('reads a step type’s schema once a session, and the trigger’s address for the step', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('hook'), 'key', record.observe);
        expect(await screen.findByDisplayValue('https://hooks.example.test/hook', undefined, { timeout: 8000 })).toBeTruthy();
        await settled(record);
        expect(record.calls.map(asLine)).toEqual(['GET /v1/step_types/example-hook', 'POST /v1/workflows/wf_orders/steps/hook/values']);
        expect(record.calls[1].body).toEqual({ field: 'webhook_url', settings: {} });
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('lists a dropdown’s choices for the step, sending its settings as the form holds them', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('mail-send'), 'key', record.observe);
        // The saved channel is found among the account's channels.
        expect(await screen.findByDisplayValue('#orders', undefined, { timeout: 8000 })).toBeTruthy();
        await settled(record);
        const options = record.calls.filter((c) => c.path === '/v1/workflows/wf_orders/steps/mail/options');
        expect(options.length).toBeGreaterThan(0);
        for (const call of options) expect(call.body.field).toBe('channel');
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('previews an expression in a field against what the step references', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('mail-send'), 'key', record.observe);
        const body = (await screen.findByDisplayValue("New order from {{ $('hook').body.name }}", undefined, { timeout: 8000 })) as HTMLTextAreaElement;
        await settled(record);
        const inside = body.value.indexOf('hook') + 2;
        await act(async () => {
            fireEvent.focus(body);
            body.setSelectionRange(inside, inside);
            fireEvent.click(body);
            fireEvent.select(body);
        });
        await waitFor(() => expect(record.calls.some((c) => c.path === '/v1/workflows/wf_orders/steps/mail/expression')).toBe(true), { timeout: 8000 });
        const preview = record.calls.find((c) => c.path === '/v1/workflows/wf_orders/steps/mail/expression')!;
        expect(preview.body).toMatchObject({ expression: "$('hook').body.name", samples: { hook: { body: { name: 'Ada' } } } });
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('clears what a step keeps between runs through the API', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('state'), 'key', record.observe);
        const clear = await screen.findByRole('button', { name: /Clear State/ }, { timeout: 8000 });
        await act(async () => fireEvent.click(clear));
        await waitFor(() => expect(record.calls.map(asLine)).toContain('POST /v1/workflows/wf_orders/steps/state/clear_state'));
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('lists the account’s connections for a step and saves a choice as the step’s set_connection edit', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('accounts-picked'), 'key', record.observe);
        const picker = await screen.findByRole('button', { name: 'Orders mailbox' }, { timeout: 8000 });
        // Its check said who it reaches; the revoked one is listed after the working ones.
        expect(screen.getByText('Verified as orders@example.test')).toBeTruthy();
        await settled(record);
        expect(record.calls.map(asLine)).toEqual(expect.arrayContaining(['GET /v1/step_types/example-mail', 'GET /v1/connections']));
        await act(async () => fireEvent.click(picker));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Support mailbox' })));
        await waitFor(() => expect(record.calls.map(asLine)).toContain('POST /v1/workflows/wf_orders/edits'));
        const edit = record.calls.find((c) => c.path === '/v1/workflows/wf_orders/edits')!;
        expect(edit.body).toEqual({ ops: [{ op: 'set_connection', id: 'mail', connection: 'cred_mail_2', slot: 'example_mail_token' }], include_graph: true });
        expect(await screen.findByRole('button', { name: 'Support mailbox' })).toBeTruthy();
        // A key's view offers no Share (the API doesn't share accounts) and no Delete (Connections deletes them).
        expect(screen.queryByRole('button', { name: /^Share / })).toBeNull();
        expect(screen.queryByRole('button', { name: /^Delete / })).toBeNull();
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('connects a step’s first account at NoClick’s connect page in a new tab, sending no secret, then saves it', { timeout: 30_000 }, async () => {
        const tabs = stubTabs();
        const record = recorder();
        draw(scene('accounts-optional'), 'key', record.observe);
        expect(await screen.findByText('Optional. With no account here, NoClick’s own key runs it and bills the usage.', undefined, { timeout: 8000 })).toBeTruthy();
        await settled(record);
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect on NoClick' })));
        // A named connection of the step's app, on its own first way in, with nothing of the account's in it.
        await waitFor(() => expect(record.calls.filter((c) => c.method === 'POST' && c.path === '/v1/connections').map((c) => c.body)).toEqual([
            { name: expect.stringMatching(/^example_search-/), integration: 'example_search' },
        ]));
        await waitFor(() => expect(tabs[0]?.location.href).toMatch(/^https:\/\/noclick\.test\/connect\/example_search-/));
        // Once the account lands there, the step takes it by its connection's id.
        await waitFor(() => expect(record.calls.map(asLine)).toContain('POST /v1/workflows/wf_orders/edits'), { timeout: 8000 });
        const edit = record.calls.find((c) => c.path === '/v1/workflows/wf_orders/edits')!;
        expect(edit.body).toEqual({ ops: [{ op: 'set_connection', id: 'search', connection: expect.stringMatching(/^conn_examplesearch/), slot: 'example_search_api_key' }], include_graph: true });
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('connects an agent’s AI account through connect.model, as the key of the provider its model names', { timeout: 30_000 }, async () => {
        const tabs = stubTabs();
        const record = recorder();
        draw(scene('accounts-agent'), 'key', record.observe);
        expect(await screen.findByRole('button', { name: 'Team key' }, { timeout: 8000 })).toBeTruthy();
        await settled(record);
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect another account' })));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect an AI account' })));
        await act(async () => fireEvent.click(await screen.findByRole('button', { name: 'Connect on NoClick' })));
        await waitFor(() => expect(record.calls.filter((c) => c.method === 'POST' && c.path === '/v1/connections').map((c) => c.body)).toEqual([
            { name: expect.stringMatching(/^openai-/), integration: 'openai', credential_type: 'agent_openai' },
        ]));
        await waitFor(() => expect(tabs[0]?.location.href).toMatch(/^https:\/\/noclick\.test\/connect\/openai-/));
        await waitFor(() => expect(record.calls.map(asLine)).toContain('POST /v1/workflows/wf_orders/edits'), { timeout: 8000 });
        const edit = record.calls.find((c) => c.path === '/v1/workflows/wf_orders/edits')!;
        expect(edit.body).toEqual({ ops: [{ op: 'set_connection', id: 'agent', connection: expect.stringMatching(/^conn_openai/), slot: 'agent_openai' }], include_graph: true });
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('says why an account the step points at can’t be used, and offers to connect another', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('accounts-revoked'), 'key', record.observe);
        expect(await screen.findByText('This account was disconnected or revoked, so runs can’t use it. Connect it again below, or choose another.', undefined, { timeout: 8000 })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Old mailbox (revoked)' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Connect on NoClick' })).toBeTruthy();
        await settled(record);
        await holdsNoSecret(record.calls);
        expect(offClient).toEqual([]);
    });

    it('says why when the API doesn’t know a step’s type', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('unknown'), 'key', record.observe);
        expect(await screen.findByText(/This step’s settings couldn’t be read: No step type 'example-gone'/, undefined, { timeout: 8000 })).toBeTruthy();
    });
});
