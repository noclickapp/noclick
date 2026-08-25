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
} from './liveGraphStore';
import {
    createWorkflowNode,
    mergeServerNodes,
    mergeServerEdges,
    dropStaleCacheEntries,
} from './applyNodeUpdate';
import type { Node, Edge } from '@xyflow/react';

const WF = 'wf-stale-cache-test';

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
    wire.respond = () => ({ success: true, workflow: { graph_version: 2 } });
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
        expect(rec.graphVersion).toBe(2); // adopted from the ack
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
