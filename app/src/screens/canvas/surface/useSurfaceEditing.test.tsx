// @vitest-environment happy-dom
// An edit is recorded in the undo history a task after the canvas takes it; a canvas that has gone records nothing.
import { act, renderHook } from '@testing-library/react';
import { ReactFlowProvider, type Edge, type Node } from '@xyflow/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSurfaceEditing, type SurfaceEditingOptions } from './useSurfaceEditing';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    vi.useRealTimers();
});

const step = (id: string, x: number): Node => ({ id, type: 'log', position: { x, y: 0 }, data: {} });

function editing() {
    let nodes: Node[] = [step('a', 0), step('b', 300)];
    let edges: Edge[] = [{ id: 'a-b', source: 'a', target: 'b' }];
    const history = { captureState: vi.fn(), startBatch: vi.fn(), endBatch: vi.fn() };
    const panToNode = vi.fn();
    const options: SurfaceEditingOptions = {
        workflowId: undefined,
        setNodes: (update) => void (nodes = update(nodes)),
        setEdges: (update) => void (edges = update(edges)),
        nodesRef: { get current() { return nodes; } },
        edgesRef: { get current() { return edges; } },
        history,
        roles: { isTrigger: () => false } as unknown as SurfaceEditingOptions['roles'],
        syncingRef: { current: false },
        draggingRef: { current: false },
        canvasRef: { current: null },
        panToNode,
        layer: (ns) => ns,
    };
    const wrapper = ({ children }: { children: ReactNode }) => <ReactFlowProvider>{children}</ReactFlowProvider>;
    const hook = renderHook(() => useSurfaceEditing(options), { wrapper });
    return { hook, history, panToNode };
}

describe('the surface’s edits', () => {
    it('are recorded in the undo history a task later', () => {
        const { hook, history } = editing();
        act(() => hook.result.current.onEdgesChange([{ type: 'remove', id: 'a-b' }]));
        expect(history.captureState).not.toHaveBeenCalled();
        act(() => vi.advanceTimersByTime(0));
        expect(history.captureState).toHaveBeenCalledWith(expect.any(Array), []);
        hook.unmount();
    });

    it('record nothing, and leave nothing pending, once the canvas has gone', () => {
        const { hook, history, panToNode } = editing();
        act(() => {
            hook.result.current.onEdgesChange([{ type: 'remove', id: 'a-b' }]);
            // One step removed: the selection moves to the step beside it, brought into view a task later.
            hook.result.current.onNodesChange([{ type: 'remove', id: 'b' }]);
        });
        expect(vi.getTimerCount()).toBeGreaterThan(0);
        hook.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(history.captureState).not.toHaveBeenCalled();
        expect(panToNode).not.toHaveBeenCalled();
    });
});
