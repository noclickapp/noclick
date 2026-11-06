// Reactive bridge from liveGraphStore (the module-level source of truth
// for workflow nodes/edges) into FlowCanvas. Replaces the canvas's old
// dual local/valtio React state with a single hook backed by Valtio.
//
// Why this exists: with the store as authoritative, mutations from
// any source — manual edits in this canvas, agentic edits via
// useCanvasWorkflowEdit / useMCPBuilderEvents, and remote edits from
// other users (applied by presenceManager when the canvas is
// unmounted, then visible immediately on remount) — all reach the
// canvas through one path. The canvas no longer holds an independent
// copy that must be reconciled with the store.
//
// API: returns the same shape FlowCanvas's old useState pair did —
// {nodes, edges, setNodes, setEdges} — so callsites need no rewriting.

import { useCallback, useEffect, useRef } from 'react';
import { useSnapshot } from 'valtio';
import type { Node, Edge } from '@xyflow/react';
import { graphRecords, createGraphRecord } from '~/lib/liveGraphStore';

type Updater<T> = T | ((prev: T) => T);

function applyUpdater<T>(prev: T, u: Updater<T>): T {
    return typeof u === 'function' ? (u as (p: T) => T)(prev) : u;
}

export function useLiveGraph(workflowId: string, isSkill: boolean, opts?: {
    initialNodes?: Node[];
    initialEdges?: Edge[];
}): {
    nodes: Node[];
    edges: Edge[];
    setNodes: (u: Updater<Node[]>) => void;
    setEdges: (u: Updater<Edge[]>) => void;
} {
    // Ensure a record exists synchronously so the very first read sees
    // a populated default rather than `undefined`. Seeded with
    // initialNodes/initialEdges from cached state when provided, so
    // the canvas renders the cached graph immediately (workflow:get
    // replaces it with authoritative state once the round-trip lands).
    if (workflowId && !graphRecords[workflowId]) {
        graphRecords[workflowId] = createGraphRecord(
            workflowId,
            isSkill,
            opts?.initialNodes,
            opts?.initialEdges,
        ) as never;
    }

    const snap = useSnapshot(graphRecords);
    const rec = workflowId ? snap[workflowId] : undefined;

    // Snapshots from useSnapshot are deeply readonly. ReactFlow doesn't
    // mutate the arrays it receives, but it does pass them around as
    // `Node[]`/`Edge[]` (mutable). Cast through unknown so TS doesn't
    // complain about the readonly-ness while preserving identity (the
    // snapshot reference only changes when the underlying array does).
    //
    // Defensive filter: drop entries without a string id. createWorkflowNode
    // now throws on missing id, but stale state from before that guard
    // landed (or third-party callsites that bypass it) can still leave
    // malformed entries in the proxy. ReactFlow uses `n.id` as the React
    // key; multiple entries with key=undefined collide and produce a
    // "removeChild: not a child of this node" error during reconcile.
    // Filtering here keeps rendering safe regardless.
    const rawNodes = rec?.nodes ?? EMPTY_NODES;
    const rawEdges = rec?.edges ?? EMPTY_EDGES;
    const nodes = sanitizeNodes(rawNodes as unknown as readonly Node[]) as unknown as Node[];
    const edges = filterValidById(rawEdges) as unknown as Edge[];

    // Mutators write into the proxy directly. We read the live (non-
    // snapshot) array via `graphRecords[workflowId].nodes` so functional
    // updaters see the latest, not a stale snapshot. Wrap in useCallback
    // keyed on workflowId so the identity is stable for ReactFlow.
    const setNodes = useCallback((u: Updater<Node[]>) => {
        const r = graphRecords[workflowId];
        if (!r) return;
        const next = applyUpdater(r.nodes as Node[], u);
        if (next !== r.nodes) r.nodes = next;
    }, [workflowId]);

    const setEdges = useCallback((u: Updater<Edge[]>) => {
        const r = graphRecords[workflowId];
        if (!r) return;
        const next = applyUpdater(r.edges as Edge[], u);
        if (next !== r.edges) r.edges = next;
    }, [workflowId]);

    // Suppress the linter on the deferred bootstrap above by tying the
    // hook's lifetime to workflowId — keeps the surface clean.
    const idRef = useRef(workflowId);
    useEffect(() => { idRef.current = workflowId; }, [workflowId]);

    return { nodes, edges, setNodes, setEdges };
}

const EMPTY_NODES: readonly Node[] = Object.freeze([]);
const EMPTY_EDGES: readonly Edge[] = Object.freeze([]);

/** Filter helper — keeps only entries whose `id` is a non-empty string.
 *  Returns the same array reference when nothing was dropped, so React
 *  / ReactFlow's identity check stays stable on the common path. */
function filterValidById<T extends { id?: unknown }>(arr: readonly T[]): readonly T[] {
    let dropped = 0;
    const out: T[] = [];
    for (const item of arr) {
        if (item && typeof item.id === 'string' && item.id.length > 0) {
            out.push(item);
        } else {
            dropped++;
        }
    }
    if (dropped === 0) return arr;
    return out;
}

/** Node-specific sanitizer for the controlled `nodes` ReactFlow receives. Drops
 *  entries without a string id (see filterValidById) AND repairs a missing /
 *  non-finite `position` to the origin: xyflow's adoptUserNodes reads
 *  `position.x` and hard-crashes the whole canvas on an undefined position,
 *  which stale state, collab sync, or a callsite that bypassed createWorkflowNode
 *  can leave behind. Returns the same array/refs when nothing needed fixing, so
 *  ReactFlow's identity check stays stable on the common path. */
// De-dupe the position warning per node id — sanitizeNodes runs every render, so
// a node that stays malformed in the store would otherwise log on each pass.
const warnedBadPosition = new Set<string>();

function sanitizeNodes(arr: readonly Node[]): readonly Node[] {
    let changed = false;
    const out: Node[] = [];
    for (const n of arr) {
        if (!n || typeof n.id !== 'string' || n.id.length === 0) {
            changed = true;
            continue;
        }
        const p = n.position as { x?: unknown; y?: unknown } | undefined;
        if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) {
            if (!warnedBadPosition.has(n.id)) {
                warnedBadPosition.add(n.id);
                console.error('[useLiveGraph] node has invalid position; defaulting to origin:', n.id, n.position);
            }
            out.push({ ...n, position: { x: 0, y: 0 } });
            changed = true;
        } else {
            out.push(n);
        }
    }
    return changed ? out : arr;
}
