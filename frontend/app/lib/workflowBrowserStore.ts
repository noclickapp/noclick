// Scope-keyed store for the workflow browser (folders + workflows + shared-with-me).
//
// WHY THIS EXISTS: the previous hand-rolled cache mirrored scoped data into React
// state and threaded scope with a string path, which required a growing pile of
// manual guards (re-seed, epoch tokens, volatile resets, by-hand dedup, dual
// tree/flat-map writes). Those guards were duct tape over a fragile model, and
// bugs kept recurring: previous org's cards on switch, duplicate cards, and the
// same items cached under multiple orgs at once.
//
// THE INVARIANT THAT MAKES THOSE IMPOSSIBLE: every fetch and mutation takes an
// explicit `scopeId`, captured as a closure constant at issue time, and writes
// ONLY into `store.scopes[scopeId]`. Reads are pure selectors over
// `scopes[currentScopeId]`. A response issued for org A can therefore only ever
// touch A's slice — there is no code path that puts A's data into B's slice, so
// cross-scope contamination and stale-on-switch are unrepresentable, not guarded.
//
// The store is IN-MEMORY ONLY (per session). Scope slices live in this module
// singleton, so switching orgs within a session is instant; a hard reload
// refetches. We deliberately do NOT persist to IndexedDB — that cache was the
// original contamination vector (see the sweep at the bottom). Data is otherwise
// local-only (no YJS/Redis/collab/streaming); this module is fully contained to
// the workflow-browser surface.

import { proxy, ref } from 'valtio';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import { isTriggerSourceLite } from '~/lib/nodeIconRegistry';
import { resolveAgentModelKind } from '~/lib/harnessBrand';
import { valtioCache } from '~/lib/indexeddb';
import type { FolderInfo, FolderTreeResponse, SharedResourceInfo } from '~/types/socket-events.generated';

// ─── Public types (re-exported by useWorkflowBrowserData for consumers) ─────────

export interface TreeNode {
    id: string;
    name: string;
    type: 'folder' | 'workflow';
    children?: TreeNode[];
    folder_id?: string | null;
    parent_folder_id?: string | null;
    path?: string;
    workflow_count?: number;
    is_owner?: boolean;
    depth?: number;
    description?: string;
    updated_at?: string;
    isLoading?: boolean;
    isExpanded?: boolean;
}

export interface WorkflowApp {
    id: string;
    name: string;
    description: string;
    created_at?: string;
    updated_at?: string;
    is_owner?: boolean;
    user_permission?: string | null;
    owner_name?: string | null;
    /** Computed client-side from workflow_data.nodes — free, since the list response already returns the graph blob. */
    node_count?: number;
    /** Unique node type strings (e.g. "automation-slack") from the graph blob — used to show integration logos in the list. */
    node_types?: string[];
    /** Slim graph projection for card thumbnails (WorkflowGraphPreview). Absent when the list entry carries no graph blob (e.g. shared-with-me resources). */
    graph_preview?: GraphPreview;
}

// ─── Graph preview projection ───────────────────────────────────────────────────
// The list response ships the full workflow_data blob; we keep only what the card
// schematic needs (positions/types/edge pairs) so the store doesn't retain heavy
// configs (sticky markdown, mockedOutput, …) for every listed workflow.

export interface GraphPreviewNode {
    id: string;
    type: string;
    x: number;
    y: number;
    width?: number;
    height?: number;
    /** Agent nodes only: config.model, so the preview can render the harness logo (AgentModelIcon). */
    agentModel?: string;
    /** Sticky notes only: the palette index (config.color), so the preview tints them like the canvas. */
    stickyColor?: number;
    /** Set (true) only when the node is disabled / has a mocked output — the preview mirrors the canvas states. */
    disabled?: boolean;
    mocked?: boolean;
}

export interface GraphPreviewEdge {
    source: string;
    target: string;
    /** 'bottom' marks tools-provider wiring (provider top → agent underside); anchors differ from dataflow. */
    targetHandle?: string;
}

export interface GraphPreview {
    nodes: GraphPreviewNode[];
    edges: GraphPreviewEdge[];
}

const asFiniteNumber = (v: unknown): number | undefined => {
    // parseFloat tolerates style-sourced dimensions like "320px".
    const n = typeof v === 'string' ? parseFloat(v) : v;
    return typeof n === 'number' && Number.isFinite(n) ? n : undefined;
};

// Loose view of the untyped workflow_data blob — every field verified before use.
interface RawGraphBlob {
    nodes?: Array<{
        id?: unknown;
        type?: unknown;
        position?: { x?: unknown; y?: unknown } | null;
        width?: unknown;
        height?: unknown;
        config?: {
            model?: unknown;
            color?: unknown;
            operation?: unknown;
            disabled?: unknown;
            mockedOutput?: unknown;
        } | null;
    } | null>;
    edges?: Array<{
        source?: unknown;
        target?: unknown;
        sourceId?: unknown;
        targetId?: unknown;
        targetHandle?: unknown;
    } | null>;
}

/** Project the raw workflow_data blob down to the preview shape. An empty-but-present
 *  nodes array yields an empty preview (rendered as a blank canvas); undefined only
 *  when the entry carries no graph blob at all (e.g. shared-with-me listings). */
export function buildGraphPreview(workflowData: unknown): GraphPreview | undefined {
    const blob = (workflowData ?? {}) as RawGraphBlob;
    const rawNodes = blob.nodes;
    if (!Array.isArray(rawNodes)) return undefined;

    const nodes: GraphPreviewNode[] = [];
    // type + selected operation per node id for edge filtering below; operation is
    // deliberately NOT retained on the projection.
    const metaById = new Map<string, { type: string; operation?: string }>();
    for (const n of rawNodes) {
        const x = asFiniteNumber(n?.position?.x);
        const y = asFiniteNumber(n?.position?.y);
        if (typeof n?.id !== 'string' || typeof n.type !== 'string' || x === undefined || y === undefined) continue;
        metaById.set(n.id, {
            type: n.type,
            operation: typeof n.config?.operation === 'string' ? n.config.operation : undefined,
        });
        nodes.push({
            id: n.id,
            type: n.type,
            x,
            y,
            width: asFiniteNumber(n.width),
            height: asFiniteNumber(n.height),
            agentModel:
                n.type === 'agent' && typeof n.config?.model === 'string' ? n.config.model : undefined,
            stickyColor:
                n.type === 'stickyNote' && typeof n.config?.color === 'number' ? n.config.color : undefined,
            disabled: n.config?.disabled === true || undefined,
            mocked: n.config?.mockedOutput != null || undefined,
        });
    }

    const rawEdges = Array.isArray(blob.edges) ? blob.edges : [];
    const edges: GraphPreviewEdge[] = [];
    for (const e of rawEdges) {
        // Older blobs use sourceId/targetId (same dual convention GraphState.from_dict accepts).
        const source = e?.source ?? e?.sourceId;
        const target = e?.target ?? e?.targetId;
        if (typeof source !== 'string' || typeof target !== 'string') continue;
        const src = metaById.get(source);
        if (!src || !metaById.has(target)) continue;
        const targetHandle = typeof e?.targetHandle === 'string' ? e.targetHandle : undefined;
        // Mirror the canvas: a tools edge whose source currently has a TRIGGER
        // operation selected is an invalid legacy combo the canvas never renders
        // (trigger/provider mutual exclusivity) — don't draw it here either.
        if (targetHandle === 'bottom' && isTriggerSourceLite(src.type, src.operation)) continue;
        edges.push({ source, target, targetHandle });
    }

    return { nodes, edges };
}

export type FolderInfoLocal = {
    id: string;
    name: string;
    description: string;
    workflow_count: number;
    parent_folder_id?: string | null;
    path?: string;
    is_owner?: boolean;
    owner_name?: string | null;
    updated_at?: string;
};

// ─── Store shape ────────────────────────────────────────────────────────────────

// A per-scope slice. The hierarchy holds FOLDERS ONLY (nested folder tree from
// get_tree); workflow leaves are NOT stored here — they're grafted on at read
// time from `workflows`, so there is no dual representation to keep in sync.
export interface ScopeSlice {
    folders: TreeNode[];                        // folder-only nested tree
    foldersLoaded: boolean;                     // get_tree has resolved at least once (drives loadingTree)
    workflows: Record<string, WorkflowApp[]>;   // key '' = root; presence = that folder loaded
    workflowsLoading: Record<string, boolean>;  // per-folder-key in-flight flag
    tier: string;                               // per-scope (from workflow:list)
    hiddenSharedCount: number;                  // per-scope (from workflow:list)
}

// Shared-with-me resources are USER-scoped (the same across every org), so they
// live OUTSIDE any scope slice and are never written into one.
export interface SharedResources {
    workflows: WorkflowApp[];
    folders: FolderInfoLocal[];
    loaded: boolean;
}

interface BrowserStore {
    currentScopeId: string;
    scopes: Record<string, ScopeSlice>;
    shared: SharedResources;
}

function emptySlice(): ScopeSlice {
    return {
        folders: [],
        foldersLoaded: false,
        workflows: {},
        workflowsLoading: {},
        tier: 'free',
        hiddenSharedCount: 0,
    };
}

export const browserStore = proxy<BrowserStore>({
    currentScopeId: 'personal',
    scopes: {},
    shared: { workflows: [], folders: [], loaded: false },
});

// ─── Pure utils ─────────────────────────────────────────────────────────────────

// Dedup by id, keeping first occurrence. share:list_shared_with_me can return the
// same resource under multiple share rows (direct share + shared-folder
// descendant), so shared lists can carry duplicate ids; duplicate React keys
// corrupt reconciliation. Applied once, inside the selectors, so no consumer can
// reintroduce duplicates.
export function dedupById<T extends { id: string }>(items: T[]): T[] {
    const seen = new Set<string>();
    const out: T[] = [];
    for (const it of items) {
        if (seen.has(it.id)) continue;
        seen.add(it.id);
        out.push(it);
    }
    return out;
}

// `prev` (same id from the previous listing) lets an SWR refetch reuse the prior
// graph_preview/node_types BY IDENTITY when updated_at is unchanged, so unchanged
// cards keep their memoized layout instead of re-rendering after every refetch.
// Top-level fields are always taken fresh (permissions/shares can change without
// bumping updated_at). graph_preview is valtio ref()-wrapped: it's an immutable
// projection, so deep-proxying its node/edge objects would be pure overhead.
export const mapWorkflowApp = (wf: any, prev?: WorkflowApp): WorkflowApp => {
    const reuse = prev && prev.updated_at === wf.updated_at && prev.graph_preview ? prev : undefined;
    const gp = reuse?.graph_preview ?? buildGraphPreview(wf.workflow_data);
    return {
        id: wf.id,
        name: wf.name,
        description: wf.description || '',
        created_at: wf.created_at,
        updated_at: wf.updated_at,
        is_owner: wf.is_owner,
        user_permission: wf.user_permission,
        owner_name: wf.owner_name ?? null,
        node_count: Array.isArray(wf.workflow_data?.nodes) ? wf.workflow_data.nodes.length : undefined,
        node_types: reuse ? reuse.node_types : gp ? Array.from(new Set(gp.nodes.map((n) => n.type))) : undefined,
        graph_preview: gp ? (reuse ? gp : ref(gp)) : undefined,
    };
};

/** The types an icon row shows: branded integrations, agents (incl. the
 *  harness-expanded `agent:<kind>` synthetic keys). One predicate for the card
 *  pill guard/filter and the list rows so they can't drift. */
export const isWorkflowIconType = (t: string): boolean =>
    t.includes('-') || t === 'agent' || t.startsWith('agent:');

// Icon-row types with 'agent' expanded per harness (`agent:<kind>` — synthetic keys
// the dashboard loader serializes into the icon registry) so icon stacks show the
// actual harness mark. API-model agents (kind 'bot') keep the generic agent icon;
// the '' fallback resolves to 'bot' exactly like any non-CLI default model would.
// Shared by the card pill, list rows, and command palette.
export function workflowIconTypes(w: WorkflowApp): string[] {
    const types = w.node_types ?? [];
    if (!types.includes('agent') || !w.graph_preview) return types;
    const kinds = new Set(
        w.graph_preview.nodes
            .filter((n) => n.type === 'agent')
            .map((n) => resolveAgentModelKind(n.agentModel ?? '')),
    );
    // kinds can be empty when every agent node was dropped from the projection
    // (e.g. malformed position) — keep the generic icon rather than losing it.
    const agentTypes = kinds.size
        ? [...kinds].map((k) => (k === 'bot' ? 'agent' : `agent:${k}`))
        : ['agent'];
    return types.flatMap((t) => (t === 'agent' ? agentTypes : [t]));
}

// share_at maps to updated_at so list view sorts these by when they were shared.
export const mapSharedWorkflowResource = (r: SharedResourceInfo): WorkflowApp => ({
    id: r.resource_id,
    name: r.resource_name,
    description: r.resource_description || '',
    updated_at: r.shared_at,
    is_owner: false,
    user_permission: r.permission,
    owner_name: r.shared_by_name || r.shared_by_email || null,
});

export const mapSharedFolderResource = (r: SharedResourceInfo): FolderInfoLocal => ({
    id: r.resource_id,
    name: r.resource_name,
    description: r.resource_description || '',
    workflow_count: 0,
    parent_folder_id: null,
    is_owner: false,
    owner_name: r.shared_by_name || r.shared_by_email || null,
    updated_at: r.shared_at,
});

function convertFolderToTreeNode(folder: FolderInfo): TreeNode {
    return {
        id: folder.id,
        name: folder.name,
        type: 'folder',
        folder_id: folder.id,
        parent_folder_id: folder.parent_folder_id ?? null,
        path: folder.path,
        workflow_count: folder.workflow_count,
        is_owner: folder.is_owner,
        depth: folder.depth,
        description: folder.description ?? '',
        updated_at: folder.updated_at,
        children: folder.children?.map(convertFolderToTreeNode) || [],
    };
}

// Folder-tree manipulation (folders only — no workflow leaves live in the tree).
function mapFolders(nodes: TreeNode[], folderId: string, updater: (n: TreeNode) => TreeNode): TreeNode[] {
    return nodes.map((n) => {
        if (n.id === folderId) return updater(n);
        if (n.children?.length) return { ...n, children: mapFolders(n.children, folderId, updater) };
        return n;
    });
}

function removeFolderNode(nodes: TreeNode[], folderId: string): TreeNode[] {
    return nodes
        .filter((n) => n.id !== folderId)
        .map((n) => (n.children?.length ? { ...n, children: removeFolderNode(n.children, folderId) } : n));
}

export function findFolderInTree(nodes: TreeNode[], folderId: string): TreeNode | null {
    for (const n of nodes) {
        if (n.id === folderId && n.type === 'folder') return n;
        if (n.children) {
            const found = findFolderInTree(n.children, folderId);
            if (found) return found;
        }
    }
    return null;
}

export function buildFolderPath(nodes: TreeNode[], folderId: string): { id: string; name: string }[] {
    const path: { id: string; name: string }[] = [];
    const find = (list: TreeNode[], ancestors: { id: string; name: string }[]): boolean => {
        for (const n of list) {
            if (n.type !== 'folder') continue;
            const current = [...ancestors, { id: n.id, name: n.name }];
            if (n.id === folderId) {
                path.push(...current);
                return true;
            }
            if (n.children && find(n.children, current)) return true;
        }
        return false;
    };
    find(nodes, []);
    return path;
}

const wfLeaf = (wf: WorkflowApp, folderId: string | null): TreeNode => ({
    id: wf.id,
    name: wf.name,
    type: 'workflow',
    description: wf.description,
    folder_id: folderId,
});

// ─── Scope lifecycle ────────────────────────────────────────────────────────────

export function ensureScope(scopeId: string): ScopeSlice {
    if (!browserStore.scopes[scopeId]) {
        browserStore.scopes[scopeId] = emptySlice();
    }
    return browserStore.scopes[scopeId];
}

export function setCurrentScope(scopeId: string) {
    browserStore.currentScopeId = scopeId;
    ensureScope(scopeId);
}

// Test-only: wipe the module singleton so each test starts clean.
export function __resetBrowserStoreForTests() {
    browserStore.currentScopeId = 'personal';
    browserStore.scopes = {};
    browserStore.shared = { workflows: [], folders: [], loaded: false };
    for (const k of Object.keys(fetchSeq)) delete fetchSeq[k];
}

// Opaque rollback token for an optimistic mutation. Captures only the DATA that a
// mutation can touch (folder tree, per-folder workflow lists, shared lists) —
// NOT the transient loading flags or per-scope tier/count — so a rollback reverts
// the failed change without clobbering an in-flight fetch's loading state or tier.
export interface BrowserSnapshot {
    scopeId: string;
    folders: TreeNode[];
    workflows: Record<string, WorkflowApp[]>;
    shared: Pick<SharedResources, 'workflows' | 'folders'>;
}
// Deep clone through the valtio proxy into plain, mutable data (structuredClone
// rejects proxies; the data is all JSON-safe scalars/arrays/objects).
const deepClone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

export function snapshotScope(scopeId = browserStore.currentScopeId): BrowserSnapshot {
    const s = ensureScope(scopeId);
    return {
        scopeId,
        folders: deepClone(s.folders),
        workflows: deepClone(s.workflows),
        shared: { workflows: deepClone(browserStore.shared.workflows), folders: deepClone(browserStore.shared.folders) },
    };
}
export function restoreSnapshot(snap: BrowserSnapshot) {
    const s = ensureScope(snap.scopeId);
    s.folders = snap.folders;
    s.workflows = snap.workflows;
    browserStore.shared.workflows = snap.shared.workflows;
    browserStore.shared.folders = snap.shared.folders;
}

// ─── Selectors (pure reads over the current scope) ──────────────────────────────

// Graft workflow leaves onto the folder-only hierarchy for the sidebar. Leaves
// come from a folder's loaded workflow list; the count badge keeps the server
// `workflow_count` (matching the grid card, refreshed by refreshTree) rather than
// the leaf count — deriving from leaves would collapse an unloaded folder's badge
// when an optimistic move materializes a partial list, and would diverge from the
// grid (server count includes e.g. trashed rows the list omits).
function graft(folders: TreeNode[], workflows: Record<string, WorkflowApp[]>): TreeNode[] {
    return folders.map((f) => {
        const subfolders = graft(f.children?.filter((c) => c.type === 'folder') ?? [], workflows);
        const leaves = (f.id in workflows ? workflows[f.id] : []).map((w) => wfLeaf(w, f.id));
        return { ...f, children: [...subfolders, ...leaves], workflow_count: f.workflow_count };
    });
}

export function selectTree(slice: ScopeSlice): TreeNode[] {
    const folderNodes = graft(slice.folders, slice.workflows);
    const rootLeaves = ('' in slice.workflows ? slice.workflows[''] : []).map((w) => wfLeaf(w, null));
    return [...folderNodes, ...rootLeaves];
}

const folderToLocal = (n: TreeNode): FolderInfoLocal => ({
    id: n.id,
    name: n.name,
    description: n.description ?? '',
    workflow_count: n.workflow_count ?? 0,
    parent_folder_id: n.parent_folder_id ?? null,
    path: n.path,
    is_owner: n.is_owner,
    updated_at: n.updated_at,
});

// Direct subfolders of a parent (root = top-level). At root, user-level shared
// folders are merged in and the whole thing is deduped (own wins ties).
export function selectSubfolders(slice: ScopeSlice, shared: SharedResources, parentId: string | null): FolderInfoLocal[] {
    const own = parentId
        ? (findFolderInTree(slice.folders, parentId)?.children ?? []).filter((c) => c.type === 'folder').map(folderToLocal)
        : slice.folders.filter((n) => n.type === 'folder').map(folderToLocal);
    if (parentId) return dedupById(own); // shared items surface at the root only
    return dedupById([...own, ...shared.folders]);
}

export function selectWorkflows(slice: ScopeSlice, shared: SharedResources, folderId: string | null): WorkflowApp[] {
    const own = slice.workflows[folderId ?? ''] ?? [];
    if (folderId) return dedupById(own); // shared items surface at the root only
    return dedupById([...own, ...shared.workflows]);
}

// Flatten all folders (any depth) + shared folders — used by global search.
export function selectAllFolders(slice: ScopeSlice, shared: SharedResources): FolderInfoLocal[] {
    const out: FolderInfoLocal[] = [];
    const walk = (nodes: TreeNode[]) => {
        for (const n of nodes) {
            if (n.type !== 'folder') continue;
            out.push(folderToLocal(n));
            if (n.children) walk(n.children);
        }
    };
    walk(slice.folders);
    const ids = new Set(out.map((f) => f.id));
    return [...out, ...shared.folders.filter((f) => !ids.has(f.id))];
}

// All loaded workflows across every folder + shared — used by the command
// palette's jump-to-workflow. Deduped by id; own wins ties over a shared copy.
export function selectAllWorkflows(slice: ScopeSlice, shared: SharedResources): WorkflowApp[] {
    const own = Object.values(slice.workflows).flat();
    return dedupById([...own, ...shared.workflows]);
}

export function selectFolderPath(slice: ScopeSlice, folderId: string): { id: string; name: string }[] {
    return buildFolderPath(slice.folders, folderId);
}

// Have root + every OWN folder's workflows loaded? Drives the search skeleton:
// search fans out across all own folders (loadAllWorkflows), so it's "resolving"
// until they're all in. Considers ONLY own folders — shared folders surface at
// root and never load into `workflows`, so including them would keep this false
// forever for any user who has a shared folder (the old getAllFolders bug).
export function selectAllWorkflowsLoaded(slice: ScopeSlice): boolean {
    if (!('' in slice.workflows)) return false;
    const allLoaded = (nodes: TreeNode[]): boolean =>
        nodes.every((n) => n.type !== 'folder' || (n.id in slice.workflows && allLoaded(n.children ?? [])));
    return allLoaded(slice.folders);
}

// ─── Fetch actions (scope-addressed) ────────────────────────────────────────────
//
// Each captures `scopeId` as a closure constant and writes ONLY scopes[scopeId].
// A response from a superseded scope can therefore only touch its own (no longer
// read) slice — cross-scope contamination is unrepresentable.
//
// A monotonic per-(scope, resource) fetch sequence additionally drops out-of-order
// / superseded responses so the LATEST fetch for a key always wins regardless of
// arrival order — the standard query-cache guard, at the correct granularity (a
// key, not a global path string), so an A→B→A cycle resolves to A's newest data.
const fetchSeq: Record<string, number> = {};
const nextSeq = (k: string) => (fetchSeq[k] = (fetchSeq[k] ?? 0) + 1);
const isCurrentSeq = (k: string, seq: number) => fetchSeq[k] === seq;

// Supersede any in-flight workflow:list for a folder key so its response is
// dropped — used by optimistic mutations so a fetch issued before the mutation
// can't land afterward and re-add a just-removed workflow (or drop a just-added one).
const invalidateWorkflowsFetch = (scopeId: string, folderKey: string) => nextSeq(`${scopeId}::wf:${folderKey}`);

// ─── Removal tombstones ─────────────────────────────────────────────────────────
// A list response computed server-side BEFORE a delete/leave committed can arrive
// after the optimistic removal and resurrect the card (e.g. the return-to-grid SWR
// refetch racing the delete RPC — the seq token can't help because the refetch is
// newer than the removal). Removals tombstone the id briefly; list/shared response
// handlers drop tombstoned rows. Expiry keeps a failed-but-unrolled-back delete
// from hiding the workflow forever.
const _removalTombstones = new Map<string, number>();
const REMOVAL_TOMBSTONE_MS = 15_000;

const tombstoneRemoval = (workflowId: string) => {
    // Sweep expired entries on write — successfully deleted ids never reappear in
    // a response, so read-side expiry alone would let the map grow all session.
    const cutoff = Date.now() - REMOVAL_TOMBSTONE_MS;
    for (const [id, t] of _removalTombstones) {
        if (t < cutoff) _removalTombstones.delete(id);
    }
    _removalTombstones.set(workflowId, Date.now());
};

/** Call when a removal is rolled back (the delete/leave RPC failed) so refetches see the row again. */
export function clearRemovalTombstone(workflowId: string) {
    _removalTombstones.delete(workflowId);
}

function isTombstoned(workflowId: string): boolean {
    const t = _removalTombstones.get(workflowId);
    if (t === undefined) return false;
    if (Date.now() - t > REMOVAL_TOMBSTONE_MS) {
        _removalTombstones.delete(workflowId);
        return false;
    }
    return true;
}

// The org id this scope requests data for. Sent on every list/tree request so the
// BACKEND serves this exact scope's data instead of its mutable active-org context
// (which lags the client's optimistic org switch) — otherwise the previous org's
// folders/workflows land in this scope's slice. '' = personal.
const orgIdForScope = (scopeId: string) => (scopeId === 'personal' ? '' : scopeId.replace(/^org_/, ''));

export function fetchTree(scopeId: string) {
    ensureScope(scopeId);
    const k = `${scopeId}::tree`;
    const seq = nextSeq(k);

    sendEventWithCallback<FolderTreeResponse>({ event_name: 'workflow_folder:get_tree' as const, scope_org_id: orgIdForScope(scopeId) }, (response) => {
        if (!isCurrentSeq(k, seq)) return; // a newer fetch for this key superseded us
        const s = ensureScope(scopeId);
        s.foldersLoaded = true; // attempted — clears the tree spinner even on error
        if (response.error) return; // keep whatever we have on a transient error
        s.folders = response.folders ? response.folders.map(convertFolderToTreeNode) : [];
        // Fetch root workflows right after so the grid fills without a second trip.
        fetchWorkflows(scopeId, null);
    });

    fetchSharedResources();
}

export function fetchWorkflows(scopeId: string, folderId: string | null) {
    const key = folderId ?? '';
    const slice = ensureScope(scopeId);
    const k = `${scopeId}::wf:${key}`;
    const seq = nextSeq(k);
    slice.workflowsLoading[key] = true;

    sendEventWithCallback({ event_name: 'workflow:list' as const, folder_id: key, scope_org_id: orgIdForScope(scopeId) }, (response) => {
        if (!isCurrentSeq(k, seq)) return; // superseded
        const s = ensureScope(scopeId);
        s.workflowsLoading[key] = false;
        if (response.error || !response.workflows) return;
        // Reconcile against the previous listing so unchanged workflows keep their
        // object identity (see mapWorkflowApp) — a no-op refetch must not re-layout
        // every card.
        const prevById = new Map((s.workflows[key] ?? []).map((w) => [w.id, w]));
        s.workflows[key] = response.workflows
            .map((wf) => mapWorkflowApp(wf, prevById.get(wf.id)))
            .filter((w) => !isTombstoned(w.id));
        // hidden_shared_count is a root-level figure (plan-limited shared flows); a
        // subfolder listing reports its own (0) and must not overwrite the root's.
        if (key === '') {
            s.hiddenSharedCount = response.hidden_shared_count || 0;
            s.tier = response.subscription_tier || 'free';
        }
    });
}

// User-level; writes store.shared, never a scope slice.
export function fetchSharedResources() {
    const k = 'shared';
    const seq = nextSeq(k);
    sendEventWithCallback({ event_name: 'share:list_shared_with_me' as const }, (response) => {
        if (!isCurrentSeq(k, seq)) return; // superseded
        if (response.error) return; // don't clobber the existing list on a transient error
        const resources = response.resources ?? [];
        browserStore.shared.workflows = dedupById(
            resources
                .filter((r) => r.resource_type === 'workflow')
                .map(mapSharedWorkflowResource)
                .filter((w) => !isTombstoned(w.id)),
        );
        browserStore.shared.folders = dedupById(
            resources.filter((r) => r.resource_type === 'workflow_folder').map(mapSharedFolderResource),
        );
        browserStore.shared.loaded = true;
    });
}

export function refreshTree(scopeId: string) {
    fetchTree(scopeId);
}

// Ensure every folder's workflows are fetched (global search). force=true
// re-fetches already-loaded folders (command palette does this on open so node
// counts/types are current).
export function loadAllWorkflows(scopeId: string, force = false) {
    const slice = ensureScope(scopeId);
    const ensure = (key: string) => {
        if (!force && key in slice.workflows) return;
        fetchWorkflows(scopeId, key === '' ? null : key);
    };
    ensure('');
    const walk = (nodes: TreeNode[]) => {
        for (const n of nodes) {
            if (n.type !== 'folder') continue;
            ensure(n.id);
            if (n.children) walk(n.children);
        }
    };
    walk(slice.folders);
}

// ─── Mutations (scope-addressed, optimistic) ────────────────────────────────────
//
// Each touches only the flat data (workflows map or folder tree); the rendered
// tree derives from that, so there is no second representation to update or leave
// stale. Callers wanting rollback capture snapshotScope() first and restore on RPC
// error — mutations themselves never talk to the network.

export function addWorkflow(scopeId: string, folderId: string | null, workflow: WorkflowApp) {
    // Re-adding an id (restore, idempotent re-create) must lift any live removal
    // tombstone or the next list refetch silently drops the row again.
    clearRemovalTombstone(workflow.id);
    const s = ensureScope(scopeId);
    const key = folderId ?? '';
    if (!(key in s.workflows)) return; // folder not loaded — it lazy-fetches fresh on open
    const existing = s.workflows[key];
    if (existing.some((w) => w.id === workflow.id)) return;
    s.workflows[key] = [workflow, ...existing]; // prepend to match server newest-first
    invalidateWorkflowsFetch(scopeId, key);
}

export function removeWorkflow(scopeId: string, workflowId: string, folderId: string | null) {
    tombstoneRemoval(workflowId);
    const s = ensureScope(scopeId);
    const key = folderId ?? '';
    if (s.workflows[key]) {
        s.workflows[key] = s.workflows[key].filter((w) => w.id !== workflowId);
        invalidateWorkflowsFetch(scopeId, key);
    }
}

export function removeWorkflowGlobal(scopeId: string, workflowId: string) {
    tombstoneRemoval(workflowId);
    const s = ensureScope(scopeId);
    for (const key of Object.keys(s.workflows)) {
        if (s.workflows[key].some((w) => w.id === workflowId)) {
            s.workflows[key] = s.workflows[key].filter((w) => w.id !== workflowId);
            invalidateWorkflowsFetch(scopeId, key);
        }
    }
}

export function updateWorkflow(scopeId: string, workflowId: string, updates: Partial<WorkflowApp>) {
    const s = ensureScope(scopeId);
    for (const key of Object.keys(s.workflows)) {
        const list = s.workflows[key];
        if (list.some((w) => w.id === workflowId)) {
            s.workflows[key] = list.map((w) => (w.id === workflowId ? { ...w, ...updates } : w));
        }
    }
    // Keep the user-level shared copy in sync (a rename of a flow surfaced only
    // from the shared list must not go stale).
    const shared = browserStore.shared.workflows;
    if (shared.some((w) => w.id === workflowId)) {
        browserStore.shared.workflows = shared.map((w) => (w.id === workflowId ? { ...w, ...updates } : w));
    }
}

export function moveWorkflows(scopeId: string, workflowIds: string[], fromFolder: string | null, toFolder: string | null) {
    const s = ensureScope(scopeId);
    const fromKey = fromFolder ?? '';
    const toKey = toFolder ?? '';
    const idSet = new Set(workflowIds);
    const fromList = s.workflows[fromKey] ?? [];
    const moved = fromList.filter((w) => idSet.has(w.id));
    // Only touch a folder's list if it's already loaded; an unloaded folder stays
    // unmaterialized so it lazy-fetches fresh (never collapses its badge/contents).
    if (fromKey in s.workflows) s.workflows[fromKey] = fromList.filter((w) => !idSet.has(w.id));
    if (toKey in s.workflows) {
        const existing = new Set(s.workflows[toKey].map((w) => w.id));
        s.workflows[toKey] = [...s.workflows[toKey], ...moved.filter((w) => !existing.has(w.id))];
    }
    invalidateWorkflowsFetch(scopeId, fromKey);
    invalidateWorkflowsFetch(scopeId, toKey);
}

// A workflow lives in exactly one scope, but the user may have several scopes
// cached. These fan a by-id mutation across every loaded scope so an external
// (MCP) delete/rename can't leave a stale copy in a non-current scope's cache.
export function removeWorkflowFromAllScopes(workflowId: string) {
    for (const scopeId of Object.keys(browserStore.scopes)) removeWorkflowGlobal(scopeId, workflowId);
}
export function updateWorkflowInAllScopes(workflowId: string, updates: Partial<WorkflowApp>) {
    for (const scopeId of Object.keys(browserStore.scopes)) updateWorkflow(scopeId, workflowId, updates);
}

export function removeSharedWorkflow(workflowId: string) {
    browserStore.shared.workflows = browserStore.shared.workflows.filter((w) => w.id !== workflowId);
}

export function removeSharedFolder(folderId: string) {
    browserStore.shared.folders = browserStore.shared.folders.filter((f) => f.id !== folderId);
}

// Folder mutations touch the folder-only hierarchy.
export function addFolder(scopeId: string, parentId: string | null, folder: TreeNode) {
    const s = ensureScope(scopeId);
    if (!parentId) {
        s.folders = [...s.folders, folder];
    } else {
        s.folders = mapFolders(s.folders, parentId, (node) => ({
            ...node,
            children: [...(node.children ?? []), folder],
        }));
    }
}

export function removeFolder(scopeId: string, folderId: string) {
    const s = ensureScope(scopeId);
    s.folders = removeFolderNode(s.folders, folderId);
    if (folderId in s.workflows) delete s.workflows[folderId];
}

export function updateFolder(scopeId: string, folderId: string, updates: Partial<TreeNode>) {
    const s = ensureScope(scopeId);
    s.folders = mapFolders(s.folders, folderId, (node) => ({ ...node, ...updates }));
}

export function moveFolders(scopeId: string, folderIds: string[], toParentId: string | null) {
    const s = ensureScope(scopeId);
    let tree = s.folders;
    const movedNodes: TreeNode[] = [];
    for (const id of folderIds) {
        const node = findFolderInTree(tree, id);
        if (node) movedNodes.push(node);
        tree = removeFolderNode(tree, id);
    }
    for (const node of movedNodes) {
        const updated = { ...node, parent_folder_id: toParentId };
        if (!toParentId) tree = [...tree, updated];
        else tree = mapFolders(tree, toParentId, (parent) => ({ ...parent, children: [...(parent.children ?? []), updated] }));
    }
    s.folders = tree;
}

// ─── One-time legacy cache sweep ────────────────────────────────────────────────
//
// The store is intentionally IN-MEMORY ONLY (per session). Scope slices live in
// this module singleton, so switching orgs within a session is instant and a full
// reload refetches. We deliberately do NOT persist to IndexedDB: the old per-path
// cache was the contamination vector — it held cross-scope-poisoned data and,
// lacking a user dimension in its key, could even surface one user's list to the
// next on a shared browser. Not persisting makes both classes impossible by
// construction, at the cost of a refetch (not a stale render) after a hard reload.
//
// We still sweep the pre-refactor keys once, so any already-poisoned cache from a
// previous version is cleared on upgrade rather than lingering unread.
let sweptLegacy = false;
export async function sweepLegacyCache() {
    if (sweptLegacy || typeof window === 'undefined') return;
    sweptLegacy = true;
    try {
        const keys = await valtioCache.getAllKeys();
        await Promise.all(keys.filter((k) => k.includes('/workflow_browser/')).map((k) => valtioCache.delete(k)));
    } catch (e) {
        console.error('[workflowBrowserStore] legacy cache sweep failed', e);
    }
}

// ─── MCP socket listeners ───────────────────────────────────────────────────────
//
// External (MCP-driven) create/delete/rename applied scope-exactly:
//  - create carries the target scope (organization_id) + folder_id, so it lands in
//    the right scope's list (no-op if that scope/folder isn't loaded — it fetches
//    fresh on open), never as a phantom card in whatever scope is being viewed;
//  - delete/rename address by id and fan across every loaded scope (a workflow
//    lives in one), so they can't leave a stale copy in a non-current scope.
// Registered once at module load.

// scopeId for a workflow's owning org — mirrors Dashboard's orgPathSuffix.
const scopeIdForOrg = (organizationId: string | null | undefined) =>
    organizationId ? `org_${organizationId}` : 'personal';

let mcpWired = false;
export function wireMcpListeners() {
    if (mcpWired || typeof window === 'undefined') return;
    mcpWired = true;
    onSocketEvent(
        'mcp:workflow:create_workflow:response',
        (r) => {
            if (!r.success) return;
            addWorkflow(scopeIdForOrg(r.organization_id), r.folder_id ?? null, {
                id: r.workflow_id,
                name: r.name ?? 'Untitled Workflow',
                description: r.description ?? '',
                is_owner: true,
            });
        },
    );
    onSocketEvent('mcp:workflow:delete_workflow:response', (r) => {
        if (!r.success) return;
        removeWorkflowFromAllScopes(r.workflow_id);
    });
    onSocketEvent(
        'mcp:workflow:update_workflow_metadata:response',
        (r) => {
            if (!r.success) return;
            updateWorkflowInAllScopes(r.workflow_id, {
                ...(r.name != null && { name: r.name }),
                ...(r.description != null && { description: r.description }),
            });
        },
    );
}
