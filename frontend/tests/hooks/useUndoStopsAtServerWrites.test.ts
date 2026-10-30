// @vitest-environment jsdom
// Undo walks back the person's own edits, never a written server change: when the workflow's room says a write
// landed, the canvas's undo history starts again from the graph as it now stands, so an undo can't put the steps
// back as they were before it (which the canvas's three-way merge would then save as the person's change).
import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { handlers } = vi.hoisted(() => ({ handlers: {} as Record<string, Array<(data: unknown) => void>> }));
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn((event: string, handler: (data: unknown) => void) => {
        (handlers[event] ??= []).push(handler);
        return () => {
            handlers[event] = handlers[event].filter((h) => h !== handler);
        };
    }),
}));
vi.mock('~/lib/socket-sender', () => ({ sendEvent: vi.fn(), sendEventWithCallback: vi.fn() }));
vi.mock('~/lib/headless-builder', () => ({ headlessBuilder: { isActive: vi.fn(() => false) } }));
vi.mock('~/lib/activeGenStore', () => ({ activeGenStore: { gens: {}, byWorkflow: {} } }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { set: vi.fn() } }));

import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { recordGraphSnapshot } from '~/lib/liveGraphStore';
import { useUndoStopsAtServerWrites } from '~/hooks/useUndoStopsAtServerWrites';

const WF = 'wf-undo-server-writes';
const heard = (data: unknown) => (handlers['workflow:graph_changed'] ?? []).forEach((h) => h(data));

describe('undo after a written server change', () => {
    it("starts the canvas's undo history again from the graph as the write left it", () => {
        recordGraphSnapshot(WF, false, {
            nodes: [createWorkflowNode('log', 'log', { x: 0, y: 0 }, { label: 'Renamed by the API' })],
            edges: [],
        }, false);
        const resetBaseline = vi.fn();
        const { unmount } = renderHook(() => useUndoStopsAtServerWrites(WF, resetBaseline));
        heard({ workflow_id: 'another', base_version: 1, version: 2 });
        expect(resetBaseline).not.toHaveBeenCalled();
        heard({ workflow_id: WF, base_version: 1, version: 2 });
        expect(resetBaseline).toHaveBeenCalledTimes(1);
        const [nodes, edges] = resetBaseline.mock.calls[0];
        expect(nodes.map((n: { id: string; data: { label: string } }) => [n.id, n.data.label])).toEqual([
            ['log', 'Renamed by the API']]);
        expect(edges).toEqual([]);
        unmount();
        heard({ workflow_id: WF, base_version: 2, version: 3 });
        expect(resetBaseline).toHaveBeenCalledTimes(1);
    });
});
