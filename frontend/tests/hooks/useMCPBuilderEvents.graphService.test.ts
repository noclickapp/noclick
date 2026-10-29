// @vitest-environment jsdom
// A write through the graph service (/v1/workflows/{id}/edits, a restore) sends the canvases open on the
// workflow what changed as the builder's events (coder/workflow/graph_service.py: canvas_events). An open canvas
// applies them to its own copy, so its next save carries the write instead of putting the old steps back.
import type { Edge, Node } from '@xyflow/react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { useMCPBuilderEvents } from '~/hooks/useMCPBuilderEvents';

const handlers: Record<string, (event: unknown) => void> = {};
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn((event: string, handler: (event: unknown) => void) => {
        handlers[event] = handler;
        return () => undefined;
    }),
}));

afterEach(() => vi.clearAllMocks());

function canvas(nodes: Node[], edges: Edge[]) {
    const state = { nodes, edges };
    const setNodes = vi.fn((change: Node[] | ((prev: Node[]) => Node[])) => {
        state.nodes = typeof change === 'function' ? change(state.nodes) : change;
    });
    const setEdges = vi.fn((change: Edge[] | ((prev: Edge[]) => Edge[])) => {
        state.edges = typeof change === 'function' ? change(state.edges) : change;
    });
    return { state, setNodes, setEdges };
}

describe('a graph service write on an open canvas', () => {
    it('adds, changes, wires, moves and removes the steps as the write did', () => {
        vi.useFakeTimers();
        const { state, setNodes, setEdges } = canvas(
            [
                createWorkflowNode('hook', 'trigger-webhook', { x: 0, y: 0 }, { label: 'Hook' }),
                createWorkflowNode('note', 'log', { x: 0, y: 200 }, { label: 'Note', message: 'done' }),
            ],
            [{ id: 'hook-note', source: 'hook', target: 'note' }],
        );
        const { unmount } = renderHook(() => useMCPBuilderEvents({ workflowId: 'wf', setNodes, setEdges }));
        const send = (event_type: string, data: Record<string, unknown>) =>
            act(() => handlers['mcp:builder_event']({ workflow_id: 'wf', event_type, data }));

        send('node_removed', { nodeId: 'hook', removedEdgeIds: ['hook-note'] });
        send('node_updated', { nodeId: 'note', config: { label: 'Order note', message: null } });
        send('node_start', { node: { id: 'done', type: 'log', position: { x: 0, y: 400 }, label: 'Done' } });
        send('node_updated', {
            nodeId: 'done', type: 'log', position: { x: 0, y: 400 }, config: { label: 'Done', message: 'ok' },
        });
        send('edge_added', { edge: { id: 'note-done', source: 'note', target: 'done' } });
        send('layout_applied', { positions: { note: { x: 400, y: 80 } } });
        act(() => vi.runAllTimers());

        expect(state.nodes.map((n) => n.id)).toEqual(['note', 'done']);
        const note = state.nodes[0];
        expect(note.data.label).toBe('Order note');
        expect((note.data.config as Record<string, unknown>).message ?? null).toBeNull();
        expect(note.position).toEqual({ x: 400, y: 80 });
        const done = state.nodes[1];
        expect(done.data.label).toBe('Done');
        expect((done.data.config as Record<string, unknown>).message).toBe('ok');
        expect(state.edges.map((e) => [e.source, e.target])).toEqual([['note', 'done']]);
        unmount();
        vi.useRealTimers();
    });

    it('leaves another workflow alone', () => {
        const { state, setNodes, setEdges } = canvas(
            [createWorkflowNode('note', 'log', { x: 0, y: 0 }, { label: 'Note' })], []);
        const { unmount } = renderHook(() => useMCPBuilderEvents({ workflowId: 'wf', setNodes, setEdges }));
        act(() => handlers['mcp:builder_event']({
            workflow_id: 'other', event_type: 'node_removed', data: { nodeId: 'note' },
        }));
        expect(state.nodes.map((n) => n.id)).toEqual(['note']);
        unmount();
    });
});
