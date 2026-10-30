// @vitest-environment jsdom
// A write through the graph service (/v1/workflows/{id}/edits, a restore) sends every canvas open on the
// workflow, whoever's, what changed as the builder's events in the workflow's room on the relay
// (coder/workflow/graph_service.py: canvas_events). An open canvas applies them to its own copy, so its next save
// carries the write instead of putting the old steps back.
import type { Edge, Node } from '@xyflow/react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { FETCH_WHOLE_TRIES, useMCPBuilderEvents } from '~/hooks/useMCPBuilderEvents';
import { WorkflowPresenceService } from '~/lib/collaboration/workflowPresenceService';
import { markStepPartial, reloadFromServer, takeServerStep } from '~/lib/liveGraphStore';
import { sendEventAsync } from '~/lib/socket-sender';

const handlers: Record<string, (event: unknown) => void> = {};
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn((event: string, handler: (event: unknown) => void) => {
        handlers[event] = handler;
        return () => undefined;
    }),
    socketReceiver: { injectWireEvent: (event: string, payload: unknown) => handlers[event]?.(payload) },
}));
const { stored } = vi.hoisted(() => ({ stored: {} as Record<string, Record<string, unknown>> }));
vi.mock('~/lib/socket-sender', () => ({
    sendEventAsync: vi.fn(async (event: { node_id: string }) => {
        if (!(event.node_id in stored)) throw new Error('Request timeout after 30000ms');
        return { config: stored[event.node_id] };
    }),
}));
vi.mock('~/lib/liveGraphStore', () => ({
    markStepPartial: vi.fn(), takeServerStep: vi.fn(), reloadFromServer: vi.fn(async () => true),
}));

class RoomSocket {
    static last: RoomSocket;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: ((event: { code: number }) => void) | null = null;
    onerror: ((error: unknown) => void) | null = null;
    readyState = 1;

    constructor(public url: string) {
        RoomSocket.last = this;
    }

    send(): void {}

    close(): void {}
}

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

    it('reaches a collaborator\'s canvas through the workflow\'s room', () => {
        vi.stubGlobal('WebSocket', RoomSocket);
        const room = new WorkflowPresenceService();
        room.connect({ workflowId: 'wf', localUser: { id: 'collaborator', name: 'Sam' }, token: 'token' });
        const { state, setNodes, setEdges } = canvas(
            [
                createWorkflowNode('hook', 'trigger-webhook', { x: 0, y: 0 }, { label: 'Hook' }),
                createWorkflowNode('note', 'log', { x: 0, y: 200 }, { label: 'Note' }),
            ],
            [{ id: 'hook-note', source: 'hook', target: 'note' }],
        );
        const { unmount } = renderHook(() => useMCPBuilderEvents({ workflowId: 'wf', setNodes, setEdges }));
        const heard = (event: Record<string, unknown>) =>
            act(() => RoomSocket.last.onmessage!({ data: JSON.stringify(event) }));

        heard({
            type: 'mcp:builder_event', workflow_id: 'wf', execution_id: 'graph-1', event_type: 'node_removed',
            data: { nodeId: 'hook', removedEdgeIds: ['hook-note'] },
        });
        heard({
            type: 'mcp:builder_event', workflow_id: 'wf', execution_id: 'graph-1', event_type: 'node_updated',
            data: { nodeId: 'note', config: { label: 'Order note' } },
        });
        heard({ type: 'workflow:graph_changed', workflow_id: 'wf', base_version: 1, version: 3 });

        expect(state.nodes.map((n) => n.id)).toEqual(['note']);
        expect(state.nodes[0].data.label).toBe('Order note');
        expect(state.edges).toEqual([]);
        unmount();
        room.disconnect();
        vi.unstubAllGlobals();
    });

    it('fetches a step whole when the room held part of it back, holding it in part until it has', async () => {
        const { state, setNodes, setEdges } = canvas(
            [createWorkflowNode('fetch', 'automation-http-request', { x: 0, y: 0 }, { label: 'Fetch' })], []);
        const { unmount } = renderHook(() => useMCPBuilderEvents({ workflowId: 'wf', setNodes, setEdges }));
        stored.fetch = { label: 'Fetch', url: 'https://api.example', api_key: 'sk-live-123' };
        await act(async () => {
            handlers['mcp:builder_event']({
                workflow_id: 'wf', event_type: 'node_updated',
                data: { nodeId: 'fetch', config: { url: 'https://api.example' }, refetch: true },
            });
        });
        expect(sendEventAsync).toHaveBeenCalledWith(expect.objectContaining({
            event_name: 'workflow:node:get_config', workflow_id: 'wf', node_id: 'fetch',
        }));
        expect(markStepPartial).toHaveBeenCalledWith('wf', 'fetch');
        expect(takeServerStep).toHaveBeenCalledWith('wf', 'fetch', stored.fetch);
        expect(reloadFromServer).not.toHaveBeenCalled();
        const config = state.nodes[0].data.config as Record<string, unknown>;
        expect(config.url).toBe('https://api.example');
        expect(config.api_key).toBe('sk-live-123');
        unmount();
    });

    it('reads the whole workflow again when it can\'t read a step whole, never saving its partial copy', async () => {
        vi.useFakeTimers();
        const { setNodes, setEdges } = canvas(
            [createWorkflowNode('big', 'log', { x: 0, y: 0 }, { label: 'Big' })], []);
        const { unmount } = renderHook(() => useMCPBuilderEvents({ workflowId: 'wf', setNodes, setEdges }));
        delete stored.big;
        await act(async () => {
            handlers['mcp:builder_event']({
                workflow_id: 'wf', event_type: 'node_updated', data: { nodeId: 'big', refetch: true },
            });
            await vi.runAllTimersAsync();
        });
        expect(sendEventAsync).toHaveBeenCalledTimes(FETCH_WHOLE_TRIES);
        expect(markStepPartial).toHaveBeenCalledWith('wf', 'big');
        expect(takeServerStep).not.toHaveBeenCalled();
        expect(reloadFromServer).toHaveBeenCalledWith('wf');
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
