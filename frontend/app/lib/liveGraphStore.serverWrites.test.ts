/**
 * A write through the graph service reaches an open canvas through the workflow's room: its builder events,
 * then `workflow:graph_changed` with the version it left. What the canvas applied from the room is the
 * server's, not an edit of its own: its CAS base moves to that version (so its next save doesn't conflict and
 * rebase over the write), a step it must fetch whole (a secret, an outsize setting) holds its saves until it
 * has, and a canvas its viewer can't edit never saves.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { handlers, sent } = vi.hoisted(() => ({
    handlers: {} as Record<string, (data: unknown) => void>,
    sent: [] as Array<Record<string, unknown>>,
}));

vi.mock('~/lib/socket-sender', () => ({
    sendEvent: vi.fn(),
    sendEventWithCallback: vi.fn((event: Record<string, unknown>) => {
        sent.push(event);
        return () => {};
    }),
}));
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn((event: string, handler: (data: unknown) => void) => {
        handlers[event] = handler;
        return () => {};
    }),
}));
vi.mock('~/lib/headless-builder', () => ({ headlessBuilder: { isActive: vi.fn(() => false) } }));
vi.mock('~/lib/activeGenStore', () => ({ activeGenStore: { gens: {}, byWorkflow: {} } }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { set: vi.fn() } }));

import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import {
    graphRecords,
    holdSaves,
    markGraphDirty,
    recordGraphSnapshot,
    releaseSaves,
    seedSaveBaseline,
    setCanvasMounted,
    setGraphLoaded,
    setGraphReadOnly,
    setGraphVersion,
} from './liveGraphStore';

const WF = 'wf-server-writes';

function openCanvas(version: number) {
    recordGraphSnapshot(WF, false, {
        nodes: [createWorkflowNode('note', 'log', { x: 0, y: 0 }, { label: 'Note' })],
        edges: [],
    }, false);
    setCanvasMounted(WF, false, true);
    setGraphLoaded(WF, true);
    setGraphVersion(WF, version);
    seedSaveBaseline(WF);
}

function editLocally(label: string) {
    const rec = graphRecords[WF];
    rec.nodes = [createWorkflowNode('note', 'log', { x: 0, y: 0 }, { label })];
    markGraphDirty(WF);
}

describe('server writes on an open canvas', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.clearAllTimers();
        sent.length = 0;
        for (const k of Object.keys(graphRecords)) delete graphRecords[k];
    });

    it('moves its base to the version the room names, so its next save does not conflict', () => {
        openCanvas(1);
        handlers['workflow:graph_changed']({ type: 'workflow:graph_changed', workflow_id: WF, version: 3 });
        editLocally('Mine');
        vi.advanceTimersByTime(5000);
        expect(sent).toHaveLength(1);
        expect(sent[0].expected_graph_version).toBe(3);
        // An older version never moves it back.
        handlers['workflow:graph_changed']({ type: 'workflow:graph_changed', workflow_id: WF, version: 2 });
        expect(graphRecords[WF].graphVersion).toBe(3);
    });

    it('holds its saves while a step it must fetch whole is on its way', () => {
        openCanvas(1);
        holdSaves(WF);
        editLocally('Mine');
        vi.advanceTimersByTime(5000);
        expect(sent).toHaveLength(0);
        releaseSaves(WF);
        vi.advanceTimersByTime(5000);
        expect(sent).toHaveLength(1);
    });

    it('never saves for a viewer who can only read it', () => {
        openCanvas(1);
        setGraphReadOnly(WF, true);
        editLocally('Not mine to save');
        vi.advanceTimersByTime(60000);
        expect(sent).toHaveLength(0);
    });
});
