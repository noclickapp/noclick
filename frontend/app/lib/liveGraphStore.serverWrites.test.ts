/**
 * A write through the graph service reaches an open canvas through the workflow's room: its builder events,
 * then `workflow:graph_changed` with the versions it was made on and left. What the canvas applied from the
 * room is the server's, not an edit of its own: a canvas on the write's base moves to the version it left (so
 * its next save doesn't conflict and rebase over the write), one on any other base keeps it (it missed a write,
 * so its next save conflicts and rebases). A step it must fetch whole (a secret, an outsize setting) is named in
 * its saves until it has, so the server keeps it as stored; a closing tab's save names what it changed; and a
 * canvas its viewer can't edit never saves.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { handlers, sent, acks } = vi.hoisted(() => ({
    handlers: {} as Record<string, (data: unknown) => void>,
    sent: [] as Array<Record<string, unknown>>,
    acks: [] as Array<(response: unknown) => void>,
}));

vi.mock('~/lib/socket-sender', () => ({
    sendEvent: vi.fn((event: Record<string, unknown>) => {
        sent.push(event);
    }),
    sendEventWithCallback: vi.fn((event: Record<string, unknown>, ack: (response: unknown) => void) => {
        sent.push(event);
        acks.push(ack);
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
    flushAllGraphsNow,
    graphRecords,
    markGraphDirty,
    markStepPartial,
    markStepWhole,
    recordGraphSnapshot,
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
        acks.length = 0;
        for (const k of Object.keys(graphRecords)) delete graphRecords[k];
    });

    it('moves its base to the version a write left when it was on the write\'s base', () => {
        openCanvas(1);
        handlers['workflow:graph_changed']({
            type: 'workflow:graph_changed', workflow_id: WF, base_version: 1, version: 3,
        });
        editLocally('Mine');
        vi.advanceTimersByTime(5000);
        expect(sent).toHaveLength(1);
        expect(sent[0].expected_graph_version).toBe(3);
    });

    it('keeps its base after a write made on a version it never saw, so its next save conflicts', () => {
        openCanvas(1);
        // Versions 2 and 3 were written where the room never carried them (a collaborator's canvas misses the
        // builder's and the platform's writes); the graph service's write on 3 doesn't vouch for them.
        handlers['workflow:graph_changed']({
            type: 'workflow:graph_changed', workflow_id: WF, base_version: 3, version: 4,
        });
        expect(graphRecords[WF].graphVersion).toBe(1);
        editLocally('Mine');
        vi.advanceTimersByTime(5000);
        expect(sent[0].expected_graph_version).toBe(1);
    });

    it('names a step it holds in part in every save until it has it whole, and a load takes it whole', () => {
        openCanvas(1);
        markStepPartial(WF, 'note');
        editLocally('Mine');
        vi.advanceTimersByTime(5000);
        expect(sent[0].partial_node_ids).toEqual(['note']);
        acks[0]({ workflow: { graph_version: 2 } });
        markStepWhole(WF, 'note');
        editLocally('Mine again');
        vi.advanceTimersByTime(5000);
        expect(sent[1].partial_node_ids).toBeUndefined();
        markStepPartial(WF, 'note');
        setGraphVersion(WF, 2);
        expect(graphRecords[WF].partialNodeIds.size).toBe(0);
    });

    it('closing, saves on the version it saw and names what it changed since', () => {
        openCanvas(4);
        const rec = graphRecords[WF];
        rec.nodes = [
            createWorkflowNode('note', 'log', { x: 0, y: 0 }, { label: 'Changed' }),
            createWorkflowNode('added', 'log', { x: 0, y: 200 }, { label: 'Added' }),
        ];
        rec.edges = [{ id: 'note-added', source: 'note', target: 'added' }];
        markStepPartial(WF, 'added');
        markGraphDirty(WF);
        flushAllGraphsNow();
        expect(sent).toHaveLength(1);
        expect(sent[0].expected_graph_version).toBe(4);
        expect(sent[0].changes).toEqual({ steps: ['note', 'added'], edges_added: ['note-added'], edges_removed: [] });
        expect(sent[0].partial_node_ids).toEqual(['added']);
    });

    it('never saves for a viewer who can only read it', () => {
        openCanvas(1);
        setGraphReadOnly(WF, true);
        editLocally('Not mine to save');
        vi.advanceTimersByTime(60000);
        expect(sent).toHaveLength(0);
    });
});
