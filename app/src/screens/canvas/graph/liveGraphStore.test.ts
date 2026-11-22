// The graph store as this app runs it, with no host: every save is the edits that changed the graph since what the
// server holds (its per-step base), sent through the app's client on the version the canvas holds, and a refusal for a
// stale version is merged three ways and saved again. What it must never do: drop a setting someone took out, bring
// back a step someone deleted, or lose a closing tab's edits. A host with its own whole-graph save (canvas.graph.saves)
// gets the same merging over its own wire.
import type { Edge, Node } from '@xyflow/react';
import { NoClick, Workflow } from 'noclick';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fill } from '@/slots';
import { applyNodeUpdate, createWorkflowNode } from '@/screens/canvas/applyNodeUpdate';
import { GRAPH_SAVES } from '../slots';
import { graphFetch, SECRETS, stored, WORKFLOW, type EditAnswer } from './fixtures';
import {
    applyToBase,
    canvasSaveTransportOf,
    flushAllGraphsNow,
    flushGraphNow,
    graphRecords,
    markGraphDirty,
    markStepPartial,
    recordDeletedNodes,
    recordGraphSnapshot,
    seedSaveBaseline,
    setCanvasEditsClient,
    setCanvasMounted,
    setGraphLoaded,
    setGraphReadOnly,
    setGraphVersion,
} from './liveGraphStore';
import { V1_GRAPH_SAVES, type WholeGraphAnswer, type WholeGraphSave } from './saves';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    body: Json;
    keepalive: boolean;
}

let calls: Call[] = [];
let server = stored();
let version = 4;
let answers: Array<(body: Json) => EditAnswer> = [];

function client(): NoClick {
    return new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: graphFetch({
            server: () => server,
            version: () => version,
            edit: (body) => (answers.shift() ?? ((b: Json) => ({ version: ((b.if_version as number | undefined) ?? version) + 1 })))(body),
            observe: (method, path, _answered, body, init) => calls.push({ method, path, body, keepalive: init?.keepalive === true }),
        }),
    });
}

interface Held {
    nodes: Node[];
    edges: Edge[];
}

/** The canvas opens the workflow as the API reads it. `meanwhile` is what it holds once the load's merge has landed,
 *  having been changed while the load was out; the baseline is what the load read either way. */
async function open(c: NoClick, meanwhile: (loaded: Held) => Held = (loaded) => loaded) {
    const graph = await Workflow.fromId(WORKFLOW, { client: c }).graph();
    const raw = graph.raw as { nodes: Json[]; edges: Json[] };
    const nodes = raw.nodes.map((n) => createWorkflowNode(String(n.id), String(n.type), n.position as Node['position'], n.config as Json));
    const edges = raw.edges.map((e) => ({ id: String(e.id), source: String(e.source), target: String(e.target) }) as Edge);
    recordGraphSnapshot(WORKFLOW, false, meanwhile({ nodes, edges }), false);
    setCanvasMounted(WORKFLOW, false, true);
    setGraphLoaded(WORKFLOW, true);
    setGraphVersion(WORKFLOW, graph.version);
    seedSaveBaseline(WORKFLOW, { nodes, edges });
    calls = [];
}

const rec = () => graphRecords[WORKFLOW];

function change(id: string, update: Parameters<typeof applyNodeUpdate>[1]) {
    rec().nodes = rec().nodes.map((n) => (n.id === id ? applyNodeUpdate(n, update) : n));
    markGraphDirty(WORKFLOW);
}

function remove(id: string) {
    rec().nodes = rec().nodes.filter((n) => n.id !== id);
    rec().edges = rec().edges.filter((e) => e.source !== id && e.target !== id);
    recordDeletedNodes(WORKFLOW, [id]);
}

/** Lets the debounce fire and what it sent be answered. */
async function settle(ms = 2500) {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 20; i++) await Promise.resolve();
}

const edits = () => calls.filter((c) => c.method === 'POST' && c.path === `/v1/workflows/${WORKFLOW}/edits`);

beforeEach(() => {
    vi.useFakeTimers();
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
    calls = [];
    server = stored();
    version = 4;
    answers = [];
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    setCanvasEditsClient(null);
});

describe('the graph store on /v1', () => {
    it('writes nothing when a workflow is opened and nothing changed', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        markGraphDirty(WORKFLOW);
        await settle();
        expect(calls).toEqual([]);
    });

    it('sends only what changed, on the version it holds, and a setting taken out as null', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        change('agent', { label: 'Sorter', config: { temperature: 0.5 } });
        rec().nodes = rec().nodes.map((n) => {
            if (n.id !== 'agent') return n;
            const config = { ...(n.data.config as Json) };
            delete config.model;
            return { ...n, data: { ...n.data, config } };
        });
        markGraphDirty(WORKFLOW);
        await settle();
        expect(edits().map((e) => e.body)).toEqual([
            {
                ops: [{ op: 'update_step', id: 'agent', settings: { model: null, temperature: 0.5, label: 'Sorter' } }],
                if_version: 4, source: 'canvas', origin: expect.stringMatching(/^canvas-/),
            },
        ]);
        expect(rec().graphVersion).toBe(5);
        expect(canvasSaveTransportOf(WORKFLOW)).toBe('edits');
        // The next save diffs from what landed: nothing more to send.
        markGraphDirty(WORKFLOW);
        await settle();
        expect(edits()).toHaveLength(1);
    });

    it('never brings back a step it deleted when another writer moved the workflow on, and saves again on their version', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        // Another writer renamed the trigger and added a step; the server still holds the step this canvas deletes.
        const theirs = stored();
        (theirs.nodes[0].config as Json).label = 'Orders';
        theirs.nodes.push({ id: 'theirs', type: 'log', position: { x: 0, y: 240 }, config: { label: 'Theirs' } });
        answers = [() => ({ conflict: { version: 7, graph: theirs } })];
        change('agent', { label: 'Mine' });
        remove('victim');
        await settle();
        const ids = rec().nodes.map((n) => n.id);
        expect(ids).toEqual(['hook', 'agent', 'slack', 'theirs']);
        expect(rec().nodes.find((n) => n.id === 'hook')!.data.label).toBe('Orders');
        expect(rec().nodes.find((n) => n.id === 'agent')!.data.label).toBe('Mine');
        await settle();
        expect(edits().map((e) => [e.body.if_version, e.body.ops])).toEqual([
            [4, [{ op: 'remove_step', id: 'victim' }, { op: 'update_step', id: 'agent', settings: { label: 'Mine' } }]],
            [7, [{ op: 'remove_step', id: 'victim' }, { op: 'update_step', id: 'agent', settings: { label: 'Mine' } }]],
        ]);
        expect(rec().graphVersion).toBe(8);
        expect(rec().deletedNodeIds.size).toBe(0);
    });

    it('sends a closing tab’s own changes at once, as one keepalive batch on no version', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        change('agent', { label: 'Closing' });
        rec().nodes = [...rec().nodes, createWorkflowNode('late', 'log', { x: 0, y: 400 }, { label: 'Late' })];
        remove('victim');
        flushAllGraphsNow();
        for (let i = 0; i < 50; i++) await Promise.resolve();
        expect(edits()).toEqual([
            {
                method: 'POST',
                path: `/v1/workflows/${WORKFLOW}/edits`,
                keepalive: true,
                body: {
                    ops: [
                        { op: 'remove_step', id: 'victim' },
                        { op: 'update_step', id: 'agent', settings: { label: 'Closing' } },
                        { op: 'add_step', type: 'log', id: 'late', settings: { label: 'Late' }, position: { x: 0, y: 400 } },
                    ],
                    source: 'canvas',
                    origin: expect.stringMatching(/^canvas-/),
                },
            },
        ]);
    });

    it('reads the server’s graph first when it never knew it, then sends its own changes', async () => {
        const c = client();
        setCanvasEditsClient(c);
        recordGraphSnapshot(WORKFLOW, false, {
            nodes: [createWorkflowNode('hook', 'trigger-webhook', { x: 0, y: 0 }, { label: 'Inbound', http_method: 'POST' })],
            edges: [],
        }, false);
        setCanvasMounted(WORKFLOW, false, true);
        setGraphLoaded(WORKFLOW, true);
        setGraphVersion(WORKFLOW, 4);
        markGraphDirty(WORKFLOW);
        await settle();
        expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
            `GET /v1/workflows/${WORKFLOW}/graph`,
            `POST /v1/workflows/${WORKFLOW}/edits`,
        ]);
        // Its own rename, never the server's secret it never read.
        expect(edits()[0].body.ops).toEqual([{ op: 'update_step', id: 'hook', settings: { label: 'Inbound' } }]);
    });

    it('edits no step it holds only in part, and never saves for a viewer', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        markStepPartial(WORKFLOW, 'agent');
        change('agent', { label: 'Half' });
        change('hook', { label: 'Inbound' });
        await settle();
        expect(edits().map((e) => e.body.ops)).toEqual([[{ op: 'update_step', id: 'hook', settings: { label: 'Inbound' } }]]);

        setGraphReadOnly(WORKFLOW, true);
        change('hook', { label: 'Viewer' });
        await settle();
        expect(edits()).toHaveLength(1);
    });

    it('moves its base with a written change it heard, so its next save sends only its own', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        const filled = { nodeId: 'hook', config: { label: 'Webhook', http_method: 'POST', webhook_url: 'https://hooks.example.test/hook' } };
        rec().nodes = rec().nodes.map((n) => (n.id === 'hook' ? applyNodeUpdate(n, { config: { webhook_url: 'https://hooks.example.test/hook' } }) : n));
        applyToBase(WORKFLOW, 'node_updated', filled);
        change('agent', { label: 'After the write' });
        await settle();
        expect(edits().map((e) => e.body.ops)).toEqual([[{ op: 'update_step', id: 'agent', settings: { label: 'After the write' } }]]);
    });

    it('sends no secret the server holds and reads none, whatever it saves', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        const theirs = stored();
        answers = [() => ({ conflict: { version: 9, graph: theirs } })];
        change('agent', { label: 'Mine' });
        change('hook', { label: 'Inbound' });
        await settle();
        await settle();
        const sent = JSON.stringify(calls.map((call) => call.body));
        for (const secret of Object.values(SECRETS)) expect(sent).not.toContain(secret);
        expect(JSON.stringify(rec().nodes)).not.toContain(SECRETS.agentKey);
    });
});

// The canvas takes edits as soon as it mounts, and a load's merge keeps a step added while the load was out and leaves
// out one removed meanwhile. The baseline and the base are what the load read, so that work is the canvas's own and is
// saved: taken for the server's, the added step was never written and the removed one stayed on the server.
describe('changes made before the load answered', () => {
    const late = () => createWorkflowNode('late', 'log', { x: 0, y: 400 }, { label: 'Late' });
    const lateEdge = { id: 'agent-late', source: 'agent', target: 'late' } as Edge;

    it('saves a step added meanwhile, with its connection, then has nothing more to send', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c, ({ nodes, edges }) => ({ nodes: [...nodes, late()], edges: [...edges, lateEdge] }));
        expect(rec().dirty).toBe(true);
        await settle();
        expect(edits().map((e) => e.body)).toEqual([
            {
                ops: [
                    { op: 'add_step', type: 'log', id: 'late', settings: { label: 'Late' }, position: { x: 0, y: 400 } },
                    { op: 'connect', from: 'agent', to: 'late', id: 'agent-late', kind: 'data' },
                ],
                if_version: 4, source: 'canvas', origin: expect.stringMatching(/^canvas-/),
            },
        ]);
        expect([...rec().base!.nodes.keys()]).toEqual(['hook', 'agent', 'slack', 'victim', 'late']);
        markGraphDirty(WORKFLOW);
        await settle();
        expect(edits()).toHaveLength(1);
    });

    it('still writes a step added meanwhile when it is changed later', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c, ({ nodes, edges }) => ({ nodes: [...nodes, late()], edges }));
        change('late', { label: 'Later' });
        await settle();
        expect(edits().map((e) => e.body.ops)).toEqual([
            [{ op: 'add_step', type: 'log', id: 'late', settings: { label: 'Later' }, position: { x: 0, y: 400 } }],
        ]);
    });

    it('sends a step added meanwhile with a closing tab’s changes', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c, ({ nodes, edges }) => ({ nodes: [...nodes, late()], edges }));
        flushAllGraphsNow();
        for (let i = 0; i < 50; i++) await Promise.resolve();
        expect(edits().map((e) => [e.keepalive, e.body.ops])).toEqual([
            [true, [{ op: 'add_step', type: 'log', id: 'late', settings: { label: 'Late' }, position: { x: 0, y: 400 } }]],
        ]);
    });

    it('removes a step deleted meanwhile, which the load’s merge left out', async () => {
        const c = client();
        setCanvasEditsClient(c);
        // The canvas showed the workflow from an earlier open, and its Slack step was deleted before the load answered.
        recordGraphSnapshot(WORKFLOW, false, { nodes: [], edges: [] }, false);
        recordDeletedNodes(WORKFLOW, ['slack']);
        await open(c, ({ nodes, edges }) => ({
            nodes: nodes.filter((n) => n.id !== 'slack'),
            edges: edges.filter((e) => e.source !== 'slack' && e.target !== 'slack'),
        }));
        await settle();
        expect(edits().map((e) => [e.body.if_version, e.body.ops])).toEqual([[4, [{ op: 'remove_step', id: 'slack' }]]]);
        expect(rec().deletedNodeIds.size).toBe(0);
        expect([...rec().base!.nodes.keys()]).toEqual(['hook', 'agent', 'victim']);
        expect([...rec().base!.edges.keys()]).toEqual(['hook-agent']);
    });

    it('takes what the canvas holds for loaded when the load carried no list of it', async () => {
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        seedSaveBaseline(WORKFLOW, {});
        expect(rec().dirty).toBe(false);
        markGraphDirty(WORKFLOW);
        await settle();
        expect(calls).toEqual([]);
    });
});

describe('a host’s own whole-graph save', () => {
    function host() {
        const sent: WholeGraphSave[] = [];
        const closed: WholeGraphSave[] = [];
        const replies: Array<(answer: WholeGraphAnswer) => void> = [];
        let paused = false;
        fill(GRAPH_SAVES, {
            transportFor: () => 'socket',
            socket: {
                save: (save, answer) => {
                    sent.push(save);
                    replies.push(answer);
                    return () => undefined;
                },
                close: (save) => void closed.push(save),
            },
            read: V1_GRAPH_SAVES.read,
            paused: () => paused,
        });
        return { sent, closed, replies, pause: (p: boolean) => { paused = p; } };
    }

    it('hands it the whole graph on the version it holds, and merges a conflict’s answer before saving again', async () => {
        const wire = host();
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        change('agent', { label: 'Mine' });
        remove('victim');
        await settle();
        expect(wire.sent).toHaveLength(1);
        expect(wire.sent[0]).toMatchObject({ workflowId: WORKFLOW, isSkill: false, ifVersion: 4, deletedNodeIds: ['victim'], partialNodeIds: [] });
        expect((wire.sent[0].graph.nodes as Json[]).map((n) => n.id)).toEqual(['hook', 'agent', 'slack']);
        const theirs = stored();
        theirs.nodes.push({ id: 'theirs', type: 'log', position: { x: 0, y: 240 }, config: { label: 'Theirs' } });
        wire.replies[0]({ conflict: true, graph: theirs, version: 6 });
        await settle();
        expect(wire.sent).toHaveLength(2);
        expect(wire.sent[1].ifVersion).toBe(6);
        expect((wire.sent[1].graph.nodes as Json[]).map((n) => n.id)).toEqual(['hook', 'agent', 'slack', 'theirs']);
        wire.replies[1]({ landed: true, version: 7 });
        await settle();
        expect(rec().graphVersion).toBe(7);
        expect(rec().deletedNodeIds.size).toBe(0);
        expect(calls.filter((call) => call.method === 'POST')).toEqual([]);
    });

    it('waits while another writer holds the graph, and sends a closing tab’s save with what it changed', async () => {
        const wire = host();
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        wire.pause(true);
        change('agent', { label: 'Held' });
        await settle();
        expect(wire.sent).toEqual([]);
        wire.pause(false);
        rec().edges = rec().edges.filter((e) => e.id !== 'agent-slack');
        flushAllGraphsNow();
        expect(wire.closed).toHaveLength(1);
        expect(wire.closed[0]).toMatchObject({ ifVersion: 4, changes: { steps: ['agent'], edges_added: [], edges_removed: ['agent-slack'] } });
    });

    it('fails loudly for a record that saves whole where no host has a save of its own', async () => {
        fill(GRAPH_SAVES, { ...V1_GRAPH_SAVES, transportFor: () => 'socket' });
        const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const c = client();
        setCanvasEditsClient(c);
        await open(c);
        change('agent', { label: 'Nowhere' });
        flushGraphNow(WORKFLOW);
        expect(error).toHaveBeenCalledWith(expect.stringContaining('there is none'));
        expect(calls).toEqual([]);
    });
});
