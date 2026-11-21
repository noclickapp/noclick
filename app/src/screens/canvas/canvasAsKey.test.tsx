// @vitest-environment happy-dom
// The canvas acting as one of the account's keys, as this app serves it: what has moved into the app so far (its
// graph: the store that saves it, graph/liveGraphStore.ts; and its drawing: the steps and connections, nodes/ and
// edges/) opens a workflow, edits it in each way a canvas does, meets another writer's change, closes, and draws what
// it holds, over fixtures that refuse what only the account's signed-in owner may do (screens/console/ownerOnly.ts)
// exactly as the API refuses a key, and none of it asks for one. What it calls, as the owner and as a key, is kept in
// canvasCalls.txt (`npx vitest run -u` writes it again), which NoClick's own tests call on its real API as a key and
// hold to the table. And what it does with what it reads: every request goes through the app's client (none off its
// origin), and no secret the account holds is in anything it reads or sends.
import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react';
import { Position, ReactFlow, ReactFlowProvider, type Edge, type Node } from '@xyflow/react';
import { NoClick } from 'noclick';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
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
import { GRAPH_SAVES, STEP_DRAWING } from './slots';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    body: Json;
    answer: Promise<string>;
}

/** Requests that left the app's client: a `fetch` of its own, an XHR, a socket. */
const offClient: string[] = [];

// The plain drawing loads with the first step a canvas draws (drawingStandards.tsx): loaded once here, with real timers,
// so each canvas below draws its steps rather than their outlines.
beforeAll(async () => {
    const { result, unmount } = renderHook(() => standing(STEP_DRAWING).useLoaded([]));
    await waitFor(() => expect(result.current).toBe(true));
    unmount();
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

describe('the canvas acting as a key', () => {
    it('opens, edits, merges and closes a workflow without asking for what only the account’s owner may do', async () => {
        const called = new Set<string>();
        const refused: string[] = [];
        for (const actsAs of ['owner', 'key'] as const) {
            for (const id of Object.keys(graphRecords)) delete graphRecords[id];
            const calls = await session(actsAs);
            const { nodes, edges } = graphRecords[WORKFLOW];
            calls.push(...(await drawing(actsAs, { nodes, edges })).calls);
            cleanup();
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
