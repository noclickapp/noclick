/**
 * Regression tests for the workflow save/load robustness work:
 *  1. "Deleted nodes keep coming back" — the IndexedDB instant-render cache
 *     went stale after deletes and mergeServerNodes union-preserved the
 *     resurrected nodes, which the autosave then re-persisted. Covered by
 *     the fireSave cache mirror + dropStaleCacheEntries.
 *  2. CAS saves — expected_graph_version rides workflow:update, acks adopt
 *     the new version, conflicts rebase (tombstone-aware) and re-save, and
 *     failures keep dirty state + delete tombstones instead of dropping them.
 *  3. No-op content gate — a scheduled save whose payload matches the last
 *     acked/loaded one never hits the wire (no updated_at churn per open).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

const wire = vi.hoisted(() => ({
    sent: [] as Array<Record<string, unknown>>,
    // Per-test responder; return undefined to leave the save unacked.
    respond: undefined as
        | undefined
        | ((event: Record<string, unknown>) => unknown),
}));

vi.mock('~/lib/socket-sender', () => ({
    sendEvent: vi.fn((event: Record<string, unknown>) => {
        wire.sent.push({ ...event, __transport: 'fire-and-forget' });
        return true;
    }),
    sendEventWithCallback: vi.fn(
        (event: Record<string, unknown>, cb: (resp: unknown) => void) => {
            wire.sent.push(event);
            const resp = wire.respond?.(event);
            if (resp !== undefined) queueMicrotask(() => cb(resp));
            return () => {};
        }
    ),
}));
vi.mock('~/lib/socket-receiver', () => ({
    onSocketEvent: vi.fn(() => () => {}),
}));
vi.mock('~/lib/headless-builder', () => ({
    headlessBuilder: { isActive: vi.fn(() => false) },
}));
vi.mock('~/lib/activeGenStore', () => ({
    activeGenStore: { gens: {}, byWorkflow: {} },
}));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: {
        get: vi.fn(async () => null),
        set: vi.fn(async () => true),
    },
}));

import { valtioCache } from '~/lib/indexeddb';
import {
    graphRecords,
    recordGraphSnapshot,
    recordDeletedNodes,
    recordRemoteDeletedNodes,
    setGraphLoaded,
    setGraphVersion,
    setCanvasMounted,
    flushGraphNow,
    hasLiveGraphState,
    seedSaveBaseline,
    markGraphDirty,
    applyAgenticGraphEvent,
} from './liveGraphStore';
import {
    createWorkflowNode,
    mergeServerNodes,
    mergeServerEdges,
    dropStaleCacheEntries,
} from './applyNodeUpdate';
import type { Node, Edge } from '@xyflow/react';

const WF = 'wf-stale-cache-test';
type AgenticEvent = Parameters<typeof applyAgenticGraphEvent>[1];

function makeNode(id: string): Node {
    return createWorkflowNode(id, 'automation-slack', { x: 0, y: 0 }, {});
}

/** Flush the queued ack microtask(s). */
const tick = () => new Promise<void>((r) => queueMicrotask(() => r()));

function primeMountedRecord(nodes: Node[], version: number | null = null) {
    setCanvasMounted(WF, false, true);
    recordGraphSnapshot(WF, false, { nodes, edges: [] });
    setGraphLoaded(WF, true);
    if (version != null) setGraphVersion(WF, version);
}

beforeEach(() => {
    for (const k of Object.keys(graphRecords)) delete graphRecords[k];
    wire.sent = [];
    // A save that lands moves the version one past the one it was made against (the first, unguarded, to 2).
    wire.respond = (event) => ({
        success: true,
        workflow: { graph_version: ((event.expected_graph_version as number | undefined) ?? 1) + 1 },
    });
    vi.mocked(valtioCache.set).mockClear();
});

describe('dropStaleCacheEntries + server merge', () => {
    it('drops a cache-injected node the server no longer has (the resurrection case)', () => {
        const deleted = makeNode('deleted_node');
        const kept = makeNode('kept_node');
        const cacheInjected = new Set(['deleted_node', 'kept_node']);
        const serverNodes = [makeNode('kept_node')];
        const serverIds = new Set(serverNodes.map((n) => n.id));

        const merged = mergeServerNodes(
            serverNodes,
            dropStaleCacheEntries([deleted, kept], cacheInjected, serverIds)
        );
        expect(merged.map((n) => n.id)).toEqual(['kept_node']);
    });

    it('preserves unsaved local adds the cache did not inject', () => {
        const agenticAdd = makeNode('agentic_new');
        const merged = mergeServerNodes(
            [makeNode('server_node')],
            dropStaleCacheEntries(
                [agenticAdd],
                new Set(['something_else']),
                new Set(['server_node'])
            )
        );
        expect(merged.map((n) => n.id).sort()).toEqual([
            'agentic_new',
            'server_node',
        ]);
    });

    it('drops cache-injected edges the server no longer has', () => {
        const staleEdge = { id: 'e-del', source: 'a', target: 'b' } as Edge;
        const merged = mergeServerEdges(
            [],
            dropStaleCacheEntries([staleEdge], new Set(['e-del']), new Set())
        );
        expect(merged).toEqual([]);
    });

    it('is identity when the cache injected nothing', () => {
        const existing = [makeNode('n1')];
        expect(dropStaleCacheEntries(existing, new Set(), new Set())).toBe(
            existing
        );
    });
});

describe('acked saves', () => {
    it('sends expected_graph_version, adopts the acked version, clears tombstones, mirrors the cache', async () => {
        primeMountedRecord([makeNode('survivor')], 5);
        recordDeletedNodes(WF, ['victim']);
        flushGraphNow(WF);
        await tick();

        expect(wire.sent).toHaveLength(1);
        const sent = wire.sent[0];
        expect(sent.event_name).toBe('workflow:update');
        expect(sent.expected_graph_version).toBe(5);
        expect(sent.deleted_node_ids).toEqual(['victim']);

        const rec = graphRecords[WF];
        expect(rec.graphVersion).toBe(6); // adopted from the ack
        expect(rec.deletedNodeIds.size).toBe(0); // retired on ack
        expect(rec.dirty).toBe(false);

        expect(valtioCache.set).toHaveBeenCalledTimes(1);
        const [key, cached] = vi.mocked(valtioCache.set).mock.calls[0] as [
            string,
            { nodes: Array<{ id: string }> },
        ];
        expect(key).toBe(`workflow-canvas:${WF}`);
        expect(cached.nodes.map((n) => n.id)).toEqual(['survivor']);
    });

    it('omits the CAS guard when no version is known', async () => {
        primeMountedRecord([makeNode('n1')]);
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(1);
        expect('expected_graph_version' in wire.sent[0]).toBe(false);
    });

    it('keeps dirty state AND delete tombstones when the save fails', async () => {
        wire.respond = () => ({ error: 'boom' });
        primeMountedRecord([makeNode('n1')], 5);
        recordDeletedNodes(WF, ['victim']);
        flushGraphNow(WF);
        await tick();

        const rec = graphRecords[WF];
        expect(rec.dirty).toBe(true); // re-queued for retry
        expect(rec.deletedNodeIds.has('victim')).toBe(true); // NOT dropped
        expect(rec.graphVersion).toBe(5); // unchanged
        expect(valtioCache.set).not.toHaveBeenCalled(); // cache mirrors acked saves only
    });

    it('does not save at all when nothing is loaded yet', async () => {
        setCanvasMounted(WF, false, true);
        recordGraphSnapshot(WF, false, { nodes: [makeNode('n1')], edges: [] });
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(0);
        expect(valtioCache.set).not.toHaveBeenCalled();
    });
});

describe('CAS conflict rebase', () => {
    it('adopts server-only nodes, honors local + remote tombstones, and re-queues the save', async () => {
        wire.respond = () => ({
            conflict: true,
            graph_version: 7,
            workflow_data: {
                nodes: [
                    { id: 'mine', type: 'automation-slack', position: { x: 0, y: 0 }, config: { label: 'server-copy' } },
                    { id: 'theirs_new', type: 'automation-gmail', position: { x: 10, y: 10 }, config: {} },
                    { id: 'my_pending_delete', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                    { id: 'their_pending_delete', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                ],
                edges: [
                    { id: 'e1', source: 'mine', target: 'theirs_new' },
                    { id: 'e2', source: 'mine', target: 'my_pending_delete' },
                ],
            },
        });

        const mine = makeNode('mine');
        (mine.data as Record<string, unknown>).label = 'local-edit';
        primeMountedRecord([mine], 5);
        recordDeletedNodes(WF, ['my_pending_delete']);
        recordRemoteDeletedNodes(WF, ['their_pending_delete']);
        flushGraphNow(WF);
        await tick();

        const rec = graphRecords[WF];
        expect(rec.graphVersion).toBe(7); // adopted from the conflict payload
        const ids = rec.nodes.map((n) => n.id).sort();
        expect(ids).toEqual(['mine', 'theirs_new']); // tombstoned nodes NOT re-added
        // Local wins for shared ids — the user's unsaved edit survives.
        const mineAfter = rec.nodes.find((n) => n.id === 'mine')!;
        expect((mineAfter.data as Record<string, unknown>).label).toBe('local-edit');
        // Edge to the tombstoned node dropped; edge between survivors adopted.
        expect(rec.edges.map((e) => e.id)).toEqual(['e1']);
        // Rebase re-queues the save under the new version.
        expect(rec.dirty).toBe(true);
        expect(rec.saveTimer).not.toBeNull();
    });
});

describe('a CAS conflict rebase against the canvas base', () => {
    it("takes the server's copy of what it never changed and keeps what it did", async () => {
        // The canvas loaded a, b, c and the a-b, b-c connections, then missed writes it was never sent (the
        // builder's or MCP's, which reach only the owner's pages): b renamed, c removed, d added.
        wire.respond = () => ({
            conflict: true,
            graph_version: 7,
            workflow_data: {
                nodes: [
                    { id: 'a', type: 'automation-slack', position: { x: 0, y: 0 }, config: { label: 'A server' } },
                    { id: 'b', type: 'automation-slack', position: { x: 0, y: 0 }, config: { label: 'B server' } },
                    { id: 'd', type: 'automation-gmail', position: { x: 0, y: 0 }, config: {} },
                ],
                edges: [{ id: 'a-b', source: 'a', target: 'b' }],
            },
        });
        primeMountedRecord([makeNode('a'), makeNode('b'), makeNode('c')], 5);
        recordGraphSnapshot(WF, false, {
            edges: [
                { id: 'a-b', source: 'a', target: 'b' },
                { id: 'b-c', source: 'b', target: 'c' },
            ] as Edge[],
        }, false);
        seedSaveBaseline(WF);
        // Its own edits since: a renamed, e added and connected, a-b removed.
        const rec = graphRecords[WF];
        rec.nodes = rec.nodes.map((n) => (n.id === 'a' ? createWorkflowNode('a', 'automation-slack', { x: 0, y: 0 },
            { label: 'A mine' }) : n));
        rec.nodes = [...rec.nodes, makeNode('e')];
        rec.edges = [{ id: 'b-c', source: 'b', target: 'c' }, { id: 'a-e', source: 'a', target: 'e' }] as Edge[];
        markGraphDirty(WF);
        flushGraphNow(WF);
        await tick();

        const label = (id: string) => (rec.nodes.find((n) => n.id === id)?.data as Record<string, unknown>)?.label;
        expect(rec.graphVersion).toBe(7);
        expect(rec.nodes.map((n) => n.id).sort()).toEqual(['a', 'b', 'd', 'e']);
        expect(label('a')).toBe('A mine');
        expect(label('b')).toBe('B server');
        // b-c went with c; the a-b connection it removed stays removed; its own a-e stays.
        expect(rec.edges.map((e) => e.id).sort()).toEqual(['a-e']);
    });
});

describe('two conflicts in a row', () => {
    function server(version: number, nodes: Array<[string, string]>) {
        return {
            conflict: true, graph_version: version, workflow_data: {
                nodes: nodes.map(([id, label]) => ({
                    id, type: 'automation-slack', position: { x: 0, y: 0 }, config: { label },
                })), edges: [],
            },
        };
    }

    it("takes the server's newest copy of a step it never changed, on the second rebase too", async () => {
        const responses: unknown[] = [server(7, [['a', 'A'], ['b', 'B server 1']]),
                                      server(8, [['a', 'A'], ['b', 'B server 2']]),
                                      { success: true, workflow: { graph_version: 9 } }];
        wire.respond = () => responses.shift();
        primeMountedRecord([createWorkflowNode('a', 'automation-slack', { x: 0, y: 0 }, { label: 'A' }),
                            createWorkflowNode('b', 'automation-slack', { x: 0, y: 0 }, { label: 'B' })], 5);
        seedSaveBaseline(WF);
        const rec = graphRecords[WF];
        // The person moved a.
        rec.nodes = rec.nodes.map((n) => (n.id === 'a'
            ? createWorkflowNode('a', 'automation-slack', { x: 5, y: 5 }, { label: 'A' }) : n));
        markGraphDirty(WF);
        flushGraphNow(WF); await tick();
        flushGraphNow(WF); await tick();
        flushGraphNow(WF); await tick();
        const label = (id: string) => (rec.nodes.find((n) => n.id === id)?.data as Record<string, unknown>)?.label;
        expect(label('b')).toBe('B server 2');
        expect(rec.nodes.find((n) => n.id === 'a')?.position).toEqual({ x: 5, y: 5 });
        const saved = wire.sent[wire.sent.length - 1] as {
            workflow_data: { nodes: Array<{ id: string; config: { label: string } }> };
        };
        expect(saved.workflow_data.nodes.find((n) => n.id === 'b')?.config.label).toBe('B server 2');
    });

    it('drops a step another writer removed after the first rebase took its copy', async () => {
        const responses: unknown[] = [server(7, [['a', 'A'], ['b', 'B server 1']]), server(8, [['a', 'A']]),
                                      { success: true, workflow: { graph_version: 9 } }];
        wire.respond = () => responses.shift();
        primeMountedRecord([createWorkflowNode('a', 'automation-slack', { x: 0, y: 0 }, { label: 'A' }),
                            createWorkflowNode('b', 'automation-slack', { x: 0, y: 0 }, { label: 'B' })], 5);
        seedSaveBaseline(WF);
        const rec = graphRecords[WF];
        rec.nodes = rec.nodes.map((n) => (n.id === 'a'
            ? createWorkflowNode('a', 'automation-slack', { x: 5, y: 5 }, { label: 'A' }) : n));
        markGraphDirty(WF);
        flushGraphNow(WF); await tick();
        flushGraphNow(WF); await tick();
        flushGraphNow(WF); await tick();
        expect(rec.nodes.map((n) => n.id)).toEqual(['a']);
    });
});

describe('builder removals survive a CAS conflict rebase', () => {
    // 2026-09-22: the builder streamed node_removed, the canvas flush-saved on
    // active_gen:terminal with a version token the builder had already bumped
    // on earlier turns, and the conflict payload carried the row as it stood
    // BEFORE the builder's own persist landed. The removed node was adopted
    // as "server-only" and written straight back — three times for one user.
    function serverStillHoldsRemoved() {
        wire.respond = () => ({
            conflict: true,
            graph_version: 9,
            workflow_data: {
                nodes: [
                    { id: 'keep', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                    { id: 'builder_removed', type: 'automation-google-sheets', position: { x: 0, y: 0 }, config: {} },
                ],
                edges: [
                    { id: 'e_keep_removed', source: 'keep', target: 'builder_removed' },
                ],
            },
        });
    }

    it('does not resurrect a node the builder just removed', async () => {
        serverStillHoldsRemoved();
        primeMountedRecord([makeNode('keep'), makeNode('builder_removed')], 5);
        recordGraphSnapshot(WF, false, {
            edges: [{ id: 'e_keep_removed', source: 'keep', target: 'builder_removed' } as Edge],
        }, false);

        applyAgenticGraphEvent(WF, { type: 'node_removed', nodeId: 'builder_removed' } as AgenticEvent);
        markGraphDirty(WF); // the canvas effect marks dirty when it sees the change
        flushGraphNow(WF);
        await tick();

        const rec = graphRecords[WF];
        expect(rec.graphVersion).toBe(9);
        expect(rec.nodes.map((n) => n.id)).toEqual(['keep']);
        expect(rec.edges).toEqual([]);
    });

    it('does not resurrect an edge the builder just removed', async () => {
        wire.respond = () => ({
            conflict: true,
            graph_version: 9,
            workflow_data: {
                nodes: [
                    { id: 'a', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                    { id: 'b', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                ],
                edges: [{ id: 'e_ab', source: 'a', target: 'b' }],
            },
        });
        primeMountedRecord([makeNode('a'), makeNode('b')], 5);
        recordGraphSnapshot(WF, false, {
            edges: [{ id: 'e_ab', source: 'a', target: 'b' } as Edge],
        }, false);

        applyAgenticGraphEvent(WF, { type: 'edge_removed', edgeId: 'e_ab' } as AgenticEvent);
        markGraphDirty(WF);
        flushGraphNow(WF);
        await tick();

        expect(graphRecords[WF].edges).toEqual([]);
    });

    it('lets the builder re-add a node it removed earlier in the run', async () => {
        wire.respond = () => ({
            conflict: true,
            graph_version: 9,
            workflow_data: {
                nodes: [
                    { id: 'keep', type: 'automation-slack', position: { x: 0, y: 0 }, config: {} },
                    { id: 'again', type: 'automation-gmail', position: { x: 0, y: 0 }, config: { label: 'server' } },
                ],
                edges: [],
            },
        });
        primeMountedRecord([makeNode('keep'), makeNode('again')], 5);
        applyAgenticGraphEvent(WF, { type: 'node_removed', nodeId: 'again' } as AgenticEvent);
        applyAgenticGraphEvent(WF, {
            type: 'node_added',
            node: { id: 'again', type: 'automation-gmail', label: 'local' },
        } as AgenticEvent);
        markGraphDirty(WF);
        flushGraphNow(WF);
        await tick();

        const rec = graphRecords[WF];
        expect(rec.nodes.map((n) => n.id).sort()).toEqual(['again', 'keep']);
        expect(rec.remoteDeletedNodeIds.has('again')).toBe(false);
    });
});

describe('no-op content gate', () => {
    it('skips the wire when the payload matches the last acked save', async () => {
        primeMountedRecord([makeNode('n1')], 5);
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(1);

        // Nothing changed — a re-mark (e.g. post-load merge identity churn)
        // must not produce a second write.
        graphRecords[WF].dirty = true;
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(1);
        expect(graphRecords[WF].dirty).toBe(false);
    });

    it('seedSaveBaseline suppresses the post-load no-op save', async () => {
        primeMountedRecord([makeNode('n1')], 5);
        seedSaveBaseline(WF);
        graphRecords[WF].dirty = true;
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(0);

        // A real change still saves.
        recordGraphSnapshot(WF, false, {
            nodes: [makeNode('n1'), makeNode('n2')],
            edges: [],
        });
        flushGraphNow(WF);
        await tick();
        expect(wire.sent).toHaveLength(1);
    });
});

describe('hasLiveGraphState', () => {
    it('is false for an unknown or freshly-created empty record', () => {
        expect(hasLiveGraphState('never-seen')).toBe(false);
        setCanvasMounted(WF, false, true); // creates an empty record
        expect(hasLiveGraphState(WF)).toBe(false);
    });

    it('is true once loaded, or once any graph content exists', () => {
        setCanvasMounted(WF, false, true);
        setGraphLoaded(WF, true);
        expect(hasLiveGraphState(WF)).toBe(true);

        const wf2 = `${WF}-2`;
        setCanvasMounted(wf2, false, true);
        recordGraphSnapshot(
            wf2,
            false,
            { nodes: [makeNode('n1')], edges: [] },
            /* markDirty */ false
        );
        expect(hasLiveGraphState(wf2)).toBe(true);
    });
});
