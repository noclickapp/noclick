// @vitest-environment jsdom
// Undo walks back the person's own edits, never a written server change: each change the canvas takes from the
// server is applied to every state in its undo history (so NoClick filling in a trigger's fields a second after it's
// added, or an API rename, survives an undo of the person's own edit), and a conflict that takes the server's graph
// wholesale starts the history again from the graph as it then stands.
import { act, renderHook } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';
import { describe, expect, it, vi } from 'vitest';

const { handlers, acks } = vi.hoisted(() => ({
    handlers: {} as Record<string, (data: unknown) => void>,
    acks: [] as Array<(response: unknown) => void>,
}));
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn((event: string, handler: (data: unknown) => void) => {
        handlers[event] = handler;
        return () => undefined;
    }),
}));
vi.mock('~/lib/socket-sender', () => ({
    sendEvent: vi.fn(),
    sendEventWithCallback: vi.fn((_event: unknown, ack: (response: unknown) => void) => {
        acks.push(ack);
        return () => undefined;
    }),
}));
vi.mock('~/lib/headless-builder', () => ({ headlessBuilder: { isActive: vi.fn(() => false) } }));
vi.mock('~/lib/activeGenStore', () => ({ activeGenStore: { gens: {}, byWorkflow: {} } }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { set: vi.fn() } }));

import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import {
    flushGraphNow,
    graphRecords,
    markGraphDirty,
    recordGraphSnapshot,
    seedSaveBaseline,
    setCanvasMounted,
    setGraphLoaded,
    setGraphVersion,
} from '~/lib/liveGraphStore';
import { useUndoKeepsServerWrites } from '~/hooks/useUndoKeepsServerWrites';
import { useWorkflowUndoRedo } from '~/hooks/useWorkflowUndoRedo';

const WF = 'wf-undo-server-writes';
const step = (id: string, label: string, config: Record<string, unknown> = {}) =>
    createWorkflowNode(id, 'log', { x: 0, y: 0 }, { label, ...config });
const label = (nodes: Node[], id: string) => (nodes.find((n) => n.id === id)?.data as { label?: string })?.label;

function canvas(nodes: Node[]) {
    recordGraphSnapshot(WF, false, { nodes, edges: [] }, false);
    setCanvasMounted(WF, false, true);
    setGraphLoaded(WF, true);
    setGraphVersion(WF, 1);
    seedSaveBaseline(WF);
    const shown = { nodes, edges: [] as Edge[] };
    const hook = renderHook(() => {
        const undo = useWorkflowUndoRedo(nodes, [], {
            onNodesChange: (n) => { shown.nodes = n; },
            onEdgesChange: (e) => { shown.edges = e; },
        });
        useUndoKeepsServerWrites(WF, undo.rebaseHistory, undo.resetBaseline);
        return undo;
    });
    return { hook, shown };
}

describe('undo and written server changes', () => {
    it("keeps NoClick's and the API's writes when the person undoes their own edit", () => {
        const { hook, shown } = canvas([step('hook', 'Hook'), step('log', 'Log')]);
        // The person adds a step.
        act(() => hook.result.current.captureState([step('hook', 'Hook'), step('log', 'Log'), step('mine', 'Mine')], []));
        // A second later NoClick fills in the trigger's webhook fields, and an API edit renames hook.
        act(() => {
            handlers['mcp:builder_event']({
                workflow_id: WF, event_type: 'node_updated', committed: true,
                data: { nodeId: 'hook', config: { webhook_url: 'https://hooks.example/1', label: 'Orders' } },
            });
        });
        act(() => hook.result.current.undo());
        expect(shown.nodes.map((n) => n.id)).toEqual(['hook', 'log']);
        const hook0 = shown.nodes.find((n) => n.id === 'hook')!;
        expect(label(shown.nodes, 'hook')).toBe('Orders');
        expect((hook0.data.config as Record<string, unknown>).webhook_url).toBe('https://hooks.example/1');
        expect(hook.result.current.canUndo).toBe(false);
    });

    it('never brings back a connection to a step the server removed', () => {
        const { hook, shown } = canvas([step('hook', 'Hook'), step('log', 'Log')]);
        // The person connects hook to log (never saved), then adds a step.
        const wired = [{ id: 'hook-log', source: 'hook', target: 'log' }] as Edge[];
        act(() => hook.result.current.captureState([step('hook', 'Hook'), step('log', 'Log')], wired));
        act(() => hook.result.current.captureState(
            [step('hook', 'Hook'), step('log', 'Log'), step('mine', 'Mine')], wired));
        // An API edit removes log; the server never had the connection, so its event doesn't name it.
        act(() => {
            handlers['mcp:builder_event']({
                workflow_id: WF, event_type: 'node_removed', committed: true, data: { nodeId: 'log' },
            });
        });
        act(() => hook.result.current.undo());
        expect(shown.nodes.map((n) => n.id)).toEqual(['hook']);
        expect(shown.edges).toEqual([]);
    });

    it('starts the history again after a conflict takes the server graph', () => {
        const { hook, shown } = canvas([step('log', 'Log')]);
        act(() => hook.result.current.captureState([step('log', 'Log'), step('mine', 'Mine')], []));
        graphRecords[WF].nodes = [step('log', 'Mine'), step('extra', 'Extra')];
        markGraphDirty(WF);
        flushGraphNow(WF);
        act(() => acks[0]({ conflict: true, graph_version: 3, workflow_data: { nodes: [
            { id: 'log', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Log' } },
            { id: 'theirs', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Theirs' } },
        ], edges: [] } }));
        expect(hook.result.current.canUndo).toBe(false);
        act(() => hook.result.current.undo());
        expect(shown.nodes.map((n) => n.id)).toEqual(['log']);
    });
});
