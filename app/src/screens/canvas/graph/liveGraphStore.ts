// Module-level shadow of the workflow graph keyed by workflow id, so
// persistence outlives the canvas's mount/unmount. The canvas writes a full
// snapshot here on every change; the store owns the autosave debounce,
// the flush when another writer is done, and the pagehide beacon.
//
// Why this exists: the canvas used to autosave from its own React state.
// Quick navigation away (in-tab) ran the unmount cleanup with a stale
// snapshot, dropping unsaved edits. Hoisting the save trigger above the
// mount lifecycle eliminates that race without lifting the source of truth.
//
// What stays in the canvas: read state, presence broadcasts, mutation
// pipelines (setNodes/setEdges), drag/load lifecycle. The canvas just
// pushes a snapshot to the store on changes and tells it about lifecycle
// transitions. How a record is saved and read again beyond /v1 is the
// `canvas.graph.saves` slot's (saves.ts); a host following a workflow's
// room hands the store what it hears (adoptServerVersion, applyToBase).

import { proxy, subscribe, useSnapshot } from 'valtio';
import type { Node, Edge, Node as XYFlowNode, Edge as XYFlowEdge } from '@xyflow/react';
import { Conflict, Workflow, type EditOptions, type NoClick, type WorkflowEdit } from 'noclick';
import { valtioCache } from '@/lib/indexeddb';
import { standing } from '@/slots';
import { serializeNodeForSave, serializeEdgeForSave, createWorkflowNode, applyNodeUpdate, mergeServerNodes, rawConfigToPayload } from '@/screens/canvas/applyNodeUpdate';
import {
    baseAfterGroups,
    canvasEditGroups,
    intoBatches,
    type CanvasGraph,
    type GraphBase,
    type OpGroup,
} from './canvasEdits';
import { GRAPH_SAVES } from '../slots';
import type { CanvasSaveTransport, ServerGraphData, WholeGraphAnswer, WholeGraphSave } from './saves';
import { GRAPH_EVENT_TYPES, serverEdgesAfter, serverNodesAfter } from './serverGraphEvents';

export type { CanvasSaveTransport } from './saves';

interface InterfaceGridState {
    layout: ReadonlyArray<unknown>;
    tabOrder?: ReadonlyArray<unknown>;
}

type DisplayMetadata = object;

interface GraphRecord {
    workflowId: string;
    isSkill: boolean;
    nodes: Node[];
    edges: Edge[];
    interfaceGridState: InterfaceGridState | null;
    variables: Record<string, unknown>;
    // Its read withheld the graph's variables' values (/v1 never sends one): it holds no copy of them to save, and the
    // runtime keeps them.
    variablesWithheld: boolean;
    displayMetadata: DisplayMetadata | null;
    deletedNodeIds: Set<string>;
    // Deletes another writer streamed to us (a collaborator over the collab
    // channel, the AI builder over its event stream) whose own persist may
    // not have landed yet. Used ONLY as rebase tombstones: a CAS conflict
    // answers with the row as it stands, and without these a node the
    // builder just removed reads as "server-only" and comes straight back
    // (2026-09-22). Full loads re-baseline and clear both.
    remoteDeletedNodeIds: Set<string>;
    remoteDeletedEdgeIds: Set<string>;

    // Lifecycle flags. Saves are suppressed unless `loaded` is true and
    // `dragging` is false. Whether another writer holds the graph is asked
    // of the `canvas.graph.saves` slot, so it needs no per-record mirror.
    //
    // canvasMounted: tracks whether the canvas is actively pushing
    // snapshots into this record. When false, the store's snapshot is
    // stale (agentic node_added events go through the canvas's setNodes
    // pipeline, not through the store directly), so we must not fire
    // saves from it — they would clobber the server's authoritative copy.
    loaded: boolean;
    dragging: boolean;
    canvasMounted: boolean;
    // The viewer can only read this workflow: it never saves.
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

    // How this record saves (decided at its first save, never changed after: one path per session).
    transport: CanvasSaveTransport | null;

    // Save coordination. graphVersion is the server's optimistic-concurrency
    // token from the last load / save ack (null = unknown → save
    // unconditionally). One save in flight at a time; dirty-set-during-flight
    // chains the next save off the ack.
    dirty: boolean;
    saveTimer: ReturnType<typeof setTimeout> | null;
    graphVersion: number | null;
    saveInFlight: boolean;
    saveFailures: number;
    // JSON of the last acked save payload (seeded from the load). A
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
        variablesWithheld: false,
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
        transport: null,
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

/** Build the save payload from the record's current snapshot: the graph as a save sends it, and the steps it
 *  removed and holds in part. */
function buildPayload(rec: GraphRecord): {
    deletedNodeIds: string[];
    partialNodeIds: string[];
    savePayload: Record<string, unknown>;
} {
    const deletedNodeIds = Array.from(rec.deletedNodeIds);
    // Drop any malformed entries (missing id) before serialization.
    // These shouldn't exist — createWorkflowNode now throws on missing
    // id, and the agentic event handlers bail — but if one slips
    // through (or a stale state from before those guards landed), we
    // don't want to ship it to the server, where id-keyed paths choke.
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
    if (Object.keys(rec.variables).length > 0 && !rec.variablesWithheld) {
        savePayload.variables = rec.variables;
    }
    return { deletedNodeIds, partialNodeIds: Object.keys(rec.partialNodeIds), savePayload };
}

/** The whole graph as a host's own save takes it. A skill's embedded workflow has no version to save on. */
function wholeSave(
    rec: GraphRecord,
    payload: ReturnType<typeof buildPayload>,
    changes?: WholeGraphSave['changes'],
): WholeGraphSave {
    return {
        workflowId: rec.workflowId,
        isSkill: rec.isSkill,
        graph: payload.savePayload,
        displayMetadata: rec.displayMetadata,
        deletedNodeIds: payload.deletedNodeIds,
        partialNodeIds: payload.partialNodeIds,
        ifVersion: rec.isSkill ? null : rec.graphVersion,
        ...(changes ? { changes } : {}),
    };
}

type SavedGraph = { nodes?: Array<{ id?: string }>; edges?: Array<{ id?: string }>; interface?: unknown };

const nodeJson = (node: Node) => JSON.stringify(serializeNodeForSave(node));
const edgeJson = (edge: Edge) => JSON.stringify(serializeEdgeForSave(edge));
const layoutJson = (layout: unknown) => (layout == null ? null : JSON.stringify(layout));

/** `layout`: the Interface tab's, as the base knows it (left out, the base doesn't know it). */
function baseOf(nodes: Node[], edges: Edge[], layout?: string | null): GraphBase {
    return {
        nodes: new Map(nodes.filter((n) => n?.id).map((n) => [n.id, nodeJson(n)])),
        edges: new Map(edges.filter((e) => e?.id).map((e) => [e.id, edgeJson(e)])),
        interface: layout,
    };
}

/** The base a save sets once acked: what it sent is what the server holds. */
function baseOfSaved(saved: SavedGraph): GraphBase {
    const byId = (items: Array<{ id?: string }> | undefined) =>
        new Map((items ?? []).filter((x) => x?.id).map((x) => [x.id as string, JSON.stringify(x)]));
    return { nodes: byId(saved.nodes), edges: byId(saved.edges), interface: layoutJson(saved.interface) };
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

/** Stored-shape snapshot of the live canvas graph, for the builder to read on a
 *  resume (answering its question). The steps it just added may not have
 *  reached the debounced auto-save yet, so the resume would otherwise read a
 *  stale/empty graph and add them again.
 *
 *  Returns null when the store isn't a trustworthy source (canvas unmounted or
 *  not yet loaded — agentic mutations bypass the store then), so the backend
 *  falls back to its own read. Shape mirrors the auto-save payload, which the
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
    if (standing(GRAPH_SAVES).paused()) return false;
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
    // What a /v1 read held back of its settings, which the form shows as saved.
    const withheld = Array.isArray(raw.withheld) && raw.withheld.length ? { withheld: raw.withheld } : {};
    const node = createWorkflowNode(
        raw.id as string,
        raw.type as string,
        (raw.position as { x: number; y: number }) ?? { x: 0, y: 0 },
        (raw.config as Record<string, unknown>) ?? {},
        withheld,
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
    serverData: ServerGraphData | null | undefined,
    serverVersion: number | null | undefined,
): void {
    if (typeof serverVersion === 'number') rec.graphVersion = serverVersion;
    // A /v1 answer withholds each secret (`withheld`: its paths by step).
    const withheld = withheldPaths(serverData?.withheld);
    const serverNodes = new Map(
        ((serverData?.nodes ?? []) as Record<string, unknown>[])
            .filter((raw) => typeof raw?.id === 'string' && raw.type)
            .map((raw) => [raw.id as string, rawNodeToCanvasNode({ withheld: withheld[raw.id as string], ...raw })] as const),
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
    // A step the server holds as the canvas does but for what it withheld is the canvas's copy, secrets and all: it
    // stays, and stays the base, so no save sends one back.
    const asHeld = new Set<string>();

    const nodes: Node[] = [];
    for (const node of rec.nodes) {
        const server = serverNodes.get(node.id);
        if (server && withheld[node.id] && heldButWithheld(node, server, withheld[node.id])) {
            nodes.push(node);
            asHeld.add(node.id);
            delete rec.partialNodeIds[node.id];
        } else if (server && !changedHere(rec, node)) {
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
    rec.base = baseOf([...serverNodes.values()], serverEdges, rec.base?.interface);
    for (const node of nodes) if (asHeld.has(node.id)) rec.base.nodes.set(node.id, nodeJson(node));
    for (const listener of serverChangeListeners) listener(rec.workflowId, null);
}

function withheldPaths(value: unknown): Record<string, string[]> {
    if (!value || typeof value !== 'object') return {};
    return Object.fromEntries(
        Object.entries(value as Record<string, unknown>).filter(
            (entry): entry is [string, string[]] => Array.isArray(entry[1]) && entry[1].every((p) => typeof p === 'string'),
        ),
    );
}

/** `path` (`api_key`, `headers[0].value`, `[0].token`) as the keys and indices it walks. */
function pathSteps(path: string): Array<string | number> {
    return Array.from(path.matchAll(/([^.[\]]+)|\[(\d+)\]/g), (m) => (m[2] !== undefined ? Number(m[2]) : m[1]));
}

/** `value` without what `paths` name (a key of an object, the last step of each). */
function withoutPaths(value: unknown, paths: string[]): unknown {
    const copy = JSON.parse(JSON.stringify(value ?? null));
    for (const path of paths) {
        const steps = pathSteps(path);
        const last = steps.pop();
        let parent: unknown = copy;
        for (const step of steps) parent = (parent as Record<string | number, unknown> | null)?.[step];
        if (parent && typeof parent === 'object' && typeof last === 'string') delete (parent as Record<string, unknown>)[last];
    }
    return copy;
}

/** `value` as JSON with every object's keys in order: the server's copy comes back from JSONB, which orders them its
 *  own way. */
function canonicalJson(value: unknown): string {
    return JSON.stringify(value, (_key, v: unknown) => (v && typeof v === 'object' && !Array.isArray(v)
        ? Object.fromEntries(Object.entries(v as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
        : v));
}

/** The canvas's step is the server's, but for the secrets the server's copy withholds (`paths`). */
function heldButWithheld(node: Node, server: Node, paths: string[]): boolean {
    const mine = serializeNodeForSave(node);
    return canonicalJson({ ...mine, config: withoutPaths(mine.config, paths) }) === canonicalJson(serializeNodeForSave(server));
}

// ── How the canvas saves ────────────────────────────────────────────────

/** This tab's name for itself on its /v1 edits (`origin`): what the workflow's room hears of its own writes names it,
 *  so it never applies them a second time (its save's answer has them already). */
export const CANVAS_ORIGIN = `canvas-${crypto.randomUUID()}`;

let editsClient: NoClick | null = null;

/** The client canvas saves and reads go through on /v1 (the app's own; a host's, signed by its session). */
export function setCanvasEditsClient(client: NoClick | null): void {
    editsClient = client;
}

/** How the record saves, decided at its first save and kept (`canvas.graph.saves`). */
function saveTransport(rec: GraphRecord): CanvasSaveTransport {
    if (rec.transport === null) {
        rec.transport = standing(GRAPH_SAVES).transportFor({ workflowId: rec.workflowId, isSkill: rec.isSkill });
    }
    return rec.transport;
}

/** The way a record saves (null before its first save). */
export function canvasSaveTransportOf(workflowId: string): CanvasSaveTransport | null {
    return graphRecords[workflowId]?.transport ?? null;
}

/** A save that didn't land: dirty again, retried on the debounce until it has failed too often in a row. */
function saveFailed(rec: GraphRecord, why: string): void {
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
}

/** After a save landed: its delete tombstones go, and the instant-render cache mirrors what the server holds now
 *  (the canvas otherwise only writes it on a load, so after a delete the next mount would restore, and eventually
 *  re-save, the deleted steps). */
function saveLanded(rec: GraphRecord, deletedNodeIds: string[], savePayload: Record<string, unknown>): void {
    rec.saveFailures = 0;
    for (const id of deletedNodeIds) rec.deletedNodeIds.delete(id);
    try {
        // JSON round-trip strips valtio proxies for structured clone.
        void valtioCache.set(`workflow-canvas:${rec.workflowId}`, JSON.parse(JSON.stringify(savePayload)));
    } catch (e) {
        console.warn('[liveGraphStore] cache mirror skipped:', e);
    }
}

/** Takes the version a save's answer names, unless a server write's notice moved the record past it while the save
 *  was on its way (false: it never moves back); the notices of writes made on the version it produced are taken
 *  then, in order. */
function adoptSavedVersion(
    rec: GraphRecord,
    newVersion: number | undefined,
    notices: Array<{ base: number; version: number }>,
): boolean {
    if (typeof newVersion === 'number' && rec.graphVersion != null && newVersion < rec.graphVersion) return false;
    if (typeof newVersion === 'number') {
        rec.graphVersion = newVersion;
        for (const notice of notices) {
            if (notice.base === rec.graphVersion) rec.graphVersion = notice.version;
        }
    }
    return true;
}

// The browser drops a keepalive request whose body is over 64 KB: a closing tab's bigger last save goes as a plain one.
const KEEPALIVE_BODY_LIMIT = 60_000;

/** One batch of a canvas's edits through /v1, on `ifVersion` when given (a closing tab's flush has none). */
async function sendEdits(
    client: NoClick,
    workflowId: string,
    groups: OpGroup[],
    options: { ifVersion?: number | null; closing?: boolean },
): Promise<WorkflowEdit | null> {
    const edit: EditOptions = {
        source: 'canvas',
        origin: CANVAS_ORIGIN,
        ...(options.ifVersion != null ? { ifVersion: options.ifVersion } : {}),
    };
    // The batch is sent once its function has queued it, so its size decides the options it goes with.
    return await Workflow.fromId(workflowId, { client }).edit(edit, (batch) => {
        for (const g of groups) g.queue(batch);
        if (options.closing) edit.keepalive = JSON.stringify(batch.ops).length <= KEEPALIVE_BODY_LIMIT;
    });
}

/** What the canvas holds, as a /v1 edits diff reads it, and the steps no op may touch (held only in part). */
function canvasGraphOf(rec: GraphRecord, savePayload: Record<string, unknown>): { graph: CanvasGraph; skip: Set<string> } {
    return {
        graph: {
            nodes: savePayload.nodes as CanvasGraph['nodes'],
            edges: savePayload.edges as CanvasGraph['edges'],
            interface: rec.interfaceGridState,
        },
        skip: new Set(Object.keys(rec.partialNodeIds)),
    };
}

/** A save as /v1 edits: the ops that bring the server's copy as the canvas knows it (its base) to what the canvas
 *  holds, on the version it holds. A refusal for a stale version answers the workflow as it stands, which the canvas
 *  rebases on (`rebaseFromServer`) before saving again, as it does a whole-graph save's conflict. A closing tab's flush sends its
 *  own changes with no version, to land on the workflow as it stands: what it changed, never its copy of the rest. */
function fireEditsSave(rec: GraphRecord, closing: boolean): void {
    const { deletedNodeIds, savePayload } = buildPayload(rec);
    if (deletedNodeIds.length === 0 && JSON.stringify(savePayload) === rec.lastSavedPayloadJson) {
        rec.dirty = false;
        return;
    }
    const client = editsClient;
    if (closing) {
        rec.dirty = false;
        if (!client || !rec.base) {
            console.error(
                `[liveGraphStore] the closing tab couldn't save ${rec.workflowId}: ` +
                (client ? 'it never knew what the server holds' : 'no /v1 client for canvas saves'),
            );
            return;
        }
        const { graph, skip } = canvasGraphOf(rec, savePayload);
        // Sent at once: nothing runs once the page has gone, so nothing could wait for an answer.
        for (const groups of intoBatches(canvasEditGroups(rec.base, graph, skip))) {
            sendEdits(client, rec.workflowId, groups, { closing: true }).catch((e: unknown) => {
                console.error(`[liveGraphStore] the closing tab's save of ${rec.workflowId} failed:`, e);
            });
        }
        return;
    }
    if (rec.saveInFlight) return; // the save on its way chains the next
    if (!client) {
        saveFailed(rec, 'no /v1 client for canvas saves (setCanvasEditsClient)');
        return;
    }

    rec.saveInFlight = true;
    rec.dirty = false; // optimistic; failure paths re-set it
    let settled = false;
    // Watchdog: a save whose answer never arrives releases the in-flight latch. A write of its that lands after is a
    // newer version, which the next save meets as a conflict and rebases on.
    const watchdog = setTimeout(() => {
        if (!settle()) return;
        saveFailed(rec, 'answer timeout');
    }, SAVE_ACK_TIMEOUT_MS);
    const settle = () => {
        if (settled) return false;
        settled = true;
        clearTimeout(watchdog);
        rec.saveInFlight = false;
        return true;
    };

    const run = async (): Promise<void> => {
        if (!rec.base) await readServerGraph(rec);
        if (settled) return;
        // The canvas as it stands now (a read may have taken the server's copies in).
        const now = buildPayload(rec);
        const { graph, skip } = canvasGraphOf(rec, now.savePayload);
        for (const groups of intoBatches(canvasEditGroups(rec.base ?? baseOf([], []), graph, skip))) {
            const start = rec.base ?? baseOf([], []);
            rec.heardSinceSend = [];
            rec.noticesSinceSend = [];
            const edit = await sendEdits(client, rec.workflowId, groups, { ifVersion: rec.graphVersion });
            if (settled) return;
            const heard = rec.heardSinceSend ?? [];
            const notices = rec.noticesSinceSend;
            rec.heardSinceSend = null;
            rec.noticesSinceSend = [];
            if (adoptSavedVersion(rec, edit?.version, notices)) {
                // What it sent is what the server holds, with the written changes heard since on top.
                rec.base = heard.reduce(
                    (base, { eventType, data }) => baseAfter(base, eventType, data),
                    baseAfterGroups(start, groups),
                );
            }
            const moot = (edit?.results ?? []).filter((r) => r.gone || r.exists);
            if (moot.length) console.warn(`[liveGraphStore] ${rec.workflowId}: edits of what the server no longer holds:`, moot);
        }
        if (!settle()) return;
        rec.lastSavedPayloadJson = JSON.stringify(now.savePayload);
        saveLanded(rec, now.deletedNodeIds, now.savePayload);
        if (rec.dirty) scheduleSave(rec); // edits arrived during flight
    };

    run().catch((e: unknown) => {
        rec.heardSinceSend = null;
        rec.noticesSinceSend = [];
        if (!settle()) return;
        const graph = e instanceof Conflict ? e.details.graph : undefined;
        const version = e instanceof Conflict ? e.details.version : undefined;
        if (graph && typeof graph === 'object' && typeof version === 'number') {
            // Another writer (another tab or device, MCP, the builder, the coordinator) moved it on: fold theirs in
            // and save again on the version it's at.
            rebaseFromServer(rec, graph as ServerGraphData, version);
            rec.dirty = true;
            rec.saveFailures = 0;
            scheduleSave(rec);
            return;
        }
        console.warn(`[liveGraphStore] save rejected for ${rec.workflowId}:`, e);
        saveFailed(rec, e instanceof Error ? e.message : String(e));
    });
}

/** The server's graph read again, for a save that has no base to diff against (one whose load never set it). */
async function readServerGraph(rec: GraphRecord): Promise<void> {
    const read = await standing(GRAPH_SAVES).read(rec.workflowId, editsClient);
    if (!read.graph) throw new Error(read.error ?? `reading ${rec.workflowId} found nothing`);
    rebaseFromServer(rec, read.graph, read.version);
}

function fireSave(rec: GraphRecord, opts?: { unconditional?: boolean }): void {
    if (!canSave(rec) || !rec.dirty) return;
    if (saveTransport(rec) === 'edits') {
        fireEditsSave(rec, !!opts?.unconditional);
        return;
    }

    const host = standing(GRAPH_SAVES).socket;
    if (!host) {
        rec.dirty = false;
        console.error(`[liveGraphStore] ${rec.workflowId} saves whole through a host's own save, and there is none`);
        return;
    }

    // Pagehide flush: the page is dying, so no ack/rebase cycle is possible.
    // Send fire-and-forget, ignoring the in-flight latch (an in-flight save
    // predates the last edits and must not swallow them), on the version this
    // canvas last saw and naming what it changed since: a workflow that moved
    // on without this tab takes only its own changes, never its stale copy of
    // the rest.
    if (opts?.unconditional) {
        const payload = buildPayload(rec);
        if (
            payload.deletedNodeIds.length === 0 &&
            JSON.stringify(payload.savePayload) === rec.lastSavedPayloadJson
        ) {
            rec.dirty = false;
            return;
        }
        const versioned = !rec.isSkill && rec.graphVersion != null;
        host.close(wholeSave(rec, payload, versioned ? changesSinceBase(rec, payload.savePayload as SavedGraph) : undefined));
        rec.dirty = false;
        return;
    }

    if (rec.saveInFlight) return; // ack handler chains the next save
    const payload = buildPayload(rec);
    const { deletedNodeIds, savePayload } = payload;
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
    // CAS guard: the save carries the version this client last saw so a stale
    // snapshot loses cleanly server-side (conflict + rebase) instead of
    // clobbering a newer save. Version-less records (never loaded) save
    // unconditionally.
    const save = wholeSave(rec, payload);

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

    const onFailure = (why: string) => saveFailed(rec, why);

    const onAck = (resp: WholeGraphAnswer) => {
        if (!settle()) return;
        const heard = rec.heardSinceSend ?? [];
        const notices = rec.noticesSinceSend;
        rec.heardSinceSend = null;
        rec.noticesSinceSend = [];
        if ('conflict' in resp) {
            // Another writer (other tab/device, MCP, builder) bumped the
            // version. Fold their graph in and re-save under the new version.
            rebaseFromServer(rec, resp.graph, resp.version);
            rec.dirty = true;
            rec.saveFailures = 0;
            scheduleSave(rec);
            return;
        }
        if ('error' in resp) {
            console.warn(`[liveGraphStore] save rejected for ${rec.workflowId}:`, resp.error);
            onFailure(resp.error);
            return;
        }
        // Success: adopt the new version (a save acked after a server write moved the base on, its room notice
        // first, never moves it back), retire the acked tombstones and mirror what the server now holds.
        if (adoptSavedVersion(rec, resp.version, notices)) {
            rec.lastSavedPayloadJson = payloadJson;
            // What it sent is what the server holds, with the written changes heard since on top.
            rec.base = heard.reduce(
                (base, { eventType, data }) => baseAfter(base, eventType, data),
                baseOfSaved(savePayload as SavedGraph),
            );
        }
        saveLanded(rec, deletedNodeIds, savePayload);
        if (rec.dirty) scheduleSave(rec); // edits arrived during flight
    };

    try {
        cleanup = host.save(save, onAck);
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

// ── Public API used by the canvas ───────────────────────────────────────

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
 *  still in flight. Never sent to the server — their save owns the cleanup. */
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

/** Adopt the server's optimistic-concurrency token from a full load.
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

/** A server write the canvas applied from the workflow's room (its graph events, then the notice of the
 *  versions it was made on and left) is the server's state: when the canvas was on the version the write was made on
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

/** A step read whole from the server (its settings as stored, which the canvas applied): no longer partial, and the
 *  server's state in the base. */
export function takeServerStep(workflowId: string, nodeId: string, config: Record<string, unknown>): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    delete rec.partialNodeIds[nodeId];
    noteServerChange(rec, 'node_updated', { nodeId, config });
}

/** The server's graph as a load read it: the canvas's base from here on. */
export function setServerBase(workflowId: string, nodes: Node[], edges: Edge[]): void {
    const rec = graphRecords[workflowId];
    if (rec) rec.base = baseOf(nodes, edges, rec.base?.interface);
}

/** A written change's graph event (heard from the workflow's room: the change is stored) moves the base as it moves
 *  the canvas. A host following the room hands it each one, never one this tab's own save wrote (its origin). */
export function applyToBase(workflowId: string, eventType: string, data: Record<string, unknown>): void {
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
    return baseOf(serverNodesAfter(nodes, eventType, data), serverEdgesAfter(edges, eventType, data), base.interface);
}

/** Read the whole workflow again and fold it in as a conflict's answer is (`rebaseFromServer`): what a canvas
 *  falls back to when a step can't be read whole, never a save of its partial copy. False when the read failed
 *  (the step stays partial: uneditable, and kept as stored by every save). */
export async function reloadFromServer(workflowId: string): Promise<boolean> {
    const rec = graphRecords[workflowId];
    if (!rec) return false;
    try {
        const read = await standing(GRAPH_SAVES).read(workflowId, editsClient);
        if (!read.graph) return false;
        rebaseFromServer(rec, read.graph, read.version);
        rec.dirty = true;
        scheduleSave(rec);
        return true;
    } catch (e) {
        console.error(`[liveGraphStore] reading ${workflowId} again failed:`, e);
        return false;
    }
}

/** The server's graph as a load read it, in the canvas's shape. A kind the load carried no list of is left out, and
 *  what the canvas holds of it counts as loaded. */
export interface LoadedGraph {
    nodes?: Node[];
    edges?: Edge[];
}

/** What the server holds of `mine`, given what a load read (`theirs`): the canvas's copy of each item the load read
 *  (the load's merge took the server's), in the canvas's order, then the server's (`own`: in the canvas's form) of
 *  those the canvas holds no more. */
function asLoaded<M extends { id: string }, T extends { id: string }>(mine: M[], theirs: T[] | undefined, own: (theirs: T) => M): M[] {
    if (!theirs) return mine;
    const read = new Set(theirs.map((t) => t.id));
    const kept = mine.filter((m) => read.has(m.id));
    const held = new Set(kept.map((k) => k.id));
    return [...kept, ...theirs.filter((t) => !held.has(t.id)).map(own)];
}

/** Sets the no-op-save baseline and the per-step base once a load's merge has landed, so freshly-loaded content
 *  doesn't read as "dirty" and fire a pointless save (DB write + updated_at churn) on every open. Both are what the
 *  load read (`loaded`; without it the record is the load), never what the canvas holds after the merge: the merge
 *  keeps a step added while the load was out and leaves out one removed meanwhile, and taken for the server's, the
 *  first was never written and the second never removed (/v1 edits send only what differs from the base). What
 *  differs is the canvas's own unsaved work, and is saved. */
export function seedSaveBaseline(workflowId: string, loaded?: LoadedGraph): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    try {
        const { savePayload } = buildPayload(rec);
        const held = savePayload as { nodes: Array<{ id: string }>; edges: Array<{ id: string }> };
        rec.lastSavedPayloadJson = JSON.stringify({
            ...savePayload,
            nodes: asLoaded(held.nodes, loaded?.nodes, serializeNodeForSave),
            edges: asLoaded(held.edges, loaded?.edges, serializeEdgeForSave),
        });
        rec.base = baseOf(
            asLoaded(rec.nodes, loaded?.nodes, (node) => node),
            asLoaded(rec.edges, loaded?.edges, (edge) => edge),
            layoutJson(rec.interfaceGridState),
        );
        if (rec.lastSavedPayloadJson !== JSON.stringify(savePayload)) {
            rec.dirty = true;
            scheduleSave(rec);
        }
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
 *  a load completed this session, or mutations (agentic/remote)
 *  landed while the canvas was unmounted. The proxy outlives canvas
 *  mounts, so in this state it is always at least as fresh as the
 *  IndexedDB instant-render snapshot; applying that snapshot over it
 *  would resurrect nodes deleted since the last load. */
export function hasLiveGraphState(workflowId: string): boolean {
    const rec = graphRecords[workflowId];
    if (!rec) return false;
    return rec.loaded || rec.nodes.length > 0 || rec.edges.length > 0;
}

// ── Remote-edit application (used by a host's live presence when the
//    canvas isn't mounted). When the canvas IS mounted, presence routes
//    remote events through setNodes/setEdges, which then flow into this
//    store via the canvas's recordGraphSnapshot effect — so these helpers
//    are background-only and presence skips them while canvasMounted is
//    true. ────────────────────────────────────────────────────────────

export function applyRemoteNodeAdd(workflowId: string, nodeData: unknown): void {
    const rec = graphRecords[workflowId];
    if (!rec) return;
    const node = nodeData as XYFlowNode;
    if (!node?.id) return;
    if (rec.nodes.some(n => n.id === node.id)) return;
    rec.nodes = [...rec.nodes, node];
    // Don't mark dirty — remote edits are already persisted by the
    // origin side. We only need to keep the canvas's view of the graph
    // current; firing our own save on top would be redundant and risk a
    // clobber if our snapshot lags theirs.
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
// A builder run's graph events arrive whenever the builder changes the
// graph. A host following the run keeps each event (its chat shows them)
// and forwards each one here so the canvas surfaces the change even when
// it was unmounted (different tab, just opened workflow, snapshot replay…).
//
// Two payload shapes arrive on this channel:
//   * Mutation events (node_added, edge_added) carry the full graph
//     state under a nested key: `event.node = {id, type, config, …}` or
//     `event.edge = {id, sourceId, targetId, …}`: the builder's own
//     record of the step or connection.
//   * Update events (node_updated, node_processing_start, node_removed,
//     edge_removed) keep nodeId / edgeId at the top level. node_updated
//     additionally carries a `config` dict for plain fields, but lifts
//     metadata (credentialIds, disabled, label, …) OUT of config to the
//     top level of the payload.
//
// rawConfigToPayload merges nested config + lifted metadata back into
// the right slots on the node data model. Without that re-routing,
// credentialIds the builder set during a canvas-unmounted turn would
// never reach data.credentialIds, the autosave snapshot would persist the
// workflow without them, and the next session would load it with no
// credentials, so running the step fails.

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
    // Nested shape (node_added, edge_added — the builder's own record)
    node?: Record<string, unknown>;
    edge?: Record<string, unknown>;
}

/** Build a NodeUpdatePayload from an event that may carry config as a
 *  flat blob with credentialIds at top-level OR as a nested config dict.
 *  Matches the shape the canvas merges a builder's edit with. */
function payloadFromAgenticEvent(event: AgenticGraphEvent) {
    const cfg = (event.config ?? {}) as Record<string, unknown>;
    // Pass the flat-blob shape through rawConfigToPayload so credentialIds
    // (nested or top-level) get routed to data.credentialIds, plain config
    // fields land at data.config, etc.
    const fromConfig = rawConfigToPayload(cfg);
    return {
        config: fromConfig.config,
        // Top-level metadata (lifted out of config by the server) wins over
        // whatever rawConfigToPayload found in config — the server puts the
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
            // (the builder's own record); fall back to flat fields for any
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
            // The builder's raw config blob carries the
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
            // The server signals that the builder is actively configuring this
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
 *  workflow. Called when a builder run ends (finished or stopped) so the
 *  canvas drops out of the active-edit glow even when the server didn't
 *  emit final node_updated events for every node it was working on
 *  (which happens on user interruption — the builder is mid-config,
 *  and no final per-step event fires before it stops). */
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

/** Saves what's pending now and resolves once it has landed (or can't: the canvas may not save, or its saves keep
 *  failing), so a read of the stored workflow sees what the canvas holds. /v1's reads of a step's choices and values
 *  read the stored step. */
export function whenGraphSaved(workflowId: string): Promise<void> {
    const rec = graphRecords[workflowId];
    if (!rec) return Promise.resolve();
    const settled = () =>
        !rec.saveInFlight &&
        rec.saveTimer == null &&
        (!rec.dirty || !canSave(rec) || rec.saveFailures > MAX_CONSECUTIVE_SAVE_FAILURES);
    flushGraphNow(workflowId);
    if (settled()) return Promise.resolve();
    return new Promise((resolve) => {
        const stop = subscribe(rec, () => {
            // Edits that landed while a save was on its way go now, not after the debounce.
            if (!rec.saveInFlight && rec.saveTimer != null) flushGraphNow(workflowId);
            if (!settled()) return;
            stop();
            resolve();
        });
    });
}

/** Whether the workflow's read withheld its graph's variables' values, so its saves leave them as stored. */
export function setGraphVariablesWithheld(workflowId: string, withheld: boolean): void {
    const rec = graphRecords[workflowId];
    if (rec) rec.variablesWithheld = withheld;
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

// ── Leaving the page ────────────────────────────────────────────────────

let _wired = false;

/** Install module-level listeners. Called eagerly on import below. */
function wire(): void {
    if (_wired) return;
    _wired = true;

    // Browser nav-away (close tab, back-forward navigation that triggers
    // page hide). Fire any dirty saves so they don't disappear with the
    // tab. In-tab navigation is covered by recordSnapshot already keeping
    // the store warm — there's no unmount cleanup to race against because
    // the store outlives the canvas mount.
    if (typeof window !== 'undefined') {
        const flushOnLeave = () => flushAllGraphsNow();
        window.addEventListener('pagehide', flushOnLeave);
        window.addEventListener('beforeunload', flushOnLeave);
    }
}

wire();
