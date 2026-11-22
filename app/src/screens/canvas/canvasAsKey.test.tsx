// @vitest-environment happy-dom
// The canvas acting as one of the account's keys, as this app serves it: what has moved into the app so far (its
// graph: the store that saves it, graph/liveGraphStore.ts; its drawing: the steps and connections, nodes/ and edges/;
// its editing surface with the palette, surface/ and WorkflowCanvas.tsx; and its runs and results, runs/) opens a
// workflow, edits it in each way a canvas does, meets another writer's change, closes, and draws what it holds; the
// canvas on its own adds a step from the palette, connects, moves, copies and pastes, deletes and brings back steps
// and follows another writer's commit; and it reads its run log, a step's outputs and one run's results, runs it
// (whole, and one step alone) and stops a run, over fixtures
// that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts)
// exactly as the API refuses a key, and none of it asks for one. What it calls, as the owner and as a key, is kept in
// canvasCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key and
// hold to the table. And what it does with what it reads: every request goes through the app's client (none off its
// origin), and no secret the account holds is in anything it reads or sends.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider, type Edge, type Node } from '@xyflow/react';
import { NoClick } from 'noclick';
import { useState, type ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { fill, standing } from '@/slots';
import { applyNodeUpdate, createWorkflowNode } from '@/screens/canvas/applyNodeUpdate';
import { isOwnerOnly } from '@/screens/console/ownerOnly';
import AnimatedWorkflowEdge from './edges/AnimatedWorkflowEdge';
import { CustomConnectionLine } from './edges/CustomConnectionLine';
import { graphFetch, SECRETS, stored, WORKFLOW, type EditAnswer } from './graph/fixtures';
import { buildLazyNodeTypes } from './nodes/lazyNodeTypes';
import {
    flushAllGraphsNow,
    graphRecords,
    markGraphDirty,
    recordDeletedNodes,
    recordGraphSnapshot,
    reloadFromServer,
    setCanvasEditsClient,
    setCanvasMounted,
    setGraphLoaded,
} from './graph/liveGraphStore';
import { V1_GRAPH_SAVES } from './graph/saves';
import { OUTPUT_SECRET, RUNS, runsFetch, stepsOf } from './runs/fixtures';
import { OutputPanel } from './runs/OutputPanel';
import type { WorkflowExecutionLog } from './runs/RunLog';
import { useRunLog } from './runs/useRunLog';
import { useWorkflowRuns } from './runs/useRun';
import { GRAPH_SAVES, RUN_READS, RUN_RESULTS, STEP_DRAWING } from './slots';
import { WorkflowCanvas } from './WorkflowCanvas';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    body: Json;
    answer: Promise<string>;
}

/** Requests that left the app's client: a `fetch` of its own, an XHR, a socket. */
const offClient: string[] = [];

/** What the canvas last put on the clipboard. */
const clipboard = { text: '' };

// The plain drawing loads with the first step a canvas draws (drawingStandards.tsx), the SDK with the standards' first
// read and the palette when it first opens: loaded once here, with real timers, so each canvas below draws its steps
// rather than their outlines.
beforeAll(async () => {
    await import('./standardsSdk');
    await import('./surface/StepPalette');
    Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: { writeText: async (text: string) => void (clipboard.text = text), readText: async () => clipboard.text },
    });
    const { result, unmount } = renderHook(() => standing(STEP_DRAWING).useLoaded([]));
    await waitFor(() => expect(result.current).toBe(true));
    unmount();
    // The standards' SDK and the standard's results view load with their first use: once here, too.
    await Promise.all([import('./standardsSdk'), import('./runs/RunSteps')]);
});

beforeEach(() => {
    vi.useFakeTimers();
    offClient.length = 0;
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
    vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
        offClient.push(`fetch ${String(input)}`);
        return Promise.reject(new Error('the canvas reached the network outside its client'));
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
    const open = XMLHttpRequest.prototype.open;
    vi.spyOn(XMLHttpRequest.prototype, 'open').mockImplementation(function (this: XMLHttpRequest, ...args: Parameters<typeof open>) {
        offClient.push(`XHR ${String(args[1])}`);
        return open.apply(this, args);
    });
});

afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    setCanvasEditsClient(null);
});

const asLine = ({ method, path }: { method: string; path: string }) => `${method} ${path}`;

/** Lets what's queued run: the debounce, the answers and what the store does with them. */
async function settle(ms = 2500) {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 30; i++) await Promise.resolve();
}

/** A workflow opened, edited in each way a canvas does, moved on by another writer, then the tab closed. */
async function session(actsAs: 'owner' | 'key'): Promise<Call[]> {
    const calls: Call[] = [];
    const theirs = stored();
    theirs.nodes.push({ id: 'theirs', type: 'log', position: { x: 0, y: 400 }, config: { label: 'Theirs' } });
    const answers: Array<(body: Json) => EditAnswer> = [() => ({ conflict: { version: 7, graph: theirs } })];
    setCanvasEditsClient(new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: graphFetch({
            actsAs,
            edit: (body) => (answers.shift() ?? ((b: Json) => ({ version: ((b.if_version as number) ?? 4) + 1 })))(body),
            observe: (method, path, answered, body) => {
                calls.push({ method, path, body, answer: answered.then((response) => response.clone().text()) });
            },
        }),
    }));

    // Opened: the graph read from the API.
    recordGraphSnapshot(WORKFLOW, false, { nodes: [], edges: [] }, false);
    setCanvasMounted(WORKFLOW, false, true);
    setGraphLoaded(WORKFLOW, true);
    expect(await reloadFromServer(WORKFLOW)).toBe(true);
    await settle();
    const rec = graphRecords[WORKFLOW];
    expect(rec.nodes.map((n) => n.id)).toEqual(['hook', 'agent', 'slack', 'victim']);

    // Edited: a rename, another account chosen, a step added and connected, one moved and one deleted.
    rec.nodes = rec.nodes.map((n) => {
        if (n.id === 'agent') return applyNodeUpdate(n, { label: 'Sorter', credentialIds: { agent_openai: 'cred_openai_2' } });
        if (n.id === 'hook') return { ...n, position: { x: -40, y: 80 } };
        return n;
    });
    rec.nodes = [...rec.nodes.filter((n) => n.id !== 'victim'), createWorkflowNode('mine', 'log', { x: 960, y: 240 }, { label: 'Mine' })];
    rec.edges = [...rec.edges, { id: 'slack-mine', source: 'slack', target: 'mine' } as Edge];
    recordDeletedNodes(WORKFLOW, ['victim']);
    markGraphDirty(WORKFLOW);
    // Refused for another writer's change, merged, and saved again on their version.
    await settle();
    await settle();
    expect(rec.graphVersion).toBe(8);
    expect(rec.nodes.map((n) => n.id)).toEqual(['hook', 'agent', 'slack', 'mine', 'theirs']);

    // Closed with one more change.
    rec.nodes = rec.nodes.map((n) => (n.id === 'slack' ? applyNodeUpdate(n, { config: { channel: 'C02' } }) : n));
    markGraphDirty(WORKFLOW);
    flushAllGraphsNow();
    await settle(0);
    return calls;
}

const HANDLE = 16;
/** Where a step's handles sit, by its type: a test's DOM has no layout to measure them in. */
function handlesOf(type: string): NonNullable<Node['handles']> {
    const at = (id: string | null, kind: 'source' | 'target', position: Position, x: number, y: number) => ({ id, type: kind, position, x, y, width: HANDLE, height: HANDLE });
    const handles = [at(null, 'source', Position.Right, 82, 37)];
    if (type !== 'trigger-webhook') handles.push(at(null, 'target', Position.Left, -8, 37));
    if (type === 'agent') handles.push(at('bottom', 'target', Position.Bottom, 37, 82));
    if (type === 'automation-slack') handles.push(at('top', 'source', Position.Top, 37, -8));
    return handles;
}

/** The workflow as the store holds it, drawn: each step as the canvas's node types draw it and each connection as its
 *  edge does, with what the API says of each step's type. */
async function drawing(actsAs: 'owner' | 'key', graph: { nodes: Node[]; edges: Edge[] }): Promise<{ calls: Call[]; container: HTMLElement }> {
    const calls: Call[] = [];
    const client = new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: graphFetch({
            actsAs,
            observe: (method, path, answered, body) => {
                calls.push({ method, path, body, answer: answered.then((response) => response.clone().text()) });
            },
        }),
    });
    const nodes = graph.nodes.map((n) => ({ ...n, width: 90, height: 90, handles: handlesOf(String(n.type)) }));
    const edges = graph.edges.map((e) => ({ ...e, type: 'animated' }));
    const { container } = render(
        <ClientProvider client={client}>
            <div style={{ width: 1600, height: 900 }}>
                <ReactFlowProvider>
                    <ReactFlow nodes={nodes} edges={edges} nodeTypes={buildLazyNodeTypes()} edgeTypes={{ animated: AnimatedWorkflowEdge }} connectionLineComponent={CustomConnectionLine} />
                </ReactFlowProvider>
            </div>
        </ClientProvider>
    );
    await act(() => settle(500));
    return { calls, container };
}

/** What the canvas hands React Flow, read from the element React Flow draws. */
function surfaceOf(container: HTMLElement): Json {
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

async function press(target: Document | Window, init: KeyboardEventInit) {
    await act(() => {
        fireEvent.keyDown(target, init);
    });
    await act(() => {
        fireEvent.keyUp(target, init);
    });
}

/** The canvas on its own (WorkflowCanvas.tsx): opened, a step added from the palette, two connected, one moved, two
 *  copied and pasted, one deleted from the keyboard, brought back and deleted again, another writer's commit followed,
 *  then closed. */
async function editing(actsAs: 'owner' | 'key'): Promise<Call[]> {
    const calls: Call[] = [];
    let server = stored();
    let version = 4;
    const client = new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        // The canvas reads its run log as it opens: the runs' fixtures answer that, the graph's the rest.
        fetch: runsFetch({
            actsAs,
            graph: {
                server: () => server,
                version: () => version,
                edit: (body) => ({ version: (version = ((body.if_version as number | undefined) ?? version) + 1) }),
            },
            observe: (method, path, answered, body) => {
                calls.push({ method, path, body, answer: answered.then((response) => response.clone().text()) });
            },
        }),
    });
    const live = createWorkLive();
    const { container, unmount } = render(
        <ClientProvider client={client}>
            <WorkLiveContext.Provider value={live}>
                <div style={{ width: 1200, height: 800 }}>
                    <WorkflowCanvas workflowId={WORKFLOW} />
                </div>
            </WorkLiveContext.Provider>
        </ClientProvider>
    );
    await act(() => settle(500));
    expect(graphRecords[WORKFLOW].nodes.map((n) => n.id)).toEqual(['hook', 'agent', 'slack', 'victim']);

    // A step from the palette.
    fireEvent.click(screen.getByRole('button', { name: /add step/i }));
    await act(() => settle(300));
    fireEvent.change(screen.getByRole('textbox', { name: 'Search steps' }), { target: { value: 'log' } });
    await act(() => settle(300));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search steps' }), { key: 'Enter' });
    const added = graphRecords[WORKFLOW].nodes.find((n) => n.type === 'log' && n.id !== 'victim');
    expect(added).toBeDefined();

    // Connected as the rules allow, moved, deleted and brought back.
    const surface = () => surfaceOf(container);
    expect((surface().isValidConnection as (c: object) => boolean)({ source: 'victim', sourceHandle: null, target: 'hook', targetHandle: null })).toBe(false);
    await act(() => (surface().onConnect as (c: object) => void)({ source: 'slack', sourceHandle: null, target: added!.id, targetHandle: null }));
    await act(() => (surface().onNodesChange as (c: object[]) => void)([{ type: 'position', id: 'victim', position: { x: 980, y: 60 }, dragging: true }]));
    await act(() => (surface().onNodesChange as (c: object[]) => void)([{ type: 'position', id: 'victim', position: { x: 1000, y: 80 }, dragging: false }]));
    await act(() => settle(2500));

    // The agent and the step after it copied and pasted: the copy holds none of their secrets, and the pasted steps
    // keep their accounts by id.
    const choose = (chosen: string[]) =>
        act(() => (surface().onNodesChange as (c: object[]) => void)(graphRecords[WORKFLOW].nodes.map((n) => ({ type: 'select', id: n.id, selected: chosen.includes(n.id) }))));
    await choose(['agent', 'slack']);
    await act(async () => {
        window.dispatchEvent(new Event('copy', { bubbles: true, cancelable: true }));
        await Promise.resolve();
    });
    const copied = JSON.parse(clipboard.text) as { nodes: Array<{ id: string; config: Json }>; edges: Json[] };
    expect(copied.nodes.map((n) => n.id)).toEqual(['agent', 'slack']);
    expect(copied.nodes[0].config.credentialIds).toEqual({ agent_openai: 'cred_openai' });
    for (const secret of Object.values(SECRETS)) expect(clipboard.text).not.toContain(secret);
    for (const key of ['api_key', 'signing_secret', 'token']) expect(keysIn(copied)).not.toContain(key);
    await act(() => {
        const event = new Event('paste', { bubbles: true, cancelable: true });
        Object.assign(event, { clipboardData: { getData: () => clipboard.text } });
        window.dispatchEvent(event);
    });
    await act(() => settle(2500));
    expect(graphRecords[WORKFLOW].nodes.filter((n) => n.type === 'agent')).toHaveLength(2);

    await choose(['victim']);
    // Each lands in the undo history a task later.
    await press(document, { key: 'Backspace' });
    await act(() => settle(0));
    await press(window, { key: 'z', metaKey: true, ctrlKey: true });
    await act(() => settle(0));
    await press(window, { key: 'z', metaKey: true, ctrlKey: true, shiftKey: true });
    await act(() => settle(2500));
    expect(graphRecords[WORKFLOW].nodes.map((n) => n.id)).not.toContain('victim');

    // Another writer's commit, heard on the account's change stream and read again.
    server = { ...server, nodes: [...server.nodes, { id: 'theirs', type: 'log', position: { x: 0, y: 400 }, config: { label: 'Theirs' } }] };
    version += 1;
    act(() => live.deliver('platform:resource', { kind: 'workflow', id: WORKFLOW, status: null, parent_id: null, version }));
    await act(() => settle(2500));
    expect(graphRecords[WORKFLOW].nodes.map((n) => n.id)).toContain('theirs');

    // Closed with one more change.
    await act(() => (surface().onNodesChange as (c: object[]) => void)([{ type: 'position', id: 'theirs', position: { x: 40, y: 420 } }]));
    unmount();
    await settle(0);
    return calls;
}

/** The workflow's runs and results as the canvas shows them, and running it: the run log (a page, the next, the failed
 *  ones, the counts), a step's stored outputs and the shape a step type outputs, a run of the whole workflow and of one
 *  step alone, a run someone else started followed and stopped, and one run's results. On real timers: each read is
 *  waited for. */
async function runsAndResults(actsAs: 'owner' | 'key'): Promise<Call[]> {
    const calls: Call[] = [];
    const client = new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: runsFetch({
            actsAs,
            oneRun: (id) => {
                const found = RUNS.find((r) => r.id === id) ?? { ...RUNS[0], id };
                return { ...found, steps: stepsOf(id) };
            },
            observe: (method, path, answered, body) => {
                calls.push({ method, path, body, answer: answered.then((response) => response.clone().text()) });
            },
        }),
    });
    const live = createWorkLive();
    const wrapper = ({ children }: { children: ReactNode }) => (
        <ClientProvider client={client}>
            <WorkLiveContext.Provider value={live}>{children}</WorkLiveContext.Provider>
        </ClientProvider>
    );

    // The run log.
    const log = renderHook(
        () => {
            const reads = standing(RUN_READS).useRunReads();
            const [logs, setLogs] = useState<WorkflowExecutionLog[]>([]);
            return { logs, log: useRunLog({ workflowId: WORKFLOW, reads, setLogs }) };
        },
        { wrapper }
    );
    await waitFor(() => expect(log.result.current.logs).toHaveLength(2));
    await waitFor(() => expect(log.result.current.log.counts.total).toBe(5));
    act(() => log.result.current.log.onLoadMore());
    await waitFor(() => expect(log.result.current.logs).toHaveLength(4));
    act(() => log.result.current.log.onFiltersChange({ status: 'error', trigger: 'all', query: '' }));
    await waitFor(() => expect(log.result.current.logs.map((l) => l.id)).toEqual(['run_4']));
    log.unmount();

    // A step's outputs across runs, and what a step type outputs before it ran.
    const node = (id: string, type: string, data: Json = {}): Node => ({ id, type, position: { x: 0, y: 0 }, data: { label: id, ...data } });
    const panel = render(<OutputPanel selectedNode={node('hook', 'trigger-webhook')} workflowId={WORKFLOW} />, { wrapper });
    await waitFor(() => expect(panel.container.textContent).toContain('2 of 2'));
    panel.unmount();
    const expected = render(<OutputPanel selectedNode={node('unrun', 'automation-slack', { operation: `send_message_as_${actsAs}` })} workflowId={WORKFLOW} />, { wrapper });
    await waitFor(() => expect(expected.container.textContent).toContain('Expected Output'));
    expected.unmount();

    // Running: the whole workflow, one step alone, and a run someone else started, followed then stopped.
    const runs = renderHook(
        () => {
            const [, setNodes] = useState<Node[]>([node('hook', 'trigger-webhook'), node('agent', 'agent'), node('slack', 'automation-slack')]);
            return useWorkflowRuns({ client, workflowId: WORKFLOW, setNodes });
        },
        { wrapper }
    );
    await act(() => runs.result.current.run());
    await act(() => runs.result.current.run({ fromStep: 'slack', only: true }));
    expect(runs.result.current.error).toBeNull();
    act(() => live.deliver('platform:resource', { kind: 'workflow_run', id: 'run_3', parent_id: WORKFLOW }));
    await waitFor(() => expect(runs.result.current.running).toEqual(['run_3']));
    await act(() => runs.result.current.stop());
    runs.unmount();

    // One run's results.
    const Results = standing(RUN_RESULTS);
    const results = render(<Results workflowId={WORKFLOW} runId="run_4" onClose={() => undefined} />, { wrapper });
    await screen.findByTestId('run-step-slack');
    results.unmount();
    return calls;
}

/** Every key anywhere in `value`. */
function keysIn(value: unknown): string[] {
    if (Array.isArray(value)) return value.flatMap(keysIn);
    if (!value || typeof value !== 'object') return [];
    return Object.entries(value).flatMap(([key, inner]) => [key, ...keysIn(inner)]);
}

/** Holds that nothing the canvas read or sent carries a secret the account holds, nor a credential's data. */
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

describe('the canvas acting as a key', () => {
    it('opens, edits, merges, closes, draws and runs a workflow without asking for what only the account’s owner may do', { timeout: 30_000 }, async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const actsAs of ['owner', 'key'] as const) {
            for (const id of Object.keys(graphRecords)) delete graphRecords[id];
            const calls = await session(actsAs);
            const { nodes, edges } = graphRecords[WORKFLOW];
            calls.push(...(await drawing(actsAs, { nodes, edges })).calls);
            cleanup();
            for (const id of Object.keys(graphRecords)) delete graphRecords[id];
            calls.push(...(await editing(actsAs)));
            cleanup();
            vi.useRealTimers();
            calls.push(...(await runsAndResults(actsAs)));
            cleanup();
            vi.useFakeTimers();
            await holdsNoSecret(calls);
            for (const call of calls) {
                called.add(asLine(call));
                if (actsAs === 'key' && isOwnerOnly(call.method, call.path)) refused.push(asLine(call));
                expect(await call.answer, `${asLine(call)} was refused`).not.toContain('permission_denied');
            }
        }
        expect(refused).toEqual([]);
        expect(offClient).toEqual([]);
        await expect([...called].sort().join('\n') + '\n').toMatchFileSnapshot('./canvasCalls.txt');
    });

    it('chooses an account by its id and never sends its values, saving each change as the edit that made it', async () => {
        const calls = await session('key');
        const edits = calls.filter((c) => asLine(c) === `POST /v1/workflows/${WORKFLOW}/edits`);
        // The same changes again on their version, in the order the merge holds the steps.
        expect(edits.map((e) => [e.body.if_version ?? null, (e.body.ops as Json[]).map((op) => op.op).sort()])).toEqual([
            [4, ['add_step', 'connect', 'move', 'remove_step', 'set_connection', 'update_step']],
            [7, ['add_step', 'connect', 'move', 'remove_step', 'set_connection', 'update_step']],
            [null, ['update_step']],
        ]);
        expect((edits[0].body.ops as Json[]).find((op) => op.op === 'set_connection')).toEqual({
            op: 'set_connection', id: 'agent', connection: 'cred_openai_2', slot: 'agent_openai',
        });
        await holdsNoSecret(calls);
        expect(offClient).toEqual([]);
    });

    it('edits on its own, adding from the palette and pasting a copy, without asking for an owner’s call or sending a value', async () => {
        const calls = await editing('key');
        const edits = calls.filter((c) => asLine(c) === `POST /v1/workflows/${WORKFLOW}/edits`);
        expect(edits.map((e) => (e.body.ops as Json[]).map((op) => op.op).sort())).toEqual([
            ['add_step', 'connect', 'move'],
            ['add_step', 'add_step', 'connect', 'set_connection', 'set_connection'],
            ['remove_step'],
            ['move'],
        ]);
        // Each on the version the last left; closing sends the last change at once, on the version after the commit.
        expect(edits.map((e) => e.body.if_version ?? null)).toEqual([4, 5, 6, 8]);
        // The pasted steps: new ids, their settings as copied, each account by its id.
        const pasted = edits[1].body.ops as Json[];
        expect(pasted.filter((op) => op.op === 'add_step').map((op) => op.type)).toEqual(['agent', 'automation-slack']);
        expect(pasted.filter((op) => op.op === 'set_connection').map((op) => [op.slot, op.connection])).toEqual([
            ['agent_openai', 'cred_openai'],
            ['slack_oauth', 'cred_slack'],
        ]);
        expect(calls.filter((c) => asLine(c) === `GET /v1/workflows/${WORKFLOW}/graph`)).toHaveLength(2);
        expect(calls.some((c) => asLine(c) === 'GET /v1/step_types')).toBe(true);
        for (const call of calls) expect(isOwnerOnly(call.method, call.path), asLine(call)).toBe(false);
        await holdsNoSecret(calls);
        expect(offClient).toEqual([]);
    });

    it('draws each step and connection as the API says of its type, reading nothing else', async () => {
        recordGraphSnapshot(WORKFLOW, false, { nodes: [], edges: [] }, false);
        const { nodes, edges } = stored();
        const graph = {
            nodes: nodes.map((n) => createWorkflowNode(String(n.id), String(n.type), n.position as { x: number; y: number }, n.config as Record<string, unknown>)),
            edges: edges as Edge[],
        };
        const { calls, container } = await drawing('key', graph);
        expect(calls.map(asLine).sort()).toEqual([
            'GET /v1/step_types/agent',
            'GET /v1/step_types/automation-slack',
            'GET /v1/step_types/log',
            'GET /v1/step_types/trigger-webhook',
        ]);
        await holdsNoSecret(calls);
        expect(offClient).toEqual([]);
        const node = (id: string) => container.querySelector(`.react-flow__node[data-id="${id}"]`) as HTMLElement;
        expect([...container.querySelectorAll('.react-flow__node')].map((n) => n.getAttribute('data-id'))).toEqual(['hook', 'agent', 'slack', 'victim']);
        // The webhook starts runs: the bolt, and nothing flows in.
        expect(node('hook').querySelector('.react-flow__handle-left')).toBeNull();
        expect(node('hook').querySelector('[title^="Trigger"] svg.lucide-zap')).not.toBeNull();
        // Slack can be an agent's tools: its handle on top; the agent takes tools in from below.
        expect(node('slack').querySelector('.react-flow__handle-top')).not.toBeNull();
        expect(node('agent').querySelector('.react-flow__handle-bottom')).not.toBeNull();
        expect(node('victim').querySelector('.react-flow__handle-top')).toBeNull();
        // Each step's label, and each connection.
        expect(container.textContent).toContain('Agent');
        expect([...container.querySelectorAll('.react-flow__edge')].map((e) => e.getAttribute('data-id'))).toEqual(['hook-agent', 'agent-slack']);
    });
});
