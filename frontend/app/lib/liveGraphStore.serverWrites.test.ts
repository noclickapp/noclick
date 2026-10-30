/**
 * A write through the graph service reaches an open canvas through the workflow's room: its builder events,
 * then `workflow:graph_changed` with the versions it was made on and left. What the canvas applied from the
 * room is the server's, not an edit of its own: a canvas on the write's base moves to the version it left (so
 * its next save doesn't conflict and rebase over the write), one on any other base keeps it (it missed a write,
 * so its next save conflicts and rebases). A written change's events also move the canvas's per-step base, so a
 * conflict's three-way merge and a closing tab's save tell the canvas's own changes from the server's. A step it
 * must fetch whole (a secret, an outsize setting) is named in its saves until it has, so the server keeps it as
 * stored, and one it can't read sends it to read the whole workflow again; a canvas its viewer can't edit never
 * saves.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { handlers, sent, acks, reads } = vi.hoisted(() => ({
    handlers: {} as Record<string, (data: unknown) => void>,
    sent: [] as Array<Record<string, unknown>>,
    acks: [] as Array<(response: unknown) => void>,
    reads: [] as unknown[],
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
    sendEventAsync: vi.fn(async () => reads.shift()),
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
    recordGraphSnapshot,
    reloadFromServer,
    seedSaveBaseline,
    setCanvasMounted,
    setGraphLoaded,
    setGraphReadOnly,
    setGraphVersion,
    takeServerStep,
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
        reads.length = 0;
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
        takeServerStep(WF, 'note', { label: 'Mine', message: 'all of it' });
        editLocally('Mine again');
        vi.advanceTimersByTime(5000);
        expect(sent[1].partial_node_ids).toBeUndefined();
        markStepPartial(WF, 'note');
        setGraphVersion(WF, 2);
        expect(graphRecords[WF].partialNodeIds).toEqual({});
    });

    it("moves its base with a written change's events, so a later conflict takes the server's newer copy", () => {
        openCanvas(1);
        // Another writer renames the step; the canvas applies it (as useMCPBuilderEvents does) and its base too.
        handlers['mcp:builder_event']({
            workflow_id: WF, event_type: 'node_updated', data: { nodeId: 'note', config: { label: 'Theirs' } },
            committed: true,
        });
        editLocally('Theirs');
        vi.advanceTimersByTime(5000);
        // Its save meets a still newer write it never heard: the step it never changed itself takes that one.
        acks[0]({ conflict: true, graph_version: 6, workflow_data: { nodes: [
            { id: 'note', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Newer' } },
        ], edges: [] } });
        const label = (graphRecords[WF].nodes[0].data as Record<string, unknown>).label;
        expect(label).toBe('Newer');
    });

    it("keeps a written change heard before its own save's ack, and takes the version it was made on", () => {
        const step = (id: string, label: string) => createWorkflowNode(id, 'log', { x: 0, y: 0 }, { label });
        recordGraphSnapshot(WF, false, { nodes: [step('a', 'A'), step('b', 'B')], edges: [] }, false);
        setCanvasMounted(WF, false, true);
        setGraphLoaded(WF, true);
        setGraphVersion(WF, 5);
        seedSaveBaseline(WF);
        const rec = graphRecords[WF];
        rec.nodes = [step('a', 'A mine'), step('b', 'B')];
        markGraphDirty(WF);
        vi.advanceTimersByTime(5000);
        expect(sent[0].expected_graph_version).toBe(5);
        // The save lands at 6; an API write on 6 renames b, and its room events come before the save's ack.
        handlers['mcp:builder_event']({
            workflow_id: WF, event_type: 'node_updated', data: { nodeId: 'b', config: { label: 'B api' } },
            committed: true,
        });
        rec.nodes = [step('a', 'A mine'), step('b', 'B api')];
        handlers['workflow:graph_changed']({ workflow_id: WF, base_version: 6, version: 7 });
        acks[0]({ workflow: { graph_version: 6 } });
        expect(rec.graphVersion).toBe(7);
        // A writer it never hears renames b at 8; the person renames a again, and the save conflicts: b, never
        // the person's, takes the server's copy.
        rec.nodes = [step('a', 'A mine again'), rec.nodes[1]];
        markGraphDirty(WF);
        vi.advanceTimersByTime(5000);
        expect(sent[1].expected_graph_version).toBe(7);
        acks[1]({ conflict: true, graph_version: 8, workflow_data: { nodes: [
            { id: 'a', type: 'log', position: { x: 0, y: 0 }, config: { label: 'A mine' } },
            { id: 'b', type: 'log', position: { x: 0, y: 0 }, config: { label: 'B mcp' } },
        ], edges: [] } });
        const label = (id: string) => (rec.nodes.find((n) => n.id === id)?.data as Record<string, unknown>).label;
        expect([label('a'), label('b')]).toEqual(['A mine again', 'B mcp']);
    });

    it('a builder stream not yet written moves no base', () => {
        openCanvas(1);
        handlers['mcp:builder_event']({
            workflow_id: WF, event_type: 'node_updated', data: { nodeId: 'note', config: { label: 'Drafted' } },
        });
        editLocally('Drafted');
        flushAllGraphsNow();
        expect(sent[0].changes).toEqual({ steps: ['note'], edges_added: [], edges_removed: [] });
    });

    it("closing, never names the server's own changes as its own", () => {
        openCanvas(4);
        handlers['mcp:builder_event']({
            workflow_id: WF, event_type: 'node_start',
            data: { node: { id: 'theirs', type: 'log', position: { x: 0, y: 200 }, label: 'Theirs' } }, committed: true,
        });
        const rec = graphRecords[WF];
        rec.nodes = [...rec.nodes, createWorkflowNode('theirs', 'log', { x: 0, y: 200 }, { label: 'Theirs' })];
        rec.nodes = rec.nodes.map((n) => (n.id === 'note'
            ? createWorkflowNode('note', 'log', { x: 0, y: 0 }, { label: 'Mine' }) : n));
        markGraphDirty(WF);
        flushAllGraphsNow();
        expect(sent[0].changes).toEqual({ steps: ['note'], edges_added: [], edges_removed: [] });
    });

    it('a step a conflict takes from the server is whole again', () => {
        openCanvas(1);
        markStepPartial(WF, 'note');
        const rec = graphRecords[WF];
        rec.nodes = [...rec.nodes, createWorkflowNode('mine', 'log', { x: 0, y: 200 }, { label: 'Mine' })];
        markGraphDirty(WF);
        vi.advanceTimersByTime(5000);
        acks[0]({ conflict: true, graph_version: 3, workflow_data: { nodes: [
            { id: 'note', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Note', message: 'x'.repeat(50) } },
        ], edges: [] } });
        expect(graphRecords[WF].partialNodeIds).toEqual({});
        expect(((graphRecords[WF].nodes[0].data as Record<string, unknown>).config as Record<string, unknown>).message)
            .toBe('x'.repeat(50));
    });

    it('reads the whole workflow again when a step can\'t be read whole, keeping its own changes', async () => {
        openCanvas(1);
        const rec = graphRecords[WF];
        rec.nodes = [...rec.nodes, createWorkflowNode('mine', 'log', { x: 0, y: 200 }, { label: 'Mine' })];
        markStepPartial(WF, 'note');
        reads.push({ workflow: { graph_version: 4, workflow_data: { nodes: [
            { id: 'note', type: 'log', position: { x: 0, y: 0 }, config: { label: 'Note', message: 'whole' } },
        ], edges: [] } } });
        expect(await reloadFromServer(WF)).toBe(true);
        expect(rec.graphVersion).toBe(4);
        expect(rec.partialNodeIds).toEqual({});
        expect(rec.nodes.map((n) => n.id)).toEqual(['note', 'mine']);
        vi.advanceTimersByTime(5000);
        expect(sent[0].expected_graph_version).toBe(4);
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
