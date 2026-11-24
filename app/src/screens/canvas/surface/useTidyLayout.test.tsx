// @vitest-environment happy-dom
// Tidying brings the workflow into view a frame after the layout, unless the canvas has gone by then.
import { act, renderHook } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useTidyLayout } from './useTidyLayout';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
});

afterEach(() => {
    vi.useRealTimers();
});

function tidy() {
    let nodes: Node[] = [
        { id: 'a', type: 'log', position: { x: 0, y: 0 }, data: {} },
        { id: 'b', type: 'log', position: { x: 0, y: 0 }, data: {} },
    ];
    const edges: Edge[] = [{ id: 'a-b', source: 'a', target: 'b' }];
    const fit = vi.fn();
    const hook = renderHook(() =>
        useTidyLayout({
            nodesRef: { get current() { return nodes; } },
            edgesRef: { current: edges },
            setNodes: (update) => void (nodes = update(nodes)),
            history: { startBatch: () => undefined, endBatch: () => undefined },
            fit,
        })
    );
    return { hook, fit };
}

describe('tidying the canvas', () => {
    it('fits the view a frame after the layout', () => {
        const { hook, fit } = tidy();
        act(() => hook.result.current());
        expect(fit).not.toHaveBeenCalled();
        act(() => vi.advanceTimersToNextFrame());
        expect(fit).toHaveBeenCalledOnce();
        hook.unmount();
    });

    it('fits nothing once the canvas has gone, and leaves no frame pending', () => {
        const { hook, fit } = tidy();
        act(() => hook.result.current());
        expect(vi.getTimerCount()).toBe(1);
        hook.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(fit).not.toHaveBeenCalled();
    });
});
