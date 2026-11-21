// @vitest-environment happy-dom
// The step form acting as one of the account's keys, as this app serves it: every scene of its lab (lab/scenes.ts)
// opened over fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts) exactly
// as the API refuses a key, and none of them asks for one. What every scene calls, as the owner and as a key, is kept in
// stepFormCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key and
// hold to the table. And what the form does with what it reads: every request goes through the app's client (none off
// its origin), and no secret the account holds is in anything it reads or sends.
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

/** Holds that nothing the form read or sent carries a secret the account holds, nor a credential's data. */
async function holdsNoSecret(calls: Call[]) {
    for (const call of calls) {
        const sent = JSON.stringify(call.body);
        const read = await call.answer;
        for (const secret of Object.values(SECRETS)) {
            expect(sent, `${asLine(call)} sent a secret`).not.toContain(secret);
            expect(read, `${asLine(call)} read a secret`).not.toContain(secret);
        }
        for (const key of ['credential_id', 'credentialIds', 'credential_ids', 'data']) {
            expect(call.body, `${asLine(call)} sent ${key}`).not.toHaveProperty(key);
        }
    }
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

    it('says why when the API doesn’t know a step’s type', { timeout: 30_000 }, async () => {
        const record = recorder();
        draw(scene('unknown'), 'key', record.observe);
        expect(await screen.findByText(/This step’s settings couldn’t be read: No step type 'example-gone'/, undefined, { timeout: 8000 })).toBeTruthy();
    });
});
