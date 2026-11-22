// @vitest-environment happy-dom
// Undo over the per-step base: it walks back the person's own edits, never a written change the canvas took from the
// server (each is applied to every state in the undo history), and a conflict that takes the server's graph wholesale
// starts the history again from the graph as it then stands.
import { act, renderHook } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';
import { NoClick } from 'noclick';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fill } from '@/slots';
import { createWorkflowNode } from '@/screens/canvas/applyNodeUpdate';
import { GRAPH_SAVES } from '../slots';
import { graphFetch, stored, WORKFLOW } from './fixtures';
import {
    applyToBase,
    flushGraphNow,
    graphRecords,
    markGraphDirty,
    recordGraphSnapshot,
    seedSaveBaseline,
    setCanvasEditsClient,
    setCanvasMounted,
    setGraphLoaded,
    setGraphVersion,
} from './liveGraphStore';
import { V1_GRAPH_SAVES } from './saves';
import { useUndoKeepsServerWrites } from './useUndoKeepsServerWrites';
import { useWorkflowUndoRedo } from './useWorkflowUndoRedo';

const step = (id: string, label: string, config: Record<string, unknown> = {}) => createWorkflowNode(id, 'log', { x: 0, y: 0 }, { label, ...config });
const label = (nodes: Node[], id: string) => (nodes.find((n) => n.id === id)?.data as { label?: string })?.label;

function canvas(nodes: Node[]) {
    recordGraphSnapshot(WORKFLOW, false, { nodes, edges: [] }, false);
    setCanvasMounted(WORKFLOW, false, true);
    setGraphLoaded(WORKFLOW, true);
    setGraphVersion(WORKFLOW, 4);
    seedSaveBaseline(WORKFLOW);
    const shown = { nodes, edges: [] as Edge[] };
    const hook = renderHook(() => {
        const undo = useWorkflowUndoRedo(nodes, [], {
            onNodesChange: (n) => {
                shown.nodes = n;
            },
            onEdgesChange: (e) => {
                shown.edges = e;
            },
        });
        useUndoKeepsServerWrites(WORKFLOW, undo.rebaseHistory, undo.resetBaseline);
        return undo;
    });
    return { hook, shown };
}

beforeEach(() => {
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
    fill(GRAPH_SAVES, V1_GRAPH_SAVES);
});

afterEach(() => {
    setCanvasEditsClient(null);
    vi.useRealTimers();
});

describe('undo over the base', () => {
    it('keeps a written change when the person undoes their own edit', () => {
        const { hook, shown } = canvas([step('hook', 'Hook'), step('log', 'Log')]);
        act(() => hook.result.current.captureState([step('hook', 'Hook'), step('log', 'Log'), step('mine', 'Mine')], []));
        act(() => applyToBase(WORKFLOW, 'node_updated', { nodeId: 'hook', config: { webhook_url: 'https://hooks.example.test/1', label: 'Orders' } }));
        act(() => hook.result.current.undo());
        expect(shown.nodes.map((n) => n.id)).toEqual(['hook', 'log']);
        expect(label(shown.nodes, 'hook')).toBe('Orders');
        expect((shown.nodes[0].data.config as Record<string, unknown>).webhook_url).toBe('https://hooks.example.test/1');
        expect(hook.result.current.canUndo).toBe(false);
    });

    it('starts the history again once a conflict takes the server’s graph', async () => {
        vi.useFakeTimers();
        const theirs = stored();
        setCanvasEditsClient(new NoClick({
            apiKey: 'nk_test', baseUrl: 'https://api.test', maxRetries: 0,
            fetch: graphFetch({ edit: () => ({ conflict: { version: 6, graph: theirs } }) }),
        }));
        const { hook, shown } = canvas([step('log', 'Log')]);
        act(() => hook.result.current.captureState([step('log', 'Log'), step('mine', 'Mine')], []));
        graphRecords[WORKFLOW].nodes = [step('log', 'Mine'), step('extra', 'Extra')];
        markGraphDirty(WORKFLOW);
        flushGraphNow(WORKFLOW);
        await act(async () => {
            for (let i = 0; i < 30; i++) await Promise.resolve();
        });
        expect(graphRecords[WORKFLOW].graphVersion).toBe(6);
        expect(hook.result.current.canUndo).toBe(false);
        act(() => hook.result.current.undo());
        expect(shown.nodes.map((n) => n.id)).toEqual(['log']);
    });
});
