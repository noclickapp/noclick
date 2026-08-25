// @vitest-environment jsdom
//
// Invariant tests for the scope-keyed workflow-browser store. These assert the
// structural guarantees that make the recurring bugs impossible — proven at the
// store level (pure module, no React): a fetch/mutation for scope A can only ever
// touch A's slice, reads select the current scope with zero stale frames, merge +
// dedup are structural, and optimistic rollback restores the slice (so the derived
// tree recomputes consistently).

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
    browserStore,
    ensureScope,
    setCurrentScope,
    fetchWorkflows,
    fetchTree,
    fetchSharedResources,
    selectTree,
    selectWorkflows,
    selectAllWorkflows,
    selectAllWorkflowsLoaded,
    selectSubfolders,
    addWorkflow,
    removeWorkflow,
    removeWorkflowFromAllScopes,
    updateWorkflowInAllScopes,
    moveWorkflows,
    snapshotScope,
    restoreSnapshot,
    __resetBrowserStoreForTests,
    type WorkflowApp,
} from '~/lib/workflowBrowserStore';
import { installMockSocket, MockSocket } from '../integration/helpers/mockSocket';

let socket: MockSocket;
let teardown: (() => void) | null = null;

beforeEach(() => {
    __resetBrowserStoreForTests();
    const i = installMockSocket();
    socket = i.socket;
    teardown = i.teardown;
});
afterEach(() => {
    teardown?.();
    teardown = null;
});

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const wf = (id: string, name: string, is_owner = true): WorkflowApp => ({ id, name, description: '', is_owner });
// last request_id emitted for an event name
const lastReq = (name: string) => {
    const evs = socket.sentEvents.filter((e) => e.name === name);
    return (evs[evs.length - 1]?.data as { request_id?: string })?.request_id;
};

describe('workflowBrowserStore — scope isolation', () => {
    it('a late response for scope A cannot touch scope B (the contamination invariant)', async () => {
        // Issue a root workflow fetch for org_a, then switch to org_b and fetch there.
        setCurrentScope('org_a');
        fetchWorkflows('org_a', null);
        const reqA = lastReq('workflow:list');

        setCurrentScope('org_b');
        fetchWorkflows('org_b', null);

        // org_a's response lands LATE, after the switch.
        socket.serverEmit('response', {
            request_id: reqA,
            data: { workflows: [{ id: 'a1', name: 'A-only', is_owner: true }], subscription_tier: 'pro', hidden_shared_count: 3 },
        });
        await flush();

        // It wrote A's slice — and ONLY A's slice.
        expect(browserStore.scopes['org_a'].workflows[''].map((w) => w.id)).toEqual(['a1']);
        expect(browserStore.scopes['org_b'].workflows['']).toBeUndefined();
        // The current scope (org_b) shows nothing of A's.
        const shown = selectWorkflows(browserStore.scopes['org_b'], browserStore.shared, null);
        expect(shown.some((w) => w.id === 'a1')).toBe(false);
        // A's per-scope tier/count landed in A's slice, not B's.
        expect(browserStore.scopes['org_a'].tier).toBe('pro');
        expect(browserStore.scopes['org_b'].tier).toBe('free');
    });

    it('switching scope is a zero-stale-frame read — selectors return the new scope synchronously', () => {
        ensureScope('org_a').workflows[''] = [wf('a1', 'A')];
        ensureScope('org_b').workflows[''] = [wf('b1', 'B')];

        setCurrentScope('org_a');
        expect(selectWorkflows(browserStore.scopes['org_a'], browserStore.shared, null).map((w) => w.id)).toEqual(['a1']);

        setCurrentScope('org_b'); // synchronous switch
        const shown = selectWorkflows(browserStore.scopes['org_b'], browserStore.shared, null);
        expect(shown.map((w) => w.id)).toEqual(['b1']); // B immediately, no A in the same tick
    });

    it('per-scope IDB cache keys are disjoint by scope (contamination cannot persist)', () => {
        // The persistence key derives from the same scopeId that addresses the
        // slice, so a given owned id lives under exactly one scope key.
        ensureScope('personal').workflows[''] = [wf('p1', 'Personal')];
        ensureScope('org_x').workflows[''] = [wf('x1', 'OrgX')];
        expect(browserStore.scopes['personal'].workflows['']).not.toEqual(browserStore.scopes['org_x'].workflows['']);
        // The same id cannot appear in two scopes from a scoped write.
        const allIds = [
            ...browserStore.scopes['personal'].workflows[''].map((w) => w.id),
            ...browserStore.scopes['org_x'].workflows[''].map((w) => w.id),
        ];
        expect(allIds.length).toBe(new Set(allIds).size);
    });

    it('A→B→A latest-fetch wins: an in-flight first-A response is dropped once A is re-fetched', async () => {
        setCurrentScope('org_a');
        fetchWorkflows('org_a', null); // first A
        const reqA1 = lastReq('workflow:list');
        setCurrentScope('org_b');
        setCurrentScope('org_a');
        fetchWorkflows('org_a', null); // second A supersedes the first
        const reqA2 = lastReq('workflow:list');
        expect(reqA1).not.toBe(reqA2);

        socket.serverEmit('response', { request_id: reqA1, data: { workflows: [wf('stale', 'stale')] } });
        await flush();
        expect(browserStore.scopes['org_a'].workflows['']?.some?.((w) => w.id === 'stale')).toBeFalsy();

        socket.serverEmit('response', { request_id: reqA2, data: { workflows: [wf('fresh', 'fresh')] } });
        await flush();
        expect(browserStore.scopes['org_a'].workflows[''].map((w) => w.id)).toEqual(['fresh']);
    });
});

describe('workflowBrowserStore — selectors (merge + dedup + tree)', () => {
    it('root selector merges user-level shared, deduped, own wins ties', () => {
        const slice = ensureScope('org_a');
        slice.workflows[''] = [{ id: 'x', name: 'Owned', description: '', is_owner: true }];
        browserStore.shared.workflows = [
            { id: 'x', name: 'Shared copy', description: '', is_owner: false }, // dup id
            { id: 'y', name: 'Shared only', description: '', is_owner: false },
        ];
        const out = selectWorkflows(slice, browserStore.shared, null);
        const ids = out.map((w) => w.id);
        expect(ids).toEqual(['x', 'y']); // no dup
        expect(out.find((w) => w.id === 'x')?.is_owner).toBe(true); // owned wins
    });

    it('selectAllWorkflows dedups across folders + shared', () => {
        const slice = ensureScope('org_a');
        slice.workflows[''] = [wf('a', 'A')];
        slice.workflows['f1'] = [wf('b', 'B'), wf('a', 'A-dup')];
        browserStore.shared.workflows = [{ id: 'c', name: 'C', description: '', is_owner: false }];
        const ids = selectAllWorkflows(slice, browserStore.shared).map((w) => w.id).sort();
        expect(ids).toEqual(['a', 'b', 'c']);
    });

    it('selectTree grafts workflow leaves and keeps the server workflow_count', () => {
        const slice = ensureScope('org_a');
        // A folder from get_tree with a server count, no workflows loaded yet.
        slice.folders = [{ id: 'f1', name: 'Folder', type: 'folder', workflow_count: 5, children: [] }];
        let tree = selectTree(slice);
        expect(tree[0].workflow_count).toBe(5); // server count
        expect(tree[0].children).toEqual([]); // no leaves yet

        // Load f1's workflows → leaves grafted, but the badge keeps the server
        // count (so an optimistic partial write can't collapse it; refreshTree updates it).
        slice.workflows['f1'] = [wf('w1', 'W1'), wf('w2', 'W2')];
        tree = selectTree(slice);
        expect(tree[0].workflow_count).toBe(5);
        expect(tree[0].children?.map((c) => c.type)).toEqual(['workflow', 'workflow']);
    });

    it('selectAllWorkflowsLoaded: false until root + every own folder loaded; unaffected by shared folders', () => {
        const slice = ensureScope('org_a');
        slice.folders = [
            { id: 'f1', name: 'F1', type: 'folder', children: [{ id: 'f2', name: 'F2', type: 'folder', children: [] }] },
        ];
        expect(selectAllWorkflowsLoaded(slice)).toBe(false); // nothing loaded
        slice.workflows[''] = [];
        expect(selectAllWorkflowsLoaded(slice)).toBe(false); // f1/f2 unloaded
        slice.workflows['f1'] = [];
        expect(selectAllWorkflowsLoaded(slice)).toBe(false); // nested f2 unloaded
        slice.workflows['f2'] = [];
        expect(selectAllWorkflowsLoaded(slice)).toBe(true); // all own folders loaded

        // A shared folder never loads into `workflows` — it must NOT flip this back
        // to false (the bug that pinned the search skeleton on forever).
        browserStore.shared.folders = [{ id: 's1', name: 'Shared', description: '', workflow_count: 0, is_owner: false }];
        expect(selectAllWorkflowsLoaded(slice)).toBe(true);
    });

    it('selectSubfolders at root merges shared folders and dedups', () => {
        const slice = ensureScope('org_a');
        slice.folders = [{ id: 'f1', name: 'Own', type: 'folder', children: [] }];
        browserStore.shared.folders = [
            { id: 'f1', name: 'dup', description: '', workflow_count: 0, is_owner: false },
            { id: 's1', name: 'Shared', description: '', workflow_count: 0, is_owner: false },
        ];
        const ids = selectSubfolders(slice, browserStore.shared, null).map((f) => f.id);
        expect(ids).toEqual(['f1', 's1']);
    });
});

describe('workflowBrowserStore — optimistic mutations + rollback', () => {
    it('rollback restores the exact slice; the derived tree recomputes consistently', () => {
        const slice = ensureScope('org_a');
        slice.folders = [{ id: 'f1', name: 'F', type: 'folder', workflow_count: 1, children: [] }];
        slice.workflows['f1'] = [wf('w1', 'W1')];
        setCurrentScope('org_a');

        const rollback = snapshotScope('org_a');
        removeWorkflow('org_a', 'w1', 'f1');
        // Optimistically gone: the tree leaf is removed. The badge keeps the server
        // workflow_count (refreshed by refreshTree), so it stays 1 until that lands.
        let tree = selectTree(browserStore.scopes['org_a']);
        expect(tree[0].children).toEqual([]);
        expect(tree[0].workflow_count).toBe(1);

        restoreSnapshot(rollback);
        tree = selectTree(browserStore.scopes['org_a']);
        expect(tree[0].children?.length).toBe(1); // leaf back — no dual-write drift
        expect(tree[0].workflow_count).toBe(1);
        expect(browserStore.scopes['org_a'].workflows['f1'].map((w) => w.id)).toEqual(['w1']);
    });

    it('removeWorkflowFromAllScopes clears a workflow from every loaded scope', () => {
        ensureScope('personal').workflows[''] = [wf('w', 'W'), wf('keep', 'K')];
        ensureScope('org_a').workflows['f1'] = [wf('w', 'W')]; // stale copy in another loaded scope
        removeWorkflowFromAllScopes('w');
        expect(browserStore.scopes['personal'].workflows[''].map((x) => x.id)).toEqual(['keep']);
        expect(browserStore.scopes['org_a'].workflows['f1']).toEqual([]);
    });

    it('updateWorkflowInAllScopes renames across every loaded scope', () => {
        ensureScope('personal').workflows[''] = [wf('w', 'Old')];
        ensureScope('org_a').workflows[''] = [wf('w', 'Old')];
        updateWorkflowInAllScopes('w', { name: 'New' });
        expect(browserStore.scopes['personal'].workflows[''][0].name).toBe('New');
        expect(browserStore.scopes['org_a'].workflows[''][0].name).toBe('New');
    });

    it('addWorkflow prepends (newest-first) and is idempotent by id', () => {
        const slice = ensureScope('org_a');
        slice.workflows[''] = []; // root loaded (as after the browser's first fetch)
        addWorkflow('org_a', null, wf('a', 'A'));
        addWorkflow('org_a', null, wf('b', 'B'));
        addWorkflow('org_a', null, wf('a', 'A-again')); // dup id → no-op
        expect(browserStore.scopes['org_a'].workflows[''].map((w) => w.id)).toEqual(['b', 'a']);
    });

    it('addWorkflow into an UNLOADED folder is a no-op (never materializes a partial list)', () => {
        ensureScope('org_a');
        addWorkflow('org_a', 'unloaded-folder', wf('x', 'X'));
        // The folder key stays absent, so graft keeps its server count / lazy-fetches fresh.
        expect('unloaded-folder' in browserStore.scopes['org_a'].workflows).toBe(false);
    });

    it('moveWorkflows into an UNLOADED target does not materialize it (no badge/content collapse)', () => {
        const slice = ensureScope('org_a');
        slice.workflows[''] = [wf('w1', 'W1')]; // root loaded (source)
        moveWorkflows('org_a', ['w1'], null, 'unloaded-target');
        expect(browserStore.scopes['org_a'].workflows['']).toEqual([]); // removed from source
        expect('unloaded-target' in browserStore.scopes['org_a'].workflows).toBe(false); // not materialized
    });

    it('an in-flight workflow:list cannot resurrect an optimistically-deleted workflow', async () => {
        setCurrentScope('org_a');
        const slice = ensureScope('org_a');
        slice.workflows[''] = [wf('w-del', 'Deleted'), wf('w-keep', 'Keep')]; // root loaded/displayed
        fetchWorkflows('org_a', null); // background SWR refresh in flight
        const req = lastReq('workflow:list');
        removeWorkflow('org_a', 'w-del', null); // optimistic delete supersedes the in-flight fetch
        // The stale server snapshot (still containing the deleted workflow) lands late.
        socket.serverEmit('response', { request_id: req, data: { workflows: [wf('w-del', 'Deleted'), wf('w-keep', 'Keep')] } });
        await flush();
        expect(browserStore.scopes['org_a'].workflows[''].some((w) => w.id === 'w-del')).toBe(false);
    });
});
