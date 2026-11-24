// @vitest-environment happy-dom
// A step added on its own is brought into view a frame later, unless the canvas has gone by then.
import { act, renderHook } from '@testing-library/react';
import { ReactFlowProvider, type Edge, type Node } from '@xyflow/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useClickToAddNode } from './useClickToAddNode';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
});

afterEach(() => {
    vi.useRealTimers();
});

function clickToAdd() {
    let nodes: Node[] = [];
    let edges: Edge[] = [];
    const panToNode = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => <ReactFlowProvider>{children}</ReactFlowProvider>;
    const hook = renderHook(
        () =>
            useClickToAddNode({
                nodesRef: { get current() { return nodes; } },
                setNodes: (update) => void (nodes = update(nodes)),
                setEdges: (update) => void (edges = update(edges)),
                palette: { open: true, show: () => undefined, hide: () => undefined },
                panToNode,
            }),
        { wrapper }
    );
    return { hook, panToNode, added: () => nodes };
}

describe('adding a step on its own', () => {
    it('brings it into view a frame later', () => {
        const { hook, panToNode, added } = clickToAdd();
        act(() => hook.result.current.add({ nodeType: 'log' }));
        expect(added()).toHaveLength(1);
        expect(panToNode).not.toHaveBeenCalled();
        act(() => vi.advanceTimersToNextFrame());
        expect(panToNode).toHaveBeenCalledWith(added()[0].id);
        hook.unmount();
    });

    it('pans nothing once the canvas has gone, and leaves no frame pending', () => {
        const { hook, panToNode } = clickToAdd();
        act(() => hook.result.current.add({ nodeType: 'log' }));
        expect(vi.getTimerCount()).toBe(1);
        hook.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(panToNode).not.toHaveBeenCalled();
    });
});
