/**
 * A canvas save as /v1 edits: what the canvas holds, diffed against its base, as the ops the TS SDK sends. The ops
 * pinned here are the ones NoClick's own tests apply as `source: canvas` and hold
 * equal to the whole-graph save (an agent's drawn handles, a harness's own connection slot, the Interface tab's
 * layout, a note where it was drawn, a setting taken out as null).
 */
import { describe, expect, it } from 'vitest';
import { EditBatch, Workflow } from 'noclick';
import { baseAfterGroups, canvasEditGroups, intoBatches, MAX_OPS, type CanvasGraph, type GraphBase } from './canvasEdits';
import type { SerializedWorkflowEdge, SerializedWorkflowNode } from '@/screens/canvas/applyNodeUpdate';

type Config = Record<string, unknown>;

const step = (id: string, type: string, config: Config, extra: Partial<SerializedWorkflowNode> = {}): SerializedWorkflowNode => (
    { id, type, position: { x: 0, y: 0 }, config, ...extra }
);
const edge = (id: string, source: string, target: string, sourceHandle: string | null = null,
              targetHandle: string | null = null): SerializedWorkflowEdge => ({ id, source, target, sourceHandle, targetHandle });

function baseOf(nodes: SerializedWorkflowNode[], edges: SerializedWorkflowEdge[] = [], layout?: unknown): GraphBase {
    return {
        nodes: new Map(nodes.map((n) => [n.id, JSON.stringify(n)])),
        edges: new Map(edges.map((e) => [e.id, JSON.stringify(e)])),
        interface: layout === undefined ? undefined : layout === null ? null : JSON.stringify(layout),
    };
}

function opsFor(base: GraphBase, graph: Partial<CanvasGraph>, skip: string[] = []) {
    const batch = new EditBatch(Workflow.fromId('wf-1'), {});
    for (const g of canvasEditGroups(base, { nodes: [], edges: [], interface: null, ...graph }, new Set(skip))) g.queue(batch);
    return batch.ops;
}

const AGENT = { label: 'Helper', model: 'openrouter/~openai/gpt-luna-latest', message: 'Sum up.' };

describe('a canvas save as /v1 edits', () => {
    it('sends nothing for an echo of what the server holds', () => {
        const nodes = [step('agent', 'agent', AGENT)];
        expect(opsFor(baseOf(nodes, [], null), { nodes })).toEqual([]);
    });

    it("joins the handles an agent's edges were drawn between, and names its tools edge as tools", () => {
        const nodes = [step('hook', 'trigger-webhook', { label: 'Hook' }), step('agent', 'agent', AGENT),
                       step('log', 'log', { label: 'Log', message: 'done' }), step('post', 'automation-slack', { label: 'Post' })];
        const ops = opsFor(baseOf(nodes), {
            nodes,
            edges: [edge('xy-edge__hook-agentleft', 'hook', 'agent', null, 'left'),
                    edge('xy-edge__agentright-logleft', 'agent', 'log', 'right', 'left'),
                    edge('xy-edge__posttop-agentbottom', 'post', 'agent', 'top', 'bottom')],
        });
        expect(ops).toEqual([
            { op: 'connect', from: 'hook', to: 'agent', kind: 'data', id: 'xy-edge__hook-agentleft', target_handle: 'left' },
            { op: 'connect', from: 'agent', to: 'log', kind: 'data', id: 'xy-edge__agentright-logleft', handle: 'right',
              target_handle: 'left' },
            { op: 'connect', from: 'post', to: 'agent', kind: 'tools', id: 'xy-edge__posttop-agentbottom' },
        ]);
    });

    it("files a connection under the slot the canvas holds it in, and takes one off by its slot", () => {
        const before = step('agent', 'agent', { label: 'Coder', model: 'claude-code', message: 'Fix it.',
                                                credentialIds: { slack_oauth: 'old' } });
        const after = step('agent', 'agent', { label: 'Coder', model: 'claude-code', message: 'Fix it.',
                                               credentialIds: { agent_claude_code: 'key-1' } });
        expect(opsFor(baseOf([before]), { nodes: [after] })).toEqual([
            { op: 'set_connection', id: 'agent', connection: null, slot: 'slack_oauth' },
            { op: 'set_connection', id: 'agent', connection: 'key-1', slot: 'agent_claude_code' },
        ]);
    });

    it("sends the Interface tab's layout when it changed from what it knew", () => {
        const nodes = [step('agent', 'agent', AGENT)];
        const layout = { layout: [{ i: 'agent', x: 0, y: 0, w: 6, h: 4 }], tabOrder: ['agent'] };
        expect(opsFor(baseOf(nodes, [], null), { nodes, interface: layout })).toEqual([
            { op: 'update_workflow', interface: layout },
        ]);
        expect(opsFor(baseOf(nodes, [], layout), { nodes, interface: layout })).toEqual([]);
        // A base that never knew it sends nothing of it (it can't tell its change from the server's).
        expect(opsFor(baseOf(nodes), { nodes, interface: layout })).toEqual([]);
    });

    it('sends each setting it changed whole, and one taken out as null', () => {
        const before = step('cron', 'trigger-cron', { label: 'Every morning', timezone: 'UTC',
                                                       schedule: { frequency: 'hourly', minute: 5 }, retired_field: 'old' });
        const after = step('cron', 'trigger-cron', { label: 'Every morning', timezone: 'UTC',
                                                      schedule: { frequency: 'daily', time: '08:00' } });
        expect(opsFor(baseOf([before]), { nodes: [after] })).toEqual([
            { op: 'update_step', id: 'cron', settings: { schedule: { frequency: 'daily', time: '08:00' }, retired_field: null } },
        ]);
    });

    it('adds a step where the canvas put it, with its operation, connections, mock and size, then wires it', () => {
        const added = step('fetch', 'automation-http-request', {
            label: 'Fetch', operation: 'send_http_get_request', url: 'https://api.example', _settings: { retry: 2 },
            _triggerPayload: { never: 'sent' }, credentialIds: { http_bearer_token: 'cred-1', empty: '' },
            mockedOutput: { ok: true },
        }, { position: { x: 420, y: 80 }, width: 300, height: 180 });
        const ops = opsFor(baseOf([step('agent', 'agent', AGENT)]), {
            nodes: [step('agent', 'agent', AGENT), added], edges: [edge('agent-fetch', 'agent', 'fetch')],
        });
        expect(ops).toEqual([
            { op: 'add_step', type: 'automation-http-request', operation: 'send_http_get_request', id: 'fetch',
              position: { x: 420, y: 80 }, settings: { label: 'Fetch', url: 'https://api.example', _settings: { retry: 2 } } },
            { op: 'set_connection', id: 'fetch', connection: 'cred-1', slot: 'http_bearer_token' },
            { op: 'mock_step', id: 'fetch', output: { ok: true } },
            { op: 'move', id: 'fetch', position: { x: 420, y: 80 }, width: 300, height: 180 },
            { op: 'connect', from: 'agent', to: 'fetch', kind: 'data', id: 'agent-fetch' },
        ].map((op) => expect.objectContaining(op)));
    });

    it("switches a step's operation, unmocks it and moves it, never writing a runtime key", () => {
        const before = step('post', 'automation-slack', { label: 'Post', operation: 'send_message', mockedOutput: { ts: 1 },
                                                          _executionId: 'run-1' });
        const after = step('post', 'automation-slack', { label: 'Post', operation: 'add_reaction', _executionId: 'run-2' },
                           { position: { x: 5, y: 5 } });
        expect(opsFor(baseOf([before]), { nodes: [after] })).toEqual([
            { op: 'update_step', id: 'post', operation: 'add_reaction' },
            { op: 'unmock_step', id: 'post' },
            { op: 'move', id: 'post', position: { x: 5, y: 5 } },
        ]);
    });

    it('removes a step without disconnecting its edges, which go with it', () => {
        const nodes = [step('a', 'log', {}), step('b', 'log', {})];
        expect(opsFor(baseOf(nodes, [edge('a-b', 'a', 'b')]), { nodes: [nodes[0]] })).toEqual([
            { op: 'remove_step', id: 'b' },
        ]);
    });

    it('disconnects an edge it removed, and one drawn again between other handles is disconnected then connected', () => {
        const nodes = [step('a', 'conditional', {}), step('b', 'log', {}), step('c', 'log', {})];
        const ops = opsFor(baseOf(nodes, [edge('a-b', 'a', 'b', 'true'), edge('a-c', 'a', 'c', 'true')]), {
            nodes, edges: [edge('a-c', 'a', 'c', 'false')],
        });
        expect(ops).toEqual([
            { op: 'disconnect', from: 'a', to: 'b', id: 'a-b' },
            { op: 'disconnect', from: 'a', to: 'c', id: 'a-c' },
            { op: 'connect', from: 'a', to: 'c', kind: 'data', id: 'a-c', handle: 'false' },
        ]);
    });

    it('a step of another type now is taken out and added again, its edges connected again', () => {
        const before = [step('a', 'log', {}), step('b', 'log', { label: 'B' })];
        const after = [step('a', 'log', {}), step('b', 'automation-slack', { label: 'B' })];
        const ops = opsFor(baseOf(before, [edge('a-b', 'a', 'b')]), { nodes: after, edges: [edge('a-b', 'a', 'b')] });
        expect(ops.map((op) => [op.op, op.id])).toEqual([['remove_step', 'b'], ['add_step', 'b'], ['connect', 'a-b']]);
    });

    it('adds a note where it was drawn: its colour, or the default taken off, then its size', () => {
        const drawn = step('note-1', 'stickyNote', { content: 'Read me', color: 3 },
                           { position: { x: 40, y: -120 }, width: 280, height: 160 });
        expect(opsFor(baseOf([]), { nodes: [drawn] })).toEqual([
            { op: 'add_note', content: 'Read me', id: 'note-1', color: 3, position: { x: 40, y: -120 } },
            { op: 'move', id: 'note-1', position: { x: 40, y: -120 }, width: 280, height: 160 },
        ]);
        const plain = step('note-2', 'stickyNote', { content: 'Plain', label: 'x' });
        expect(opsFor(baseOf([]), { nodes: [plain] })).toEqual([
            { op: 'add_note', content: 'Plain', id: 'note-2', position: { x: 0, y: 0 } },
            { op: 'update_step', id: 'note-2', settings: { color: null, label: 'x' } },
        ]);
    });

    it('touches no step it holds in part, nor its edges when the server holds no such step', () => {
        const nodes = [step('a', 'log', { label: 'A' })];
        const ops = opsFor(baseOf(nodes), {
            nodes: [step('a', 'log', { label: 'A changed' }), step('partial', 'log', { label: 'half' })],
            edges: [edge('a-partial', 'a', 'partial')],
        }, ['a', 'partial']);
        expect(ops).toEqual([]);
    });

    it('splits a large save into batches /v1 takes, keeping a step\'s own ops together', () => {
        const nodes = Array.from({ length: 120 }, (_, i) => step(`s${i}`, 'log', { credentialIds: { log_key: `k${i}` } }));
        const batches = intoBatches(canvasEditGroups(baseOf([]), { nodes, edges: [], interface: null }));
        expect(batches.length).toBe(2);
        for (const batch of batches) expect(batch.reduce((n, g) => n + g.size, 0)).toBeLessThanOrEqual(MAX_OPS);
        expect(batches.flat().every((g) => g.size === 2)).toBe(true);
    });

    it('the base after a batch holds what it sent, and nothing of what it removed', () => {
        const nodes = [step('a', 'log', {}), step('b', 'log', {})];
        const base = baseOf(nodes, [edge('a-b', 'a', 'b')], null);
        const graph: CanvasGraph = { nodes: [step('a', 'log', { label: 'A' })], edges: [], interface: { layout: [] } };
        const after = baseAfterGroups(base, canvasEditGroups(base, graph));
        expect([...after.nodes.keys()]).toEqual(['a']);
        expect(after.nodes.get('a')).toBe(JSON.stringify(graph.nodes[0]));
        expect([...after.edges.keys()]).toEqual([]);
        expect(after.interface).toBe(JSON.stringify({ layout: [] }));
        expect(canvasEditGroups(after, graph)).toEqual([]);
    });
});
