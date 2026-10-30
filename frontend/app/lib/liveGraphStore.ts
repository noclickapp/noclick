// Module-level shadow of the workflow graph keyed by workflow id, so
// persistence outlives FlowCanvas mount/unmount. Canvas writes a full
// snapshot here on every change; the store owns the autosave debounce,
// gen-terminal flush, and pagehide beacon.
//
// Why this exists: the canvas used to autosave from its own React state.
// Quick navigation away (Remix in-tab) ran the unmount cleanup with a
// stale snapshot or hit the 3s MCP-event skip guard, dropping unsaved
// edits. Hoisting the save trigger above the mount lifecycle eliminates
// both races without lifting the source of truth (Phase 1).
//
// What stays in the canvas: read state, presence broadcasts, mutation
// pipelines (setNodes/setEdges), drag/load lifecycle. The canvas just
// pushes a snapshot to the store on changes and tells it about lifecycle
// transitions.

import { proxy, useSnapshot } from 'valtio';
import type { Node, Edge, Node as XYFlowNode, Edge as XYFlowEdge } from '@xyflow/react';
import { valtioCache } from '~/lib/indexeddb';
import { sendEvent, sendEventAsync, sendEventWithCallback } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import { serializeNodeForSave, serializeEdgeForSave, createWorkflowNode, applyNodeUpdate, mergeServerNodes, rawConfigToPayload } from '~/lib/applyNodeUpdate';
import { headlessBuilder } from '~/lib/headless-builder';
import { GRAPH_EVENT_TYPES, serverEdgesAfter, serverNodesAfter } from '~/lib/serverGraphEvents';
import { activeGenStore } from '~/lib/activeGenStore';

interface InterfaceGridState {
    layout: ReadonlyArray<unknown>;
    tabOrder?: ReadonlyArray<unknown>;
}

type DisplayMetadata = object;

/** Each step and connection as the server holds it, as far as this canvas knows, serialized as a save sends it. */
interface GraphBase {
    nodes: Map<string, string>;
    edges: Map<string, string>;
}

interface GraphRecord {
    workflowId: string;
    isSkill: boolean;
    nodes: Node[];
    edges: Edge[];
    interfaceGridState: InterfaceGridState | null;
    variables: Record<string, unknown>;
    displayMetadata: DisplayMetadata | null;
    deletedNodeIds: Set<string>;
    // Deletes another writer streamed to us (a collaborator over the collab
    // channel, the AI builder over its event stream) whose own persist may
    // not have landed yet. Used ONLY as rebase tombstones: a CAS conflict
    // answers with the row as it stands, and without these a node the
    // builder just removed reads as "server-only" and comes straight back
    // (2026-09-22). Full workflow:get loads re-baseline and clear both.
    remoteDeletedNodeIds: Set<string>;
    remoteDeletedEdgeIds: Set<string>;

    // Lifecycle flags. Saves are suppressed unless `loaded` is true and
    // `dragging` is false. Headless-active is queried directly from the
    // headlessBuilder singleton (it's already module-level), so it
    // doesn't need a per-record mirror.
    //
    // canvasMounted: tracks whether FlowCanvas is actively pushing
    // snapshots into this record. When false, the store's snapshot is
    // stale (agentic node_added events go through the canvas's setNodes
    // pipeline, not through the store directly), so we must not fire
    // saves from it — they would clobber the BE's authoritative copy.
    loaded: boolean;
    dragging: boolean;
    canvasMounted: boolean;
    // The viewer can only read this workflow (workflow:get's user_permission is view): it never saves.
    readOnly: boolean;
    // Steps the canvas holds only in part: a server write's room event held some of each back (a secret, an
    // outsize setting) and the canvas hasn't read it whole. They can't be edited (their panel shows them
    // loading), every save names them so the server keeps their settings as stored, and a full load, a server
    // copy a conflict takes or their own read makes them whole. An object, so a panel re-renders on the change.
    partialNodeIds: Record<string, true>;
    // The per-step base of a three-way merge: what the server holds, as far as this canvas knows. Set on load
    // and on each acked save, and moved by every server change the canvas takes (a written change's room
    // events, a server copy a conflict takes, a step read whole). A step or connection that differs from it
    // is the canvas's own change: a conflict keeps those and takes the server's copy of the rest, and a closing
    // tab's last save names only those. null before a load (then everything local counts as its own).
    base: GraphBase | null;
    // While a save is in flight: the written changes heard since it was sent (replayed onto the base its ack sets,
    // so the ack never resets them out of it), and the room's notices of writes made on a version this canvas
    // reaches only when the ack lands (taken then, in order).
    heardSinceSend: Array<{ eventType: string; data: Record<string, unknown> }> | null;
    noticesSinceSend: Array<{ base: number; version: number }>;

    // Save coordination. graphVersion is the server's optimistic-concurrency
    // token from the last workflow:get / save ack (null = unknown → save
    // unconditionally, matching pre-CAS behavior). One save in flight at a
    // time; dirty-set-during-flight chains the next save off the ack.
    dirty: boolean;
    saveTimer: ReturnType<typeof setTimeout> | null;
    graphVersion: number | null;
    saveInFlight: boolean;
    saveFailures: number;
    // JSON of the last acked save payload (seeded from workflow:get). A
    // scheduled save whose payload matches it is a no-op — skipped before
    // it hits the wire, so opening a workflow doesn't write the DB.
    lastSavedPayloadJson: string | null;
}

const DEBOUNCE_MS = 2000;
// Ack watchdog: a save whose response never arrives (socket died mid-flight)
// must release the in-flight latch so later saves aren't wedged.
const SAVE_ACK_TIMEOUT_MS = 15000;
// Consecutive-failure cap: stop auto-retrying after this many failures in a
// row (dirty stays true, so the next edit / flush / remount re-attempts).
const MAX_CONSECUTIVE_SAVE_FAILURES = 5;

// Valtio-proxied so the canvas can read nodes/edges reactively via
// useLiveGraph (Phase 2). Object-keyed by workflowId rather than Map
// because Valtio's reactivity tracks property reads on objects, not
// Map operations.
export const graphRecords = proxy<Record<string, GraphRecord>>({});

/** Fresh record shape — shared with useLiveGraph's synchronous bootstrap so
 *  the two creation sites can't drift. */
export function createGraphRecord(
    workflowId: string,
    isSkill: boolean,
    initialNodes: Node[] = [],
    initialEdges: Edge[] = [],
): GraphRecord {
    return {
        workflowId,
        isSkill,
        nodes: initialNodes,
        edges: initialEdges,
        interfaceGridState: null,
        variables: {},
        displayMetadata: null,
        deletedNodeIds: new Set(),
        remoteDeletedNodeIds: new Set(),
        remoteDeletedEdgeIds: new Set(),
        loaded: false,
        dragging: false,
        canvasMounted: false,
        readOnly: false,
        partialNodeIds: {},
        base: null,
        heardSinceSend: null,
        noticesSinceSend: [],
        dirty: false,
        saveTimer: null,
        graphVersion: null,
        saveInFlight: false,
        saveFailures: 0,
        lastSavedPayloadJson: null,
    };
}

function ensureRecord(workflowId: string, isSkill: boolean): GraphRecord {
    let rec = graphRecords[workflowId];
    if (!rec) {
        rec = createGraphRecord(workflowId, isSkill);
        graphRecords[workflowId] = rec;
    }
    return rec;
}

/** True when workflow id is real (not demo/temp), so saves are allowed. */
function isPersistableWorkflowId(workflowId: string): boolean {
    return !!workflowId
        && !workflowId.startsWith('workflow_demo')
        && !workflowId.startsWith('temp-');
}

/** Build the wire payload from the record's current snapshot. Mirrors
 *  the shape FlowCanvas was sending pre-lift (kept verbatim so the BE
 *  contract is unchanged). */
function buildPayload(rec: GraphRecord): {
    event: Record<string, unknown>;
    deletedNodeIds: string[];
    savePayload: Record<string, unknown>;
} {
    const deletedNodeIds = Array.from(rec.deletedNodeIds);
    // Drop any malformed entries (missing id) before serialization.
    // These shouldn't exist — createWorkflowNode now throws on missing
    // id, and the agentic event handlers bail — but if one slips
    // through (or a stale state from before those guards landed), we
    // don't want to ship it to the BE where compute_workflow_delta
    // and other id-keyed paths choke.
    const safeNodes = rec.nodes.filter(n => n && typeof n.id === 'string' && n.id.length > 0);
    const safeEdges = rec.edges.filter(e => e && typeof e.id === 'string' && e.id.length > 0);
    if (safeNodes.length !== rec.nodes.length || safeEdges.length !== rec.edges.length) {
        console.warn(
            '[liveGraphStore] dropping malformed graph entries before save',
            { droppedNodes: rec.nodes.length - safeNodes.length, droppedEdges: rec.edges.length - safeEdges.length },
        );
    }
    const savePayload: Record<string, unknown> = {
        nodes: safeNodes.map(serializeNodeForSave),
        edges: safeEdges.map(serializeEdgeForSave),
        interface: rec.interfaceGridState ?? undefined,
    };
    if (Object.keys(rec.variables).length > 0) {
        savePayload.variables = rec.variables;
    }
    const partialNodeIds = Object.keys(rec.partialNodeIds);
    const event: Record<string, unknown> = rec.isSkill
        ? {
            event_name: 'skill:update_workflow',
            skill_id: rec.workflowId,
            body_workflow: savePayload,
            display_metadata: rec.displayMetadata,
        }
        : {
            event_name: 'workflow:update',
            workflow_id: rec.workflowId,
            workflow_data: savePayload,
            ...(deletedNodeIds.length > 0 ? { deleted_node_ids: deletedNodeIds } : {}),
            ...(partialNodeIds.length > 0 ? { partial_node_ids: partialNodeIds } : {}),
        };
    return { event, deletedNodeIds, savePayload };
}

type SavedGraph = { nodes?: Array<{ id?: string }>; edges?: Array<{ id?: string }> };

const nodeJson = (node: Node) => JSON.stringify(serializeNodeForSave(node));
const edgeJson = (edge: Edge) => JSON.stringify(serializeEdgeForSave(edge));

function baseOf(nodes: Node[], edges: Edge[]): GraphBase {
    return {
        nodes: new Map(nodes.filter((n) => n?.id).map((n) => [n.id, nodeJson(n)])),
        edges: new Map(edges.filter((e) => e?.id).map((e) => [e.id, edgeJson(e)])),
    };
}

/** The base a save sets once acked: what it sent is what the server holds. */
function baseOfSaved(saved: SavedGraph): GraphBase {
    const byId = (items: Array<{ id?: string }> | undefined) =>
        new Map((items ?? []).filter((x) => x?.id).map((x) => [x.id as string, JSON.stringify(x)]));
    return { nodes: byId(saved.nodes), edges: byId(saved.edges) };
}

/** The step differs from what the server holds as far as the canvas knows: the canvas's own change (or no base
 *  yet, when everything local counts as its own). */
function changedHere(rec: GraphRecord, node: Node): boolean {
    return !rec.base || rec.base.nodes.get(node.id) !== nodeJson(node);
}

/** What the canvas changed since its base: steps it added or changed, connections it added or removed. A
 *  closing tab's save names them, so a workflow that moved on without it takes only these (its deleted steps
 *  ride `deleted_node_ids`). */
function changesSinceBase(rec: GraphRecord, savePayload: SavedGraph): {
    steps: string[];
    edges_added: string[];
    edges_removed: string[];
} {
    const base = rec.base ?? { nodes: new Map<string, string>(), edges: new Map<string, string>() };
    const nodes = (savePayload.nodes ?? []).filter((n) => n?.id);
    const edges = new Set((savePayload.edges ?? []).filter((e) => e?.id).map((e) => e.id as string));
    return {
        steps: nodes.filter((n) => base.nodes.get(n.id as string) !== JSON.stringify(n)).map((n) => n.id as string),
        edges_added: [...edges].filter((id) => !base.edges.has(id)),
        edges_removed: [...base.edges.keys()].filter((id) => !edges.has(id)),
    };
}

/** DB-shaped snapshot of the live canvas graph, for the brain to consume on a
 *  builder resume (answering an <ask/>). The agent's just-added nodes may not
 *  have reached the debounced auto-save in public.workflows yet, so the resume
 *  handler would otherwise read a stale/empty graph and re-add them (B8).
 *
 *  Returns null when the store isn't a trustworthy source (canvas unmounted or
 *  not yet loaded — agentic mutations bypass the store then), so the backend
 *  falls back to its DB read. Shape mirrors the auto-save payload, which the
 *  resume handler already consumes. */
export function getBackendGraphSnapshot(
    workflowId: string,
): { workflow_id: string; nodes: unknown[]; edges: unknown[] } | null {
    const rec = graphRecords[workflowId];
    if (!rec || !rec.loaded || !rec.canvasMounted) return null;
    const nodes = rec.nodes.filter((n) => n && typeof n.id === 'string' && n.id.length > 0);
    const edges = rec.edges.filter((e) => e && typeof e.id === 'string' && e.id.length > 0);
    return {
        workflow_id: workflowId,
        nodes: nodes.map(serializeNodeForSave),
        edges: edges.map(serializeEdgeForSave),
    };
}

/** May this record be persisted right now? */
function canSave(rec: GraphRecord): boolean {
    if (!isPersistableWorkflowId(rec.workflowId)) return false;
    if (!rec.loaded) return false;
    if (rec.readOnly) return false;
    if (rec.dragging) return false;
    if (headlessBuilder.isActive()) return false;
    // Snapshot is only fresh while the canvas is mounted and recording
    // into this record. When unmounted, agentic mutations bypass the
    // store, so saving from it would clobber the BE's truth.
    if (!rec.canvasMounted) return false;
    return true;
}

/** Convert one raw backend node blob (the save/load wire shape) into a
 *  canvas Node. Used by the CAS-conflict rebase for server-only nodes;
 *  width/height ride top-level like serializeNodeForSave writes them. */
function rawNodeToCanvasNode(raw: Record<string, unknown>): Node {
    const node = createWorkflowNode(
        raw.id as string,
        raw.type as string,
        (raw.position as { x: number; y: number }) ?? { x: 0, y: 0 },
        (raw.config as Record<string, unknown>) ?? {},
    );
    if (raw.width) (node as { width?: unknown }).width = raw.width;
    if (raw.height) (node as { height?: unknown }).height = raw.height;
    return node;
}

/** Fold the server's current graph into the record: a CAS conflict's answer, or a full read when a step couldn't
 *  be read whole. A three-way merge over the per-step base (`rec.base`): what the canvas changed since its base
 *  wins (the user's own edits, the steps and connections they added); a step or connection it holds unchanged
 *  is the server's, its copy taken (whole: no longer partial), and one the server no longer has goes (another
 *  writer changed or removed it, maybe one the canvas never heard: the builder's, MCP's or the platform's).
 *  Server-only steps are adopted UNLESS tombstoned (my pending delete, or a collaborator's delete whose save
 *  hasn't landed yet), server-only connections unless removed here. The base becomes the server's graph, so a
 *  second conflict judges against it. The re-save that follows persists the merged result under the server's
 *  new version. */
function rebaseFromServer(
    rec: GraphRecord,
    serverData: { nodes?: unknown[]; edges?: unknown[] } | null | undefined,
    serverVersion: number | null | undefined,
): void {
    if (typeof serverVersion === 'number') rec.graphVersion = serverVersion;
    const serverNodes = new Map(
        ((serverData?.nodes ?? []) as Record<string, unknown>[])
            .filter((raw) => typeof raw?.id === 'string' && raw.type)
            .map((raw) => [raw.id as string, rawNodeToCanvasNode(raw)] as const),
    );
    const serverEdges = ((serverData?.edges ?? []) as Record<string, unknown>[])
        .filter((raw) => raw?.id && raw.source && raw.target)
        .map((raw) => ({
            id: raw.id as string,
            source: raw.source as string,
            target: raw.target as string,
            ...(raw.sourceHandle ? { sourceHandle: raw.sourceHandle as string } : {}),
            ...(raw.targetHandle ? { targetHandle: raw.targetHandle as string } : {}),
        }) as Edge);
    const dropped = (id: string) => rec.deletedNodeIds.has(id) || rec.remoteDeletedNodeIds.has(id);

    const nodes: Node[] = [];
    for (const node of rec.nodes) {
        const server = serverNodes.get(node.id);
        if (server && !changedHere(rec, node)) {
            nodes.push(mergeServerNodes([server], [node])[0]);
            delete rec.partialNodeIds[node.id];
        } else if (server || changedHere(rec, node)) {
            nodes.push(node);
        }
    }
    const nodeIds = new Set(nodes.map((n) => n.id));
    for (const [id, server] of serverNodes) {
        if (nodeIds.has(id) || dropped(id)) continue;
        nodes.push(server);
        nodeIds.add(id);
    }

    const serverEdgeIds = new Set(serverEdges.map((e) => e.id));
    const edges = rec.edges.filter(
        (e) => (serverEdgeIds.has(e.id) || !rec.base?.edges.has(e.id)) && nodeIds.has(e.source) && nodeIds.has(e.target),
    );
    const edgeIds = new Set(edges.map((e) => e.id));
    const localEdgeIds = new Set(rec.edges.map((e) => e.id));
    for (const edge of serverEdges) {
        if (edgeIds.has(edge.id) || rec.remoteDeletedEdgeIds.has(edge.id)) continue;
        // Removed here since the base: it stays removed.
        if (rec.base?.edges.has(edge.id) && !localEdgeIds.has(edge.id)) continue;
        // An edge is only meaningful if both endpoints survived the merge.
        if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
        edges.push(edge);
    }
    rec.nodes = nodes;
    rec.edges = edges;
    rec.base = baseOf([...serverNodes.values()], serverEdges);
    for (const listener of serverChangeListeners) listener(rec.workflowId, null);
}

function fireSave(rec: GraphRecord, opts?: { unconditional?: boolean }): void {
    if (!canSave(rec) || !rec.dirty) return;

    // Pagehide flush: the page is dying, so no ack/rebase cycle is possible.
    // Send fire-and-forget, ignoring the in-flight latch (an in-flight save
    // predates the last edits and must not swallow them), on the version this
    // canvas last saw and naming what it changed since: a workflow that moved
    // on without this tab takes only its own changes, never its stale copy of
    // the rest.
    if (opts?.unconditional) {
        const { event, deletedNodeIds, savePayload } = buildPayload(rec);
        if (
            deletedNodeIds.length === 0 &&
            JSON.stringify(savePayload) === rec.lastSavedPayloadJson
        ) {
            rec.dirty = false;
            return;
        }
        (event as { request_id: string }).request_id = crypto.randomUUID();
        if (!rec.isSkill && rec.graphVersion != null) {
            (event as Record<string, unknown>).expected_graph_version = rec.graphVersion;
            (event as Record<string, unknown>).changes = changesSinceBase(rec, savePayload as SavedGraph);
        }
        sendEvent(event as never);
        rec.dirty = false;
        return;
    }

    if (rec.saveInFlight) return; // ack handler chains the next save
    const { event, deletedNodeIds, savePayload } = buildPayload(rec);
    // Content gate: dirty is a cheap over-approximation (the canvas marks it
    // on any nodes/edges identity change, including the post-load merge), so
    // opening a workflow schedules a "save" of unchanged content. Comparing
    // the serialized payload against the last acked/loaded one keeps those
    // off the wire — no DB write, no updated_at recency churn.
    const payloadJson = JSON.stringify(savePayload);
    if (deletedNodeIds.length === 0 && payloadJson === rec.lastSavedPayloadJson) {
        rec.dirty = false;
        return;
    }
    // CAS guard: echo the version this client last saw so a stale snapshot
    // loses cleanly server-side (conflict + rebase) instead of clobbering a
    // newer save. Version-less records (never loaded) save unconditionally.
    if (!rec.isSkill && rec.graphVersion != null) {
        (event as Record<string, unknown>).expected_graph_version = rec.graphVersion;
    }

    rec.saveInFlight = true;
    rec.dirty = false; // optimistic; failure paths re-set it
    rec.heardSinceSend = [];
    rec.noticesSinceSend = [];

    let cleanup: (() => void) | undefined;
    let settled = false;
    // Watchdog: a save whose ack never arrives must release the in-flight
    // latch (settle/onFailure are const arrows below — assigned by the time
    // this callback can run).
    const watchdog = setTimeout(() => {
        if (!settle()) return;
        onFailure('ack timeout');
    }, SAVE_ACK_TIMEOUT_MS);
    const settle = () => {
        if (settled) return false;
        settled = true;
        clearTimeout(watchdog);
        cleanup?.();
        rec.saveInFlight = false;
        return true;
    };

    const onFailure = (why: string) => {
        rec.dirty = true;
        rec.saveFailures += 1;
        if (rec.saveFailures <= MAX_CONSECUTIVE_SAVE_FAILURES) {
            scheduleSave(rec);
        } else {
            console.error(
                `[liveGraphStore] save failing repeatedly for ${rec.workflowId} (${why}); ` +
                'holding dirty state for the next edit/flush/remount',
            );
        }
    };

    const onAck = ((resp: {
        conflict?: boolean;
        graph_version?: number;
        workflow_data?: { nodes?: unknown[]; edges?: unknown[] };
        error?: string;
        workflow?: { graph_version?: number };
    }) => {
        if (!settle()) return;
        const heard = rec.heardSinceSend ?? [];
        const notices = rec.noticesSinceSend;
        rec.heardSinceSend = null;
        rec.noticesSinceSend = [];
        if (resp?.conflict) {
            // Another writer (other tab/device, MCP, builder) bumped the
            // version. Fold their graph in and re-save under the new version.
            rebaseFromServer(rec, resp.workflow_data, resp.graph_version ?? null);
            rec.dirty = true;
            rec.saveFailures = 0;
            scheduleSave(rec);
            return;
        }
        if (resp?.error) {
            console.warn(`[liveGraphStore] save rejected for ${rec.workflowId}:`, resp.error);
            onFailure(resp.error);
            return;
        }
        // Success: adopt the new version, retire the acked tombstones, and
        // mirror what the server now holds into the instant-render cache
        // (FlowCanvas otherwise only writes it on workflow:get, so after a
        // delete the cache would still hold the pre-delete graph and the
        // next mount would restore — and eventually re-save — deleted nodes).
        rec.saveFailures = 0;
        const newVersion = resp?.workflow?.graph_version;
        // A save acked after a server write moved the base on (its room notice came first) never moves it back.
        if (typeof newVersion !== 'number' || rec.graphVersion == null || newVersion >= rec.graphVersion) {
            rec.lastSavedPayloadJson = payloadJson;
            // What it sent is what the server holds, with the written changes heard since on top.
            rec.base = heard.reduce(
                (base, { eventType, data }) => baseAfter(base, eventType, data),
                baseOfSaved(savePayload as SavedGraph),
            );
            if (typeof newVersion === 'number') {
                rec.graphVersion = newVersion;
                // Writes made on the version this save produced, heard while it was on its way: taken, in order.
                for (const notice of notices) {
                    if (notice.base === rec.graphVersion) rec.graphVersion = notice.version;
                }
            }
        }
        for (const id of deletedNodeIds) rec.deletedNodeIds.delete(id);
        try {
            // JSON round-trip strips valtio proxies for structured clone.
            void valtioCache.set(
                `workflow-canvas:${rec.workflowId}`,
                JSON.parse(JSON.stringify(savePayload))
            );
        } catch (e) {
            console.warn('[liveGraphStore] cache mirror skipped:', e);
        }
        if (rec.dirty) scheduleSave(rec); // edits arrived during flight
    }) as never;

    try {
        cleanup = sendEventWithCallback(event as never, onAck);
    } catch (e) {
        settle();
        onFailure(`send threw: ${e}`);
    }
}

function scheduleSave(rec: GraphRecord): void {
    if (rec.saveTimer != null) clearTimeout(rec.saveTimer);
    rec.saveTimer = setTimeout(() => {
        rec.saveTimer = null;
        fireSave(rec);
    }, DEBOUNCE_MS);
}

// ── Public API used by FlowCanvas ───────────────────────────────────────

/** Snapshot canvas state into the store. After Phase 2 nodes/edges
 *  live in the proxy directly (mutations via useLiveGraph), so callers
 *  pass only sidecar fields here. nodes/edges are kept on the type for
 *  the (rare) cold-path callers that still want a wholesale replace —
 *  in that case set `markDirty=true` to trigger a save.
 *
 *  Pass `markDirty: false` for snapshot-only updates that shouldn't
 *  schedule a save on their own (the `markGraphDirty` helper exists
 *  for the explicit save trigger). */
export function recordGraphSnapshot(
    workflowId: string,
    isSkill: boolean,
    snapshot: {
        nodes?: Node[];
        edges?: Edge[];
        interfaceGridState?: InterfaceGridState | null;
        variables?: Record<string, unknown>;
        displayMetadata?: DisplayMetadata | null;
    },
    markDirty: boolean = true,
): void {
    const rec = ensureRecord(workflowId, isSkill);
    rec.isSkill = isSkill;
    if (snapshot.nodes !== undefined) rec.nodes = snapshot.nodes;
    if (snapshot.edges !== undefined) rec.edges = snapshot.edges;
    if (snapshot.interfaceGridState !== undefined) {
        rec.interfaceGridState = snapshot.interfaceGridState;
    }
    if (snapshot.variables !== undefined) {
        rec.variables = snapshot.variables;
    }
    if (snapshot.displayMetadata !== undefined) {
        rec.displayMetadata = snapshot.displayMetadata;
    }
    if (markDirty) {
        rec.dirty = true;
        scheduleSave(rec);
    }
}

/** Mark a record dirty + schedule the debounced save. Used by the
 *  canvas effect that detects nodes/edges changes via Valtio
 *  reactivity — direct proxy writes don't run through
 *  recordGraphSnapshot, so the save schedule has to be triggered
 *  explicitly. */
export function markGraphDirty(workflowId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    rec.dirty = true;
    scheduleSave(rec);
}

export function recordDeletedNodes(workflowId: string, ids: string[]): void {
    if (ids.length === 0) return;
    const rec = graphRecords[workflowId];
    if (!rec) return;
    for (const id of ids) rec.deletedNodeIds.add(id);
    rec.dirty = true;
    scheduleSave(rec);
}

/** Tombstone a collaborator's delete (delivered over the collab channel)
 *  so a CAS-conflict rebase can't re-add the node while their save is
 *  still in flight. Never sent to the BE — their save owns the cleanup. */
export function recordRemoteDeletedNodes(workflowId: string, ids: string[]): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    for (const id of ids) rec.remoteDeletedNodeIds.add(id);
}

export function recordRemoteDeletedEdges(workflowId: string, ids: string[]): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    for (const id of ids) rec.remoteDeletedEdgeIds.add(id);
}

/** My own deletes whose save hasn't been acked yet. Load/reconnect merges
 *  must drop matching server nodes or a refetch resurrects the deletion. */
export function getPendingDeletedNodeIds(workflowId: string): ReadonlySet<string> {
    return graphRecords[workflowId]?.deletedNodeIds ?? EMPTY_ID_SET;
}

const EMPTY_ID_SET: ReadonlySet<string> = new Set();

export function setGraphLoaded(workflowId: string, loaded: boolean): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    rec.loaded = loaded;
}

/** Adopt the server's optimistic-concurrency token from a full workflow:get.
 *  A full load is also the re-baseline point for remote-delete tombstones:
 *  whatever the server holds now is truth, so stale remote tombstones from
 *  collaborator sessions that never saved must not keep hiding nodes. */
export function setGraphVersion(workflowId: string, version: number | null): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    if (typeof version === 'number') rec.graphVersion = version;
    rec.remoteDeletedNodeIds.clear();
    rec.remoteDeletedEdgeIds.clear();
    // The load takes every step whole from the server.
    rec.partialNodeIds = {};
}

/** A server write the canvas applied from the workflow's room (its builder events, then
 *  `workflow:graph_changed`) is the server's state: when the canvas was on the version the write was made on
 *  (`base`), its CAS base moves to the version the write left, so its next save carries the write instead of
 *  conflicting and rebasing over it. On any other base the canvas missed a write (one the room never carried, or
 *  carried while it was away): it keeps its base, so its next save conflicts and rebases on what the server holds. */
export function adoptServerVersion(workflowId: string, base: number, version: number): void {
    const rec = graphRecords[workflowId];
    if (!rec || typeof base !== 'number' || typeof version !== 'number') return;
    if (rec.graphVersion === base) rec.graphVersion = version;
    // Made on a version the save on its way may be producing: judged when that save's ack lands.
    else if (rec.saveInFlight) rec.noticesSinceSend.push({ base, version });
}

/** The viewer may only read this workflow: the canvas never saves it. */
export function setGraphReadOnly(workflowId: string, readOnly: boolean): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    rec.readOnly = readOnly;
}

export function isGraphReadOnly(workflowId: string): boolean {
    return graphRecords[workflowId]?.readOnly ?? false;
}

/** The canvas holds this step only in part (the room held some of it back) until it's read whole
 *  (`takeServerStep`), a full read takes it or a load does: it can't be edited meanwhile, and its saves keep the
 *  step's settings as stored, the closing tab's last one included. */
export function markStepPartial(workflowId: string, nodeId: string): void {
    const rec = graphRecords[workflowId];
    if (rec) rec.partialNodeIds[nodeId] = true;
}

export function isStepPartial(workflowId: string | undefined, nodeId: string | undefined): boolean {
    return !!(workflowId && nodeId && graphRecords[workflowId]?.partialNodeIds[nodeId]);
}

/** The step is held in part, for a component (its panel shows it loading). */
export function useStepPartial(workflowId: string | undefined, nodeId: string | undefined): boolean {
    const records = useSnapshot(graphRecords);
    return !!(workflowId && nodeId && records[workflowId]?.partialNodeIds[nodeId]);
}

/** A step read whole from the server (`workflow:node:get_config`'s settings, which the canvas applied): no longer
 *  partial, and the server's state in the base. */
export function takeServerStep(workflowId: string, nodeId: string, config: Record<string, unknown>): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    delete rec.partialNodeIds[nodeId];
    noteServerChange(rec, 'node_updated', { nodeId, config });
}

/** The server's graph as a load read it: the canvas's base from here on. */
export function setServerBase(workflowId: string, nodes: Node[], edges: Edge[]): void {
    const rec = graphRecords[workflowId];
    if (rec) rec.base = baseOf(nodes, edges);
}

/** A written change's builder event (the graph service's room) moves the base as it moves the canvas. */
function applyToBase(workflowId: string, eventType: string, data: Record<string, unknown>): void {
    const rec = graphRecords[workflowId];
    if (rec && GRAPH_EVENT_TYPES.has(eventType)) noteServerChange(rec, eventType, data);
}

/** A server change the canvas took: into its base, kept for the ack of a save on its way (`heardSinceSend`), and
 *  told to whoever follows them (the canvas's undo history). */
function noteServerChange(rec: GraphRecord, eventType: string, data: Record<string, unknown>): void {
    if (rec.base) rec.base = baseAfter(rec.base, eventType, data);
    rec.heardSinceSend?.push({ eventType, data });
    for (const listener of serverChangeListeners) listener(rec.workflowId, { eventType, data });
}

/** A server change the canvas took (`change`), or null when it took the server's graph wholesale (a conflict's
 *  merge, a re-read). */
export type ServerChangeListener = (
    workflowId: string,
    change: { eventType: string; data: Record<string, unknown> } | null,
) => void;

const serverChangeListeners = new Set<ServerChangeListener>();

export function onServerChange(listener: ServerChangeListener): () => void {
    serverChangeListeners.add(listener);
    return () => {
        serverChangeListeners.delete(listener);
    };
}

function baseAfter(base: GraphBase, eventType: string, data: Record<string, unknown>): GraphBase {
    const nodes = [...base.nodes.values()].map((json) => rawNodeToCanvasNode(JSON.parse(json)));
    const edges = [...base.edges.values()].map((json) => JSON.parse(json) as Edge);
    return baseOf(serverNodesAfter(nodes, eventType, data), serverEdgesAfter(edges, eventType, data));
}

/** Read the whole workflow again and fold it in as a conflict's answer is (`rebaseFromServer`): what a canvas
 *  falls back to when a step can't be read whole, never a save of its partial copy. False when the read failed
 *  (the step stays partial: uneditable, and kept as stored by every save). */
export async function reloadFromServer(workflowId: string): Promise<boolean> {
    const rec = graphRecords[workflowId];
    if (!rec) return false;
    try {
        const resp = (await sendEventAsync({ event_name: 'workflow:get', workflow_id: workflowId } as never)) as {
            workflow?: { workflow_data?: { nodes?: unknown[]; edges?: unknown[] }; graph_version?: number };
        } | null;
        const workflow = resp?.workflow;
        if (!workflow?.workflow_data) return false;
        rebaseFromServer(rec, workflow.workflow_data, workflow.graph_version ?? null);
        rec.dirty = true;
        scheduleSave(rec);
        return true;
    } catch (e) {
        console.error(`[liveGraphStore] reading ${workflowId} again failed:`, e);
        return false;
    }
}

/** Snapshot the record's current content as the no-op-save baseline. Called
 *  after the workflow:get merges land so freshly-loaded content doesn't read
 *  as "dirty" and fire a pointless save (DB write + updated_at churn) on
 *  every open. */
export function seedSaveBaseline(workflowId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    try {
        rec.lastSavedPayloadJson = JSON.stringify(buildPayload(rec).savePayload);
        rec.base = baseOf(rec.nodes, rec.edges);
    } catch {
        /* non-serializable state — leave unseeded; the save fires normally */
    }
}

export function setCanvasMounted(workflowId: string, isSkill: boolean, mounted: boolean): void {
    // Use ensureRecord so the flag is in place even before the first
    // recordGraphSnapshot fires (the canvas's mount effect runs before
    // its snapshot effect). Mid-session unmounts find an existing record.
    const rec = ensureRecord(workflowId, isSkill);
    rec.canvasMounted = mounted;
    // Dirty state stranded while unmounted (a save retry / conflict-rebase
    // ack that landed after unmount can't fire — canSave gates on mounted):
    // pick it up as soon as the canvas is back.
    if (mounted && rec.dirty) scheduleSave(rec);
}

export function isCanvasMountedFor(workflowId: string): boolean {
    return graphRecords[workflowId]?.canvasMounted ?? false;
}

/** True when the store already holds live graph state for this workflow —
 *  a workflow:get completed this session, or mutations (agentic/remote)
 *  landed while the canvas was unmounted. The proxy outlives canvas
 *  mounts, so in this state it is always at least as fresh as the
 *  IndexedDB instant-render snapshot; applying that snapshot over it
 *  would resurrect nodes deleted since the last workflow:get. */
export function hasLiveGraphState(workflowId: string): boolean {
    const rec = graphRecords[workflowId];
    if (!rec) return false;
    return rec.loaded || rec.nodes.length > 0 || rec.edges.length > 0;
}

// ── Remote-edit application (used by presenceManager when the canvas
//    isn't mounted). When the canvas IS mounted, useCollaborativePresence
//    routes remote events through setNodes/setEdges, which then flow
//    into this store via the canvas's recordGraphSnapshot effect — so
//    these helpers are background-only and presenceManager skips them
//    while canvasMounted is true. ────────────────────────────────────

export function applyRemoteNodeAdd(workflowId: string, nodeData: unknown): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    const node = nodeData as XYFlowNode;
    if (!node?.id) return;
    if (rec.nodes.some(n => n.id === node.id)) return;
    rec.nodes = [...rec.nodes, node];
    // Don't mark dirty — remote edits are already persisted by the
    // origin side. We only need to keep the FE's view of the graph
    // current; firing our own `workflow:update` on top would be
    // redundant and risk a clobber if our snapshot lags theirs.
}

export function applyRemoteNodeUpdate(workflowId: string, nodeId: string, data: Record<string, unknown>): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    const idx = rec.nodes.findIndex(n => n.id === nodeId);
    if (idx === -1) return;
    rec.nodes = [
        ...rec.nodes.slice(0, idx),
        { ...rec.nodes[idx], data: { ...rec.nodes[idx].data, ...data } },
        ...rec.nodes.slice(idx + 1),
    ];
}

export function applyRemoteNodeRemove(workflowId: string, nodeId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    // Tombstone before the existence check: the removal may race a snapshot
    // that hasn't listed the node yet, and the rebase guard must still hold.
    rec.remoteDeletedNodeIds.add(nodeId);
    if (!rec.nodes.some(n => n.id === nodeId)) return;
    rec.nodes = rec.nodes.filter(n => n.id !== nodeId);
    rec.edges = rec.edges.filter(e => e.source !== nodeId && e.target !== nodeId);
}

export function applyRemoteEdgeAdd(workflowId: string, edgeData: unknown): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    const edge = edgeData as XYFlowEdge;
    if (!edge?.id) return;
    if (rec.edges.some(e => e.id === edge.id)) return;
    rec.edges = [...rec.edges, edge];
}

export function applyRemoteEdgeRemove(workflowId: string, edgeId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    rec.remoteDeletedEdgeIds.add(edgeId);
    if (!rec.edges.some(e => e.id === edgeId)) return;
    rec.edges = rec.edges.filter(e => e.id !== edgeId);
}

// ── Agentic graph_event application ────────────────────────────────────
//
// `active_gen:graph_event` arrives whenever the brain mutates the graph
// during a builder run. activeGenStore appends each event to the gen's
// `events` array (drives the chat's inline node tags) and forwards each
// one here so the canvas surfaces the mutation even when it was
// unmounted (different tab, just opened workflow, snapshot replay…).
//
// Two payload shapes arrive on this channel:
//   * Mutation events (node_added, edge_added) carry the full graph
//     state under a nested key: `event.node = {id, type, config, …}` or
//     `event.edge = {id, sourceId, targetId, …}`. These come straight
//     from NodeState.to_dict / EdgeState.to_dict.
//   * Update events (node_updated, node_processing_start, node_removed,
//     edge_removed) keep nodeId / edgeId at the top level. node_updated
//     additionally carries a `config` dict for plain fields, but lifts
//     metadata (credentialIds, disabled, label, …) OUT of config to the
//     top level of the payload — see _build_node_update_data.
//
// rawConfigToPayload merges nested config + lifted metadata back into
// the right slots on the node data model. Without that re-routing,
// credentialIds set via <set_credentials> during a canvas-unmounted turn
// would never reach data.credentialIds, the autosave snapshot would
// persist the workflow without them, and the next session would load
// from the DB with no credentials → `run_node` fails.

interface AgenticGraphEvent {
    type?: string;
    // Flat shape (node_updated, node_removed, processing/start, edge_removed)
    nodeId?: string;
    nodeType?: string;
    nodeLabel?: string;
    edgeId?: string;
    sourceId?: string;
    targetId?: string;
    status?: string;
    operation?: string | null;
    config?: Record<string, unknown>;
    credentialIds?: Record<string, string>;
    disabled?: boolean;
    mockedOutput?: unknown;
    goal?: string;
    operationReason?: string | null;
    userFields?: string[];
    // Nested shape (node_added, edge_added — from NodeState/EdgeState.to_dict)
    node?: Record<string, unknown>;
    edge?: Record<string, unknown>;
}

/** Build a NodeUpdatePayload from an event that may carry config as a
 *  flat blob with credentialIds at top-level OR as a nested config dict.
 *  Matches the shape useCanvasWorkflowEdit.handleEditEvent merges. */
function payloadFromAgenticEvent(event: AgenticGraphEvent) {
    const cfg = (event.config ?? {}) as Record<string, unknown>;
    // Pass the flat-blob shape through rawConfigToPayload so credentialIds
    // (nested or top-level) get routed to data.credentialIds, plain config
    // fields land at data.config, etc.
    const fromConfig = rawConfigToPayload(cfg);
    return {
        config: fromConfig.config,
        // Top-level metadata (lifted by _build_node_update_data) wins over
        // whatever rawConfigToPayload found in config — the BE puts the
        // authoritative value at the top level.
        ...(event.operation !== undefined ? { operation: event.operation } : {}),
        ...(event.operationReason !== undefined ? { operationReason: event.operationReason } : {}),
        ...(event.goal !== undefined ? { goal: event.goal } : {}),
        ...(event.nodeLabel !== undefined ? { label: event.nodeLabel } : {}),
        ...(event.userFields !== undefined ? { userFields: event.userFields } : {}),
        credentialIds: event.credentialIds ?? fromConfig.credentialIds,
        ...(event.disabled !== undefined ? { disabled: event.disabled } : {}),
        ...(event.mockedOutput !== undefined ? { mockedOutput: event.mockedOutput } : {}),
    };
}

export function applyAgenticGraphEvent(
    workflowId: string,
    event: AgenticGraphEvent,
): void {
    // Seed a record on demand. Agentic events can land before the
    // canvas has ever mounted (user is on a different tab, or the
    // gen started before the workflow was opened). Without this,
    // events would be dropped on the canvas-side mirror and only
    // surface after a full workflow re-fetch on remount.
    const rec = ensureRecord(workflowId, /* isSkill */ false);
    switch (event.type) {
        case 'node_added': {
            // Mutation events carry the full node under event.node
            // (NodeState.to_dict); fall back to flat fields for any
            // legacy emitters that send the chat-summary shape.
            const nested = event.node ?? {};
            const id = (nested.id as string | undefined) ?? event.nodeId;
            const type = (nested.type as string | undefined) ?? event.nodeType;
            if (!id || !type) return;
            rec.remoteDeletedNodeIds.delete(id); // a re-add is the newer intent
            if (rec.nodes.some(n => n.id === id)) return;
            const animState = event.status === 'completed' ? 'complete' : 'adding';
            // Prefer the BE-authored position if present; otherwise a
            // staggered grid so synthesized nodes don't pile on top of
            // each other.
            const idx = rec.nodes.length;
            const position = (nested.position as { x: number; y: number } | undefined) ?? {
                x: 100 + (idx % 4) * 280,
                y: 100 + Math.floor(idx / 4) * 220,
            };
            // The raw config blob from NodeState.to_dict carries the
            // flat shape (operation/goal/label/credentialIds spread at
            // top level + config dict). createWorkflowNode → applyNodeUpdate
            // routes each field via rawConfigToPayload, so credentialIds
            // and labels land at data.* (not data.config.*).
            const rawConfig: Record<string, unknown> = {
                label: (nested.label as string | undefined) ?? event.nodeLabel ?? id,
                ...(nested.operation !== undefined ? { operation: nested.operation } : {}),
                ...(nested.goal !== undefined ? { goal: nested.goal } : {}),
                ...(nested.userFields !== undefined ? { userFields: nested.userFields } : {}),
                ...(nested.operationReason !== undefined ? { operationReason: nested.operationReason } : {}),
                ...(nested.config && typeof nested.config === 'object'
                    ? (nested.config as Record<string, unknown>)
                    : {}),
            };
            const node = createWorkflowNode(
                id,
                type,
                position,
                rawConfig,
                { mcpAnimationState: animState },
            );
            rec.nodes = [...rec.nodes, node];
            break;
        }
        case 'node_updated': {
            const id = event.nodeId;
            if (!id) return;
            const i = rec.nodes.findIndex(n => n.id === id);
            if (i === -1) return;
            const animState = event.status === 'in_progress' ? 'editing' : 'complete';
            const payload = payloadFromAgenticEvent(event);
            // Always apply when the event carries real config / metadata
            // (credentialIds, disabled, config fields, etc.). Skip only
            // the pure animation re-assert frames where every payload key
            // is empty AND the animState already matches — those happen
            // many times per gen and would otherwise allocate a fresh
            // nodes array per frame.
            const current = rec.nodes[i];
            const currentAnim = (current.data as { mcpAnimationState?: string })?.mcpAnimationState;
            const hasMeaningfulPayload = Boolean(
                payload.operation ||
                payload.label ||
                payload.goal ||
                payload.credentialIds ||
                payload.disabled !== undefined ||
                payload.mockedOutput !== undefined ||
                payload.userFields !== undefined ||
                (payload.config && Object.keys(payload.config).length > 0),
            );
            if (currentAnim === animState && !hasMeaningfulPayload) {
                break;
            }
            const updated = applyNodeUpdate(current, {
                ...payload,
                extras: { mcpAnimationState: animState },
            });
            rec.nodes = [...rec.nodes.slice(0, i), updated, ...rec.nodes.slice(i + 1)];
            break;
        }
        case 'node_processing_start': {
            // BE signals that the brain is actively configuring this
            // node. Surface as `editing` so the canvas renders the
            // active-editing animation.
            const id = event.nodeId;
            if (!id) return;
            const i = rec.nodes.findIndex(n => n.id === id);
            if (i === -1) return;
            rec.nodes = [
                ...rec.nodes.slice(0, i),
                applyNodeUpdate(rec.nodes[i], { extras: { mcpAnimationState: 'editing' } }),
                ...rec.nodes.slice(i + 1),
            ];
            break;
        }
        case 'node_removed': {
            const id = event.nodeId;
            if (!id) return;
            // Tombstone first: the builder's persist of this removal runs
            // after its terminal frame, so our flush save can conflict
            // against a row that still holds the node.
            rec.remoteDeletedNodeIds.add(id);
            rec.nodes = rec.nodes.filter(n => n.id !== id);
            rec.edges = rec.edges.filter(e => e.source !== id && e.target !== id);
            break;
        }
        case 'edge_added': {
            // Same as node_added: mutation events nest under event.edge.
            const nested = event.edge ?? {};
            const id = (nested.id as string | undefined) ?? event.edgeId;
            // EdgeState.to_dict uses sourceId/targetId; the MCP bridge
            // normalizes to source/target — accept either.
            const source = (nested.sourceId as string | undefined)
                ?? (nested.source as string | undefined)
                ?? event.sourceId;
            const target = (nested.targetId as string | undefined)
                ?? (nested.target as string | undefined)
                ?? event.targetId;
            if (!id || !source || !target) return;
            rec.remoteDeletedEdgeIds.delete(id);
            if (rec.edges.some(e => e.id === id)) return;
            const sourceHandle = nested.sourceHandle as string | undefined;
            const targetHandle = nested.targetHandle as string | undefined;
            rec.edges = [
                ...rec.edges,
                {
                    id,
                    source,
                    target,
                    ...(sourceHandle ? { sourceHandle } : {}),
                    ...(targetHandle ? { targetHandle } : {}),
                } as Edge,
            ];
            break;
        }
        case 'edge_removed': {
            const id = event.edgeId;
            if (!id) return;
            rec.remoteDeletedEdgeIds.add(id);
            rec.edges = rec.edges.filter(e => e.id !== id);
            break;
        }
    }
}

/** Clear the editing/adding animation flag on every node for a
 *  workflow. Called when a gen ends (terminal or user-stop) so the
 *  canvas drops out of the active-edit glow even when the BE didn't
 *  emit final node_updated events for every node it was working on
 *  (which happens on user interruption — the brain is mid-config,
 *  no final per-node frame fires before the CancelScope trips). */
export function clearGraphAnimations(workflowId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    let mutated = false;
    const next = rec.nodes.map(n => {
        const anim = (n.data as { mcpAnimationState?: string } | undefined)?.mcpAnimationState;
        if (!anim || anim === 'complete') return n;
        mutated = true;
        return applyNodeUpdate(n, { extras: { mcpAnimationState: 'complete' } });
    });
    if (mutated) rec.nodes = next;
}

export function setGraphDragging(workflowId: string, dragging: boolean): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    rec.dragging = dragging;
    // On drag-end, run the deferred save if anything became dirty during
    // the drag (e.g. node-position commits).
    if (!dragging && rec.dirty) scheduleSave(rec);
}

/** Cancel pending debounce and save immediately. Used on gen-terminal
 *  and pagehide so nothing rides on the timer. */
export function flushGraphNow(workflowId: string): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    if (rec.saveTimer != null) {
        clearTimeout(rec.saveTimer);
        rec.saveTimer = null;
    }
    fireSave(rec);
}

/** Pagehide/beforeunload flush: fire-and-forget, no CAS (see fireSave). */
export function flushAllGraphsNow(): void {
    for (const rec of Object.values(graphRecords)) {
        if (rec.saveTimer != null) {
            clearTimeout(rec.saveTimer);
            rec.saveTimer = null;
        }
        fireSave(rec, { unconditional: true });
    }
}

// ── Cross-store wiring ──────────────────────────────────────────────────

let _wired = false;

/** Install module-level listeners. Called eagerly on import below. */
function wire(): void {
    if (_wired) return;
    _wired = true;

    // When a gen terminates, force-flush the workflow it owned. This
    // gives the post-stream save a deterministic ordering w.r.t. the
    // user-driven debounce (no race between "agentic terminal saves at
    // T+10ms" and "manual debounce fires at T+800ms with stale data").
    //
    // The terminal frame doesn't carry workflow_id directly — look it up
    // from activeGenStore where it was stamped at active_gen:started.
    // Run synchronously *before* activeGenStore's terminal listener
    // evicts the gen by reading it out at this listener's call time;
    // listener order isn't guaranteed, so we tolerate the eviction by
    // also checking byWorkflow as a fallback.
    // A server write's notice in the workflow's room, after the builder events the canvas applied.
    onSocketEvent('workflow:graph_changed', (data) => {
        if (data?.workflow_id) adoptServerVersion(data.workflow_id, data.base_version, data.version);
    });
    // A written change's builder events move the canvas's base too; the builder's own stream (not yet written)
    // doesn't.
    onSocketEvent('mcp:builder_event' as never, ((event: {
        workflow_id?: string; event_type?: string; data?: Record<string, unknown>; committed?: boolean;
    }) => {
        if (event?.committed && event.workflow_id && event.event_type) {
            applyToBase(event.workflow_id, event.event_type, event.data ?? {});
        }
    }) as never);

    onSocketEvent('active_gen:terminal' as never, ((data: { gen_id?: string }) => {
        const gen_id = data?.gen_id;
        if (!gen_id) return;
        const wfId = activeGenStore.gens[gen_id]?.workflow_id;
        if (wfId) flushGraphNow(wfId);
    }) as never);

    // Browser nav-away (close tab, back-forward navigation that triggers
    // page hide). Fire any dirty saves so they don't disappear with the
    // tab. The Remix in-tab navigation case is covered by recordSnapshot
    // already keeping the store warm — there's no unmount cleanup to
    // race against because the store outlives the canvas mount.
    if (typeof window !== 'undefined') {
        const flushOnLeave = () => flushAllGraphsNow();
        window.addEventListener('pagehide', flushOnLeave);
        window.addEventListener('beforeunload', flushOnLeave);
    }
}

wire();
