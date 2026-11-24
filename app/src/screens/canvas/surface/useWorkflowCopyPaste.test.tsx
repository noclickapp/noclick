// @vitest-environment happy-dom
// A paste is one step back in the undo history, recorded a task after it lands; once the canvas has gone, nothing is.
import { act, renderHook } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';
import type { ReactNode } from 'react';
import { ClientProvider } from '@/sdk/client';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { formFetch } from '../form/fixtures/world';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkflowCopyPaste } from './useWorkflowCopyPaste';

const COPIED = JSON.stringify({
    workflow_data: {
        nodes: [{ id: 'log', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Log' } }],
        edges: [],
    },
});

beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { readText: async () => COPIED, writeText: async () => undefined } });
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    vi.useRealTimers();
});

function copyPaste() {
    let nodes: Node[] = [];
    let edges: Edge[] = [];
    const captureState = vi.fn();
    const client = workFixtureClient(formFetch(), { maxRetries: 0 });
    const wrapper = ({ children }: { children: ReactNode }) => <ClientProvider client={client}>{children}</ClientProvider>;
    const hook = renderHook(() =>
        useWorkflowCopyPaste({
            nodes,
            edges,
            active: true,
            setNodes: (update) => void (nodes = update(nodes)),
            setEdges: (update) => void (edges = update(edges)),
            captureState,
        }),
        { wrapper }
    );
    return { hook, captureState, pasted: () => nodes };
}

describe('pasting steps', () => {
    it('records the paste in the undo history a task later', async () => {
        const { hook, captureState, pasted } = copyPaste();
        await act(() => hook.result.current.pasteFromClipboard({ x: 10, y: 10 }));
        expect(pasted()).toHaveLength(1);
        expect(captureState).not.toHaveBeenCalled();
        act(() => vi.advanceTimersByTime(0));
        expect(captureState).toHaveBeenCalledOnce();
        hook.unmount();
    });

    it('records nothing, and leaves nothing pending, once the canvas has gone', async () => {
        const { hook, captureState, pasted } = copyPaste();
        await act(() => hook.result.current.pasteFromClipboard({ x: 10, y: 10 }));
        expect(pasted()).toHaveLength(1);
        expect(vi.getTimerCount()).toBe(1);
        hook.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(captureState).not.toHaveBeenCalled();
    });
});
