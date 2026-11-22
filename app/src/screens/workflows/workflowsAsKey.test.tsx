// @vitest-environment happy-dom
// The workflows pages acting as one of the account's keys, as this app serves them (lab/WorkflowsLab.tsx over
// fixtures.ts): the list under its folders, a workflow made by name, and one workflow's page whole: its canvas opened,
// a step's panel with its settings changed (saved as the canvas's own edit, once), a step added from the palette, the
// workflow run and its run shown, its Setup tab and its Test Run; then a workflow the key may only look at, read-only.
// Over fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts) exactly as
// the API refuses a key, and none of it asks for one. What it calls, as the owner and as a key, is kept in
// workflowsCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key.
// And what it does with what it reads: every request goes through the app's client (none off its origin), and no
// secret the account holds is in anything it reads or sends.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { Node } from '@xyflow/react';
import { MotionGlobalConfig } from 'framer-motion';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { standing } from '@/slots';
import { SECRETS, WORKFLOW } from '@/screens/canvas/graph/fixtures';
import { flushAllGraphsNow, graphRecords } from '@/screens/canvas/graph/liveGraphStore';
import { V1_GRAPH_SAVES } from '@/screens/canvas/graph/saves';
import { OUTPUT_SECRET } from '@/screens/canvas/runs/fixtures';
import { GRAPH_SAVES, STEP_DRAWING } from '@/screens/canvas/slots';
import { forgetAuthoring } from '@/screens/canvas/testRun/authoring';
import { forgetTestRuns } from '@/screens/canvas/testRun/standards';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import { VARIABLE_SECRET } from '@/screens/canvas/setup/fixtures';
import { fill } from '@/slots';
import { SCENES, SceneView, type WorkflowsScene } from './lab/WorkflowsLab';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    body: Json;
    answer: Promise<string>;
}

/** Requests that left the app's client: a `fetch` of its own, an XHR, a socket. */
const offClient: string[] = [];

const scene = (id: string) => SCENES.find((s) => s.id === id) as WorkflowsScene;
const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

// What loads with its first use (the plain drawing, the SDK the standards call, the palette, a run's results, the step
// form, the README a frame draws with): loaded once here, so each page below draws rather than waits.
beforeAll(async () => {
    await Promise.all([
        import('@/screens/canvas/standardsSdk'),
        import('@/screens/canvas/surface/StepPalette'),
        import('@/screens/canvas/runs/RunSteps'),
        import('@/screens/canvas/form/NodeConfig'),
        import('@/screens/canvas/setup/RuntimeAccounts'),
        import('@/screens/resources/CodeView'),
        import('@/ui/connectStandards'),
    ]);
    const { result, unmount } = renderHook(() => standing(STEP_DRAWING).useLoaded([]));
    await waitFor(() => expect(result.current).toBe(true));
    unmount();
    MotionGlobalConfig.skipAnimations = true;
    Element.prototype.scrollIntoView ??= () => undefined;
});

beforeEach(() => {
    offClient.length = 0;
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
    forgetAuthoring();
    forgetTestRuns();
    vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
        offClient.push(`fetch ${String(input)}`);
        return Promise.reject(new Error('the page reached the network outside its client'));
    });
    for (const name of ['WebSocket', 'EventSource'] as const) {
        vi.stubGlobal(
            name,
            class {
                constructor(url: string) {
                    offClient.push(`${name} ${url}`);
                    throw new Error(`no ${name}`);
                }
            }
        );
    }
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

/** A scene of the lab drawn, with every call it makes kept. */
function draw(which: WorkflowsScene, actsAs: 'owner' | 'key') {
    const calls: Call[] = [];
    const view = render(
        <MemoryRouter>
            <div style={{ width: 1280, height: 800 }}>
                <SceneView
                    scene={which}
                    actsAs={actsAs}
                    observe={(method, path, answered, body) => {
                        calls.push({ method, path, body, answer: answered.then((response) => response.clone().text()) });
                    }}
                />
            </div>
        </MemoryRouter>
    );
    return { ...view, calls };
}

/** What the canvas hands React Flow, read from the element React Flow draws. */
function surface(container: HTMLElement): Json {
    const el = container.querySelector('.react-flow') as Element & Record<string, unknown>;
    const key = Object.keys(el).find((k) => k.startsWith('__reactFiber'));
    let fiber = key ? (el[key] as { memoizedProps?: Json; return?: unknown } | null) : null;
    while (fiber) {
        const props = fiber.memoizedProps;
        if (props && typeof props.isValidConnection === 'function' && typeof props.onConnect === 'function') return props;
        fiber = fiber.return as typeof fiber;
    }
    throw new Error('React Flow’s props not found');
}

/** Selects one step, as a click on it does. */
async function select(container: HTMLElement, id: string) {
    const nodes = graphRecords[WORKFLOW].nodes as Node[];
    await act(async () => {
        (surface(container).onNodesChange as (changes: unknown[]) => void)(nodes.map((n) => ({ type: 'select', id: n.id, selected: n.id === id })));
    });
    await act(async () => {
        (surface(container).onSelectionChange as (selection: unknown) => void)({ nodes: (graphRecords[WORKFLOW].nodes as Node[]).filter((n) => n.id === id), edges: [] });
    });
}

const edits = (calls: Call[]) => calls.filter((c) => asLine(c) === `POST /v1/workflows/${WORKFLOW}/edits`);
const opsOf = (call: Call) => (call.body.ops as Json[]).map((op) => op.op);
const tab = (name: string) => screen.getAllByRole('tab').find((t) => t.textContent === name) as HTMLElement;
const SAVED = { timeout: 8000 };

/** The list, a workflow made, then one workflow's page whole. */
async function session(actsAs: 'owner' | 'key'): Promise<Call[]> {
    // The list: the account's workflows under its folders, and a new one made by name.
    const list = draw(scene('list'), actsAs);
    await screen.findByText('Orders');
    expect(screen.getByRole('region', { name: 'Reports' }).textContent).toContain('Morning brief');
    expect(screen.getByTestId('workflow-row-wf_shared').textContent).toContain('View only');
    fireEvent.click(screen.getByRole('button', { name: /new workflow/i }));
    fireEvent.change(screen.getByRole('textbox', { name: 'The workflow’s name' }), { target: { value: `Made as the ${actsAs}` } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(list.calls.some((c) => asLine(c) === 'POST /v1/workflows')).toBe(true));
    // The new workflow's page opens; back, the list reads it.
    await screen.findByTestId('workflow-page');
    fireEvent.click(screen.getByRole('button', { name: /automations/i }));
    await screen.findByText(`Made as the ${actsAs}`);
    const calls = [...list.calls];
    list.unmount();
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];

    // One workflow's page: its canvas.
    const page = draw(scene('canvas'), actsAs);
    const { container } = page;
    await waitFor(() => expect(container.querySelector('.react-flow__node[data-id="slack"]')).not.toBeNull(), SAVED);
    await screen.findByRole('button', { name: 'Run' });

    // A step's panel: its settings, one changed.
    await select(container, 'slack');
    const panel = await screen.findByTestId('step-panel');
    const text = await waitFor(() => {
        const field = panel.querySelector('input[data-field-key="text"], textarea[data-field-key="text"]');
        expect(field).not.toBeNull();
        return field as HTMLInputElement | HTMLTextAreaElement;
    }, SAVED);
    fireEvent.change(text, { target: { value: 'A new order came in.' } });
    await waitFor(() => expect(edits(page.calls).some((e) => opsOf(e).includes('update_step'))).toBe(true), SAVED);
    // Its accounts: the ones the account holds of its kind.
    fireEvent.click(tab('Account'));
    await waitFor(() => expect(page.calls.some((c) => asLine(c) === 'GET /v1/connections')).toBe(true));
    fireEvent.click(screen.getByRole('button', { name: 'Close the step' }));
    await waitFor(() => expect(screen.queryByTestId('step-panel')).toBeNull());

    // A step added from the palette.
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    const search = await screen.findByRole('textbox', { name: 'Search steps' });
    fireEvent.change(search, { target: { value: 'sla' } });
    await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([expect.stringContaining('Slack')]), SAVED);
    fireEvent.keyDown(search, { key: 'Enter' });
    await waitFor(() => expect(edits(page.calls).some((e) => opsOf(e).includes('add_step'))).toBe(true), SAVED);

    // The workflow run, and its run shown.
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await waitFor(() => expect(page.calls.some((c) => asLine(c) === `GET /v1/workflows/${WORKFLOW}/runs/run_new`)).toBe(true), SAVED);
    await waitFor(() => expect((graphRecords[WORKFLOW].nodes as Node[]).find((n) => n.id === 'slack')?.data._lastRunStatus).toBe('completed'), SAVED);

    // Its Setup tab: the steps it still needs, derived from the workflow.
    fireEvent.click(tab('Setup'));
    const setup = await screen.findByTestId('workflow-setup');
    await waitFor(() => expect(setup.querySelector('h2')).not.toBeNull(), SAVED);
    // Its one variable has a value. The owner's page read it apart and shows it; a key's never asked, and says it's
    // saved and hidden.
    const expand = setup.querySelector('button[aria-label="Expand sidebar"]');
    if (expand) fireEvent.click(expand);
    fireEvent.click(
        await waitFor(() => {
            const row = [...setup.querySelectorAll('aside nav button')].find((b) => b.textContent?.includes('Reply to'));
            expect(row).toBeTruthy();
            return row as HTMLButtonElement;
        }, SAVED)
    );
    const value = await waitFor(() => {
        const field = setup.querySelector('input[placeholder]');
        expect(setup.querySelector('h2')?.textContent).toBe('Reply to');
        return field as HTMLInputElement;
    }, SAVED);
    const asked = page.calls.filter((c) => asLine(c) === `GET /v1/workflows/${WORKFLOW}/variables`).length;
    expect([value.value, value.placeholder, asked]).toEqual(actsAs === 'owner' ? [VARIABLE_SECRET, 'Enter a value', 1] : ['', 'Saved, hidden. Type to replace it.', 0]);
    // Leaving the field as it was writes nothing, whoever reads it.
    fireEvent.blur(value);
    expect(edits(page.calls).some((e) => opsOf(e).includes('define_variable'))).toBe(false);

    // Its Test Run: the message it stages.
    fireEvent.click(tab('Test Run'));
    const test = await screen.findByTestId('workflow-test-run');
    await waitFor(() => expect(test.textContent).toContain('Sample event'), SAVED);
    calls.push(...page.calls);
    page.unmount();
    return calls;
}

/** Every key anywhere in `value`. */
function keysIn(value: unknown): string[] {
    if (Array.isArray(value)) return value.flatMap(keysIn);
    if (!value || typeof value !== 'object') return [];
    return Object.entries(value).flatMap(([key, inner]) => [key, ...keysIn(inner)]);
}

/** Holds that nothing the pages read or sent carries a secret the account holds, nor a credential's data. */
async function holdsNoSecret(calls: Call[]) {
    for (const call of calls) {
        const sent = JSON.stringify(call.body);
        const read = await call.answer;
        for (const secret of [...Object.values(SECRETS), OUTPUT_SECRET]) {
            expect(sent, `${asLine(call)} sent a secret`).not.toContain(secret);
            expect(read, `${asLine(call)} read a secret`).not.toContain(secret);
        }
        const keys = keysIn(call.body);
        for (const key of ['credential_id', 'credentialIds', 'credential_ids', 'credential_data', 'data', 'token', 'api_key']) {
            expect(keys, `${asLine(call)} sent ${key}`).not.toContain(key);
        }
    }
}

describe('the workflows pages acting as a key', () => {
    it('list, make and open workflows, change and add steps, run, set up and test one without asking for what only the account’s owner may do', { timeout: 120_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const actsAs of ['owner', 'key'] as const) {
            for (const id of Object.keys(graphRecords)) delete graphRecords[id];
            forgetAuthoring();
            forgetTestRuns();
            const calls = await session(actsAs);
            cleanup();
            await holdsNoSecret(calls);
            for (const call of calls) {
                called.add(asLine(call));
                if (actsAs === 'key' && isOwnerOnly(call.method, call.path)) refused.push(asLine(call));
                expect(await call.answer, `${asLine(call)} was refused`).not.toContain('permission_denied');
                // A variable's value is read by the one read that answers its owner, and never sent back unchanged.
                const readsValues = asLine(call) === `GET /v1/workflows/${WORKFLOW}/variables`;
                expect((await call.answer).includes(VARIABLE_SECRET), `${asLine(call)} read a variable's value`).toBe(actsAs === 'owner' && readsValues);
                expect(JSON.stringify(call.body), `${asLine(call)} sent a variable's value`).not.toContain(VARIABLE_SECRET);
            }
        }
        expect(refused).toEqual([]);
        expect(offClient).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./workflowsCalls.txt');
    });

    it('save what a step’s panel changes as the canvas’s own edit, once, naming the step and the setting alone', { timeout: 60_000 }, async () => {
        const page = draw(scene('canvas'), 'key');
        await waitFor(() => expect(page.container.querySelector('.react-flow__node[data-id="slack"]')).not.toBeNull(), SAVED);
        await select(page.container, 'slack');
        const panel = await screen.findByTestId('step-panel');
        const text = await waitFor(() => {
            const field = panel.querySelector('input[data-field-key="text"], textarea[data-field-key="text"]');
            expect(field).not.toBeNull();
            return field as HTMLInputElement;
        }, SAVED);
        fireEvent.change(text, { target: { value: 'Order in.' } });
        await waitFor(() => expect(edits(page.calls)).toHaveLength(1), SAVED);
        expect(edits(page.calls)[0].body).toMatchObject({ if_version: 4, ops: [{ op: 'update_step', id: 'slack', settings: { text: 'Order in.' } }] });
        // The step's own accounts are the canvas's to save too: the panel's pickers write nothing themselves.
        expect(page.calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/options')).map(asLine)).toEqual([`POST /v1/workflows/${WORKFLOW}/edits`]);
        await holdsNoSecret(page.calls);
        expect(offClient).toEqual([]);
    });

    it('open a workflow the key may only look at read-only: nothing added, run or saved', { timeout: 60_000 }, async () => {
        const page = draw(scene('viewer'), 'key');
        await waitFor(() => expect(page.container.querySelector('.react-flow__node[data-id="slack"]')).not.toBeNull(), SAVED);
        await screen.findByTestId('workflow-view-only');
        expect(screen.queryByRole('button', { name: /add step/i })).toBeNull();
        expect(screen.queryByRole('button', { name: 'Run' })).toBeNull();
        expect(surface(page.container).nodesDraggable).toBe(false);
        // A step's panel shows the step and takes no input.
        await select(page.container, 'slack');
        const panel = await screen.findByTestId('step-panel');
        expect(panel.textContent).toContain('Changing it takes edit access');
        expect((panel.querySelector('fieldset') as HTMLFieldSetElement).disabled).toBe(true);
        // Nothing is written: what the canvas holds is never saved, asked outright.
        flushAllGraphsNow();
        await act(async () => {
            await Promise.resolve();
        });
        // (The step's form reads its dropdown's choices, a read the API takes as a POST.)
        expect(page.calls.filter((c) => c.method !== 'GET' && !c.path.endsWith('/options')).map(asLine)).toEqual([]);
        expect(offClient).toEqual([]);
    });
});
