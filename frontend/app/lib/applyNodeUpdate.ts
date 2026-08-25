// Single source of truth for node data construction and mutation.
//
// ──────────────────────────────────────────────────────────────────────────────
// Data model (one definition, used by every function in this module):
//
//   node.data.config       – nested, authoritative store for ALL user/AI-editable
//                            fields, including `_settings` (the on-error / retry /
//                            output-data block rendered by NodeSettings).
//
//   node.data.<field>      – top-level metadata + runtime knobs listed in
//                            TOP_LEVEL_FIELDS below.
//
// The TOP_LEVEL_FIELDS table is the *only* place that names a top-level field.
// Every function here reads/writes via that table, so adding or moving a field
// can't introduce drift between createWorkflowNode (load), applyNodeUpdate
// (edit), buildSaveConfig (save), and normalizeNodeUpdatePayload (collab sync).
//
// The round-trip invariant (createWorkflowNode → buildSaveConfig →
// createWorkflowNode yields an equal `data`) is enforced by the property test
// in tests/unit/applyNodeUpdate.test.ts. Any future field that misses a
// placement site will fail that test in CI before the user does.
//
// ALL node mutations should go through this module. Never spread
// { ...node.data, someField: value } at a call site — call applyNodeUpdate,
// updateNodeInList, or createWorkflowNode instead.

import type { Edge, Node } from '@xyflow/react';

import { reportInvariant } from '~/lib/telemetry-errors';

// Top-level fields on node.data. Each entry has two independent flags:
//
//   persist:  true → buildSaveConfig writes it into the save blob (so it
//                    round-trips back to the backend on save).
//   restore:  true → rawConfigToPayload lifts it from the flat save blob and
//                    places it on data.<name> when hydrating.
//
// Three resulting categories:
//
//   persist:true,  restore:true   – normal user/AI-editable metadata
//                                   (operation, label, credentialIds, etc.)
//                                   Full round trip: edit → save → load → display.
//   persist:false, restore:true   – server-authored runtime state that we
//                                   want to display on the canvas but should
//                                   NEVER be sent back to the backend (output,
//                                   outputTimestamp, _outputStoredLocally,
//                                   _outputSizeBytes). The backend is the
//                                   single source of truth; frontend save
//                                   must not stomp it.
//   persist:false, restore:false  – purely client-side transient state
//                                   (configValid, error, executionState,
//                                   workflowAnimating, _executionId, etc.).
//                                   Lives on data only during the session;
//                                   doesn't survive save or load.
const TOP_LEVEL_FIELDS: ReadonlyArray<{
    name: string;
    persist: boolean;
    restore: boolean;
}> = [
    // Persisted + restored — user/AI-editable metadata.
    { name: 'operation', persist: true, restore: true },
    { name: 'operationReason', persist: true, restore: true },
    { name: 'userFields', persist: true, restore: true },
    { name: 'goal', persist: true, restore: true },
    { name: 'label', persist: true, restore: true },
    { name: 'credentialIds', persist: true, restore: true },
    { name: 'disabled', persist: true, restore: true },
    { name: 'mockedOutput', persist: true, restore: true },
    { name: 'credentials', persist: true, restore: true },
    { name: 'content', persist: true, restore: true },
    { name: 'color', persist: true, restore: true },

    // Server-authored runtime state — display only, never written back on save and
    // never lifted from the saved config. Node outputs live solely in the CAS now;
    // they reach data.output via the workflow:get_node_outputs / get_node_output(_history)
    // responses (CAS-backed) and the live workflow:node:output event. restore:false so
    // a stale pre-cutover config.output in the workflows JSONB can never shadow the
    // fresh CAS value; persist:false so a save never writes it back.
    { name: 'output', persist: false, restore: false },
    { name: 'outputTimestamp', persist: false, restore: false },
    { name: '_outputStoredLocally', persist: false, restore: false },
    { name: '_outputSizeBytes', persist: false, restore: false },
    // Last-run status — server-authored, stored in the CAS (cas_manifests). It
    // reaches data.* via the workflow:get node_statuses map and the live
    // workflow:node:state event — never from the saved config blob. So restore:false
    // (a stale JSONB copy must be ignored) and persist:false (a save must not write it).
    { name: '_lastRunStatus', persist: false, restore: false },
    { name: '_lastRunAt', persist: false, restore: false },
    { name: '_lastRunError', persist: false, restore: false },

    // Display-only per-item sample set when "Loop over each item" injects an
    // iteration node, so its panel can offer draggable {{id.item.*}} fields before
    // the loop has run. Clipped small; the backend ignores it; a real run's
    // `output` takes precedence. persist+restore so it survives the workflow sync
    // (the non-persisted `output` above gets wiped on the next save round-trip).
    { name: 'previewOutput', persist: true, restore: true },

    // Client-only transient state — neither saved nor restored.
    { name: 'configValid', persist: false, restore: false },
    { name: 'error', persist: false, restore: false },
    // The button offered beside `error` when the backend could name a fix —
    // `{type, label, url?}` from WorkflowNodeStateEvent.error_action. Server-
    // authored and as transient as the error it belongs to, so it is neither
    // saved nor restored; a persisted copy would outlive its error and offer a
    // fix for a failure that no longer exists.
    { name: 'errorAction', persist: false, restore: false },
    { name: 'executionState', persist: false, restore: false },
    { name: 'workflowAnimating', persist: false, restore: false },
    { name: '_hasPresetPosition', persist: false, restore: false },
    { name: '_executionId', persist: false, restore: false },
    { name: '_timeToFillMs', persist: false, restore: false },
    // Live in-flight progress for the workflow output panel. Shape:
    // `{ text?: string, snapshot?: unknown }`. `text` is append-only
    // (streaming chunks from agent_node and similar); `snapshot` is
    // replace-on-write (one-shot dict from self.emit({...}) — Jira's
    // action summaries, etc.). Both write here via
    // workflow:node:progress events. Cleared when workflow:node:state
    // goes to 'running' (fresh run) and when the canonical
    // workflow:node:output lands. Display-only — canonical output for
    // downstream nodes lives in data.output.
    { name: 'progress', persist: false, restore: false },
];

// The per-node last-run status triple (server-authored, cleared together on re-run).
export const RUN_STATUS_FIELDS = [
    '_lastRunStatus',
    '_lastRunAt',
    '_lastRunError',
] as const;

const TOP_LEVEL_NAMES: ReadonlySet<string> = new Set(
    TOP_LEVEL_FIELDS.map((f) => f.name)
);
const PERSISTED_TOP_LEVEL_NAMES: ReadonlyArray<string> =
    TOP_LEVEL_FIELDS.filter((f) => f.persist).map((f) => f.name);
const RESTORED_TOP_LEVEL_NAMES: ReadonlySet<string> = new Set(
    TOP_LEVEL_FIELDS.filter((f) => f.restore).map((f) => f.name)
);
// Fields named in the registry but not restored on hydrate — dropped from the
// flat blob during rawConfigToPayload. Anything not listed above falls through
// to data.config (the default for unknown keys is "treat as config field").
const DROP_ON_RESTORE_FIELDS: ReadonlySet<string> = new Set(
    TOP_LEVEL_FIELDS.filter((f) => !f.restore).map((f) => f.name)
);

// Registered top-level fields that have a typed slot on NodeUpdatePayload.
// Other restored fields (output, outputTimestamp, _outputStoredLocally,
// _outputSizeBytes) are passed through via `extras` so applyNodeUpdate writes
// them to data.<name> without needing per-field plumbing on the payload type.
const TYPED_PAYLOAD_KEYS: ReadonlySet<string> = new Set([
    'operation',
    'operationReason',
    'userFields',
    'goal',
    'label',
    'credentialIds',
    'disabled',
    'mockedOutput',
    'credentials',
    'content',
    'color',
    'configValid',
]);

export interface NodeUpdatePayload {
    /** Config fields to merge into data.config (authoritative; includes `_settings`) */
    config?: Record<string, any>;
    /** Operation (top-level node attribute) */
    operation?: string | null;
    /** Operation reason from node drafter */
    operationReason?: string | null;
    /** Fields that need user input */
    userFields?: string[];
    /** Node goal/description */
    goal?: string;
    /** Node label */
    label?: string;
    /** Credential IDs keyed by credential type */
    credentialIds?: Record<string, string>;
    /** Whether node is disabled */
    disabled?: boolean;
    /** Mocked output data (bypasses execution). Pass `null` to clear. */
    mockedOutput?: any;
    /** Inline agent credentials (special case for agent nodes) */
    credentials?: any;
    /** Sticky-note body (top-level) */
    content?: string;
    /** Sticky-note color index (top-level) */
    color?: number;
    /** Config validation state (runtime, not persisted) */
    configValid?: boolean;
    /** Additional top-level fields to spread into data (e.g., mcpAnimationState, animation flags) */
    extras?: Record<string, any>;
}

/**
 * Read a field's value from a node, choosing `data.<name>` for registered
 * top-level fields and `data.config.<name>` for everything else.
 *
 * Use this whenever the field name comes from a Pydantic schema, a registry,
 * or any other dynamic source where the location isn't statically known.
 * Direct `node.data.label` / `node.data.operation` reads are fine for known
 * top-level fields; this helper exists for the *unknown-name* case so callers
 * can't silently read from the wrong location when a config field happens to
 * share its slot with an unset top-level field.
 */
export function getNodeFieldValue(node: Node, fieldName: string): unknown {
    const data = (node.data || {}) as Record<string, unknown>;
    if (TOP_LEVEL_NAMES.has(fieldName)) return data[fieldName];
    const config = (data.config || {}) as Record<string, unknown>;
    return config[fieldName];
}

/**
 * Apply an update to a node's data, returning a new node object.
 *
 * - `update.config` is merged into `data.config` (authoritative — includes `_settings`)
 * - Metadata fields listed in TOP_LEVEL_FIELDS are written to `data.<field>`
 * - `null` in `update.config` means "delete this config key"
 * - `update.mockedOutput === null` clears `data.mockedOutput`
 */
export function applyNodeUpdate(node: Node, update: NodeUpdatePayload): Node {
    const existingData = (node.data || {}) as Record<string, any>;
    const existingConfig = (existingData.config || {}) as Record<string, any>;
    const incomingConfig = update.config || {};

    // Resolve operation with fallback chain: explicit update > config.operation > existing
    const operation =
        update.operation ??
        incomingConfig.operation ??
        existingData.operation ??
        null;

    // Strip operation from config — it's a top-level field, not a config field
    const { operation: _stripOp, ...cleanIncomingConfig } = incomingConfig;

    // Merge nested config: existing + incoming. `null` deletes the key.
    const mergedConfig: Record<string, any> = {
        ...existingConfig,
        ...cleanIncomingConfig,
    };
    delete mergedConfig.operation;
    for (const [k, v] of Object.entries(cleanIncomingConfig)) {
        if (v === null) delete mergedConfig[k];
    }

    // Build merged data: existing + config + top-level fields from update
    const mergedData: Record<string, any> = {
        ...existingData,
        config: mergedConfig,
    };

    // operation: write or delete (null = clear, no value = keep existing handled above)
    if (operation !== null) mergedData.operation = operation;
    else delete mergedData.operation;

    // mockedOutput: explicit `null` clears; otherwise write if defined
    if (update.mockedOutput === null) {
        delete mergedData.mockedOutput;
    } else if (update.mockedOutput !== undefined) {
        mergedData.mockedOutput = update.mockedOutput;
    }

    // All other top-level fields: write if defined, skip if undefined
    const updateRecord = update as unknown as Record<string, any>;
    for (const { name } of TOP_LEVEL_FIELDS) {
        if (name === 'operation' || name === 'mockedOutput') continue; // handled above
        const value = updateRecord[name];
        if (value !== undefined) mergedData[name] = value;
    }

    if (update.extras) Object.assign(mergedData, update.extras);

    return { ...node, data: mergedData };
}

/**
 * Find a node by id in a list and apply an update, returning a new list.
 * This is the standardized way to mutate a single node inside setNodes(...).
 *
 * Usage:
 *   setNodes(nodes => updateNodeInList(nodes, nodeId, { config: { foo: 'bar' } }));
 */
export function updateNodeInList(
    nodes: Node[],
    nodeId: string,
    update: NodeUpdatePayload
): Node[] {
    return nodes.map((n) => (n.id === nodeId ? applyNodeUpdate(n, update) : n));
}

/**
 * Generic by-id list helpers used by collaborative sync handlers (and
 * wherever else we have an array of `{id}` items).
 */
export function appendIfUnique<T extends { id: string }>(
    items: T[],
    item: T
): T[] {
    return items.some((i) => i.id === item.id) ? items : [...items, item];
}

export function removeById<T extends { id: string }>(
    items: T[],
    id: string
): T[] {
    return items.filter((i) => i.id !== id);
}

export function patchById<T extends { id: string }>(
    items: T[],
    id: string,
    patch: Partial<T>
): T[] {
    return items.map((i) => (i.id === id ? { ...i, ...patch } : i));
}

/**
 * Merge BE-loaded nodes with whatever's currently in the canvas, preserving
 * transient FE-only state (mcpAnimationState set by agentic graph events
 * arriving while the canvas was unmounted, output overlays). Loaded BE
 * nodes win for everything else (config, position).
 *
 * Also keeps any in-canvas nodes the BE doesn't know about — e.g. nodes
 * added by an agentic event after the BE's last save, so they survive a
 * workflow:get round-trip.
 */
/** True when ReactFlow (and every position-reading canvas heuristic) can
 * safely touch `node.position.x/y`. */
export function hasValidPosition(
    node: { position?: { x?: unknown; y?: unknown } } | null | undefined
): boolean {
    return (
        !!node?.position &&
        Number.isFinite((node.position as { x: unknown }).x) &&
        Number.isFinite((node.position as { y: unknown }).y)
    );
}

/**
 * Heal a node entering canvas state without a valid position, loudly.
 * A single position-less node can break deletion because the nearest-select
 * heuristic throws inside the nodes-change updater, preventing remove changes
 * and undo snapshots from applying. The invariant report carries a stack so
 * the path that minted the invalid node remains attributable.
 */
export function ensureNodePosition(node: Node, source: string): Node {
    if (hasValidPosition(node)) return node;
    reportInvariant(
        `positionless node healed at ${source}: id=${node?.id} type=${node?.type}`,
        new Error().stack
    );
    return { ...node, position: { x: 0, y: 0 } };
}

export function mergeServerNodes(loaded: Node[], existing: Node[]): Node[] {
    const next = loaded.map((loadedNode) => {
        const prev = existing.find((p) => p.id === loadedNode.id);
        const animState = (
            prev?.data as { mcpAnimationState?: string } | undefined
        )?.mcpAnimationState;
        if (animState && animState !== 'complete') {
            return applyNodeUpdate(loadedNode, {
                extras: { mcpAnimationState: animState },
            });
        }
        return loadedNode;
    });
    for (const prev of existing) {
        if (!loaded.some((l) => l.id === prev.id)) next.push(prev);
    }
    return next;
}

/** Edge equivalent of mergeServerNodes — BE-loaded edges win, but
 *  any in-canvas edges the BE doesn't have (newly-added, not yet
 *  persisted) are preserved. */
export function mergeServerEdges(loaded: Edge[], existing: Edge[]): Edge[] {
    const next = [...loaded];
    for (const prev of existing) {
        if (!loaded.some((l) => l.id === prev.id)) next.push(prev);
    }
    return next;
}

/**
 * Pre-filter for the merge functions above when the canvas was seeded from
 * the IndexedDB instant-render cache. A cache-injected entry the server
 * response no longer contains was deleted after the cache was written —
 * union-merging it back would resurrect it on the canvas, and the next
 * autosave would re-persist the deletion victim (the "deleted nodes keep
 * coming back" bug). Entries the cache did NOT inject (agentic/remote adds
 * not yet saved) still get the union treatment.
 */
export function dropStaleCacheEntries<T extends { id: string }>(
    existing: T[],
    cacheInjectedIds: ReadonlySet<string>,
    serverIds: ReadonlySet<string>
): T[] {
    if (cacheInjectedIds.size === 0) return existing;
    return existing.filter(
        (item) => !cacheInjectedIds.has(item.id) || serverIds.has(item.id)
    );
}

/**
 * Convert a loose `{config?, label?, operation?, ...}` shape (from the config
 * editor or collaborative sync) into a typed NodeUpdatePayload. Unknown keys
 * are treated as `extras` (top-level data fields), NOT as config fields —
 * because callers of this function pass nested config as `raw.config` explicitly.
 */
export function normalizeNodeUpdatePayload(
    raw: Record<string, any>
): NodeUpdatePayload {
    const { config, ...rest } = raw;
    const update: NodeUpdatePayload = {};
    if (config !== undefined) update.config = config;

    const extras: Record<string, any> = {};
    for (const [k, v] of Object.entries(rest)) {
        if (v === undefined) continue;
        if (TYPED_PAYLOAD_KEYS.has(k)) {
            (update as Record<string, any>)[k] = v;
        } else {
            // Includes registered top-level fields without a typed slot
            // (output/outputTimestamp/etc.) and any caller-provided extras.
            extras[k] = v;
        }
    }
    if (Object.keys(extras).length > 0) update.extras = extras;
    return update;
}

/**
 * Convert a flat-blob `rawConfig` (the backend save shape) into a NodeUpdatePayload.
 *
 * Unknown keys are treated as *config fields* — the wire shape stores config
 * fields flat at the top of the blob alongside metadata, with no nesting.
 *
 * Registered top-level fields are routed to data.<name> via the payload's
 * top-level slots OR `extras`, depending on the field. Fields with
 * `restore: false` (configValid, error, executionState, workflowAnimating,
 * etc.) are dropped — they're transient and shouldn't survive a hydrate.
 *
 * If the blob also carries a nested `config` object (legacy/internal data), the
 * flat fields override it (flat is the newer authoritative form on save).
 */
export function rawConfigToPayload(
    rawConfig: Record<string, any>
): NodeUpdatePayload {
    const { config: nestedConfig, ...rest } = rawConfig;

    const payload: NodeUpdatePayload = {};
    const configFields: Record<string, any> = {};
    const extras: Record<string, any> = {};

    for (const [k, v] of Object.entries(rest)) {
        if (DROP_ON_RESTORE_FIELDS.has(k)) continue;
        if (TOP_LEVEL_NAMES.has(k)) {
            // Restored top-level field. If it has a typed slot on the payload
            // (operation, label, credentialIds, ...), use it; otherwise pass it
            // through via extras so applyNodeUpdate places it on data.<name>.
            if (TYPED_PAYLOAD_KEYS.has(k)) {
                (payload as Record<string, any>)[k] = v;
            } else {
                extras[k] = v;
            }
        } else {
            configFields[k] = v;
        }
    }

    const configFromNested =
        nestedConfig && typeof nestedConfig === 'object'
            ? (nestedConfig as Record<string, any>)
            : {};
    const mergedConfig = { ...configFromNested, ...configFields };
    delete mergedConfig.operation; // always top-level
    payload.config = mergedConfig;
    if (Object.keys(extras).length > 0) payload.extras = extras;

    return payload;
}

/** Per-node last-run status as returned by workflow:get (keyed by node id). */
export interface NodeStatusInfo {
    status?: string;
    finishedAt?: number;
    error?: string | null;
}

/**
 * Apply a per-node last-run status map onto a node list.
 *
 * Used by EVERY workflow load path (the initial workflow:get AND the
 * collaborative-reconnect refetch) so the "✓/✗ N ago" chip + run-status aurora
 * survive a reload/reconnect. `_lastRunStatus` is never in the saved blob
 * (restore:false) and mergeServerNodes drops it, so it must be re-applied from
 * this server-authored map on every load — otherwise a reconnect that refetches
 * the graph silently wipes the status.
 *
 * Skips a node a live run already owns — one that's currently running, or that
 * already carries a `_lastRunStatus` this session — so a stale REST snapshot can't
 * clobber fresher live state.
 */
export function applyNodeStatuses(
    nodes: Node[],
    nodeStatuses: Record<string, NodeStatusInfo> | undefined | null
): Node[] {
    if (!nodeStatuses || Object.keys(nodeStatuses).length === 0) return nodes;
    return nodes.map((n) => {
        const s = nodeStatuses[n.id];
        const data = n.data as
            | { _lastRunStatus?: string; executionState?: string }
            | undefined;
        if (
            !s ||
            data?._lastRunStatus !== undefined ||
            data?.executionState === 'running'
        )
            return n;
        return applyNodeUpdate(n, {
            extras: {
                _lastRunStatus: s.status,
                _lastRunAt: s.finishedAt,
                _lastRunError: s.error ?? undefined,
            },
        });
    });
}

/**
 * Create a ReactFlow node with the correct data model.
 *
 * Internally delegates to applyNodeUpdate so the field-placement logic lives in
 * exactly one place — eliminating a class of drift bugs where a field could
 * land at data.X on create but data.config.X on edit (or vice versa).
 */
export function createWorkflowNode(
    id: string,
    type: string,
    position: { x: number; y: number },
    rawConfig: Record<string, any> = {},
    extras: Record<string, any> = {}
): Node {
    // ID is the node's identity — every callsite MUST provide it. Most graph
    // operations key on `n.id` (filter for cursor pseudo-nodes, dedupe, lookup),
    // so a node with `id: undefined` corrupts the graph and crashes filters that
    // call `.startsWith` on it. Treat a missing id as a programming error.
    if (!id || typeof id !== 'string') {
        throw new Error(
            `createWorkflowNode: id is required (got ${JSON.stringify(id)}) for type=${type}`
        );
    }

    // ReactFlow's adoptUserNodes reads `position.x` and hard-crashes the entire
    // canvas if it's undefined. Backend/synced/pasted nodes can arrive without a
    // valid position despite the typed signature (callers pass `any` raw nodes),
    // so default to the origin and surface it loudly. Unlike `id`, position has a
    // safe default and the node self-heals (saved back with a real position), so
    // we repair rather than throw — a single bad node shouldn't fail the load.
    let pos = position as { x: number; y: number } | undefined;
    if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) {
        console.error(
            `createWorkflowNode: invalid position for node ${id} (type=${type}); defaulting to origin:`,
            position
        );
        pos = { x: 0, y: 0 };
    }

    const blank: Node = { id, type, position: pos, data: {} };
    const payload = rawConfigToPayload(rawConfig);
    if (extras && Object.keys(extras).length > 0) {
        payload.extras = { ...(payload.extras ?? {}), ...extras };
    }
    return applyNodeUpdate(blank, payload);
}

/**
 * Build the config blob for saving a node to the backend.
 *
 * Spreads `data.config` (which already contains `_settings` and every other
 * user-editable field) and mirrors persisted top-level metadata into the same
 * flat blob alongside it.
 */
export function buildSaveConfig(node: Node): Record<string, any> {
    const data = (node.data || {}) as Record<string, any>;
    const config = {
        ...((data.config as Record<string, any> | undefined) || {}),
    };

    // operation has a truthy check (skip null/empty) for back-compat with old data
    if (data.operation) config.operation = data.operation;

    for (const name of PERSISTED_TOP_LEVEL_NAMES) {
        if (name === 'operation') continue; // handled above
        const value = data[name];
        if (value !== undefined) config[name] = value;
    }

    return config;
}

/**
 * Serialize a single node for the workflow:update backend payload. Includes
 * `width`/`height` for resizable nodes (interface blocks, sticky notes) —
 * checks both node.width/height (set after a resize) and node.style
 * (set on creation).
 */
export interface SerializedWorkflowNode {
    id: string;
    type?: string;
    position: Node['position'];
    config: Record<string, unknown>;
    width?: unknown;
    height?: unknown;
}

export function serializeNodeForSave(node: Node): SerializedWorkflowNode {
    const nodeData: SerializedWorkflowNode = {
        id: node.id,
        type: node.type,
        position: node.position,
        config: buildSaveConfig(node),
    };
    const w =
        node.width ?? (node.style as Record<string, any> | undefined)?.width;
    const h =
        node.height ?? (node.style as Record<string, any> | undefined)?.height;
    if (w) nodeData.width = w;
    if (h) nodeData.height = h;
    return nodeData;
}

/**
 * Serialize an edge for the workflow:update backend payload.
 */
export interface SerializedWorkflowEdge {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

export function serializeEdgeForSave(edge: Edge): SerializedWorkflowEdge {
    return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
    };
}
