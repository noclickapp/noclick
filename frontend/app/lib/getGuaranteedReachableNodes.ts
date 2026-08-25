// BFS utilities for graph reachability analysis during workflow execution.
// Used to determine which interface blocks should show loading states.
// Stops at conditional/switch nodes since only one branch executes.

import { resolveNodeType } from '~/utils/nodeSchemas';

export interface MinimalEdge {
    source: string;
    target: string;
    sourceHandle?: string | null;
    /** 'bottom' marks a tool-provider edge into an agent / hosting MCP node. */
    targetHandle?: string | null;
}

const BRANCHING_TYPES = new Set(['conditional', 'switch']);

/**
 * Shared BFS traversal. Follows outgoing edges from seed nodes,
 * stopping at conditional/switch nodes (doesn't follow their outgoing edges).
 */
function bfsReachable(
    adj: Map<string, string[]>,
    seedIds: string[],
    nodeTypes: Map<string, string>,
    exclude?: Set<string>
): Set<string> {
    const reachable = new Set<string>();
    const queue = [...seedIds];

    while (queue.length > 0) {
        const nodeId = queue.shift()!;

        // Don't follow outgoing edges from branching nodes
        if (BRANCHING_TYPES.has(nodeTypes.get(nodeId) ?? '')) continue;

        for (const target of adj.get(nodeId) ?? []) {
            if (!reachable.has(target) && !exclude?.has(target)) {
                reachable.add(target);
                queue.push(target);
            }
        }
    }

    return reachable;
}

/**
 * Returns the set of node IDs guaranteed to be reached from `startNodeId`.
 * Stops traversal at conditional/switch nodes (branching = not guaranteed).
 * Iteration nodes are transparent (both loop and done branches always fire).
 */
export function getGuaranteedReachableNodes(
    edges: MinimalEdge[],
    startNodeId: string,
    nodeTypes: Map<string, string>
): Set<string> {
    const adj = new Map<string, string[]>();
    for (const edge of edges) {
        const targets = adj.get(edge.source);
        if (targets) targets.push(edge.target);
        else adj.set(edge.source, [edge.target]);
    }

    return bfsReachable(adj, [startNodeId], nodeTypes, new Set([startNodeId]));
}

/**
 * Returns ALL node IDs forward-reachable from `startNodeId` (every descendant),
 * NOT stopping at conditional/switch nodes. Used to reset stale run-state on
 * every node that could execute downstream when a run starts from `startNodeId`
 * — both branches of a conditional get cleared since either might run.
 * Excludes `startNodeId` itself.
 */
export function getAllDownstreamNodes(
    edges: MinimalEdge[],
    startNodeId: string
): Set<string> {
    const adj = new Map<string, string[]>();
    for (const edge of edges) {
        const targets = adj.get(edge.source);
        if (targets) targets.push(edge.target);
        else adj.set(edge.source, [edge.target]);
    }

    const seen = new Set<string>();
    const queue = [startNodeId];
    while (queue.length > 0) {
        const id = queue.shift()!;
        for (const target of adj.get(id) ?? []) {
            if (!seen.has(target)) {
                seen.add(target);
                queue.push(target);
            }
        }
    }
    seen.delete(startNodeId); // a cycle could re-add the seed; never reset it here
    return seen;
}

/**
 * Returns nodes reachable from a specific resolved branch of a conditional/switch.
 * Called when a branching node's output arrives with `output_handle` indicating
 * which branch was taken. Follows only edges matching that handle, then continues
 * BFS with the same rules (stop at next conditional/switch).
 */
export function getReachableFromHandle(
    edges: MinimalEdge[],
    branchNodeId: string,
    resolvedHandle: string,
    nodeTypes: Map<string, string>
): Set<string> {
    // Find direct targets from the resolved handle
    const seedIds: string[] = [];
    for (const edge of edges) {
        if (
            edge.source === branchNodeId &&
            edge.sourceHandle === resolvedHandle
        ) {
            seedIds.push(edge.target);
        }
    }
    if (seedIds.length === 0) return new Set();

    // Build full adjacency list for BFS beyond the seed nodes
    const adj = new Map<string, string[]>();
    for (const edge of edges) {
        const targets = adj.get(edge.source);
        if (targets) targets.push(edge.target);
        else adj.set(edge.source, [edge.target]);
    }

    // Seeds are reachable themselves, then BFS from them
    const reachable = bfsReachable(adj, seedIds, nodeTypes);
    for (const id of seedIds) reachable.add(id);
    return reachable;
}

/**
 * Returns `startIds` plus every ancestor of them (the backward closure).
 *
 * A run that pulls in a node for its output also has to run whatever produces
 * that node's input, so the set of nodes such a run touches is the ancestor
 * closure — not just the directly-referenced ids. Used to gate "run from here"
 * on the nodes it will ACTUALLY execute: when something downstream references
 * upstream data the request goes out with forward_only=false, and gating on the
 * forward set alone let runs start with a broken upstream node in them.
 */
export function withAncestors(
    edges: MinimalEdge[],
    startIds: Iterable<string>
): Set<string> {
    const incoming = new Map<string, string[]>();
    for (const edge of edges) {
        const sources = incoming.get(edge.target);
        if (sources) sources.push(edge.source);
        else incoming.set(edge.target, [edge.source]);
    }

    const seen = new Set<string>();
    const queue = [...startIds];
    while (queue.length > 0) {
        const id = queue.shift()!;
        if (seen.has(id)) continue;
        seen.add(id);
        for (const source of incoming.get(id) ?? []) {
            if (!seen.has(source)) queue.push(source);
        }
    }
    return seen;
}

/**
 * Returns `ids` plus every tool provider wired into one of them.
 *
 * A bottom-handle edge points from the provider INTO the agent (or hosting MCP
 * node), so a provider is neither downstream of its consumer nor referenced by
 * `{{id.field}}` — yet the backend backfills these into any run containing the
 * consumer, so the agent keeps its tools. Mirrors the `bottom_edge_sources`
 * backfill in workflow_execution_handler._get_reachable_nodes.
 *
 * Without it, "Run from here" on an agent started a run whose Telegram and
 * Google Forms providers had no actions allowlisted — invisible to a gate
 * looking only forward and at ancestors.
 *
 * Iterated to a fixpoint: an MCP node in hosting mode is itself a consumer of
 * bottom-handle providers.
 */
export function withWiredToolProviders(
    edges: MinimalEdge[],
    ids: Iterable<string>
): Set<string> {
    const providersOf = new Map<string, string[]>();
    for (const edge of edges) {
        if (edge.targetHandle !== 'bottom') continue;
        const sources = providersOf.get(edge.target);
        if (sources) sources.push(edge.source);
        else providersOf.set(edge.target, [edge.source]);
    }

    const seen = new Set(ids);
    const queue = [...seen];
    while (queue.length > 0) {
        const id = queue.shift()!;
        for (const provider of providersOf.get(id) ?? []) {
            if (!seen.has(provider)) {
                seen.add(provider);
                queue.push(provider);
            }
        }
    }
    return seen;
}

/**
 * The nodes a run starting from `rootIds` would touch: those roots, everything
 * forward of them, any tool provider wired into one of them, and any upstream
 * interface / state-manager DATA provider feeding an in-scope node.
 *
 * Used when the Run popup offers a choice of entry points and the user runs
 * only some of them — the executed graph is narrowed to this set so unpicked
 * branches stay untouched. Branching nodes are transparent here (unlike
 * getGuaranteedReachableNodes): either branch may run, so both belong in scope.
 *
 * The data-provider backfill mirrors the backend's _get_reachable_nodes
 * Phase 2: a form node's value store (or a state manager) feeding a picked
 * path must still execute even when its own entry path wasn't picked —
 * without it, {{form.field}} / $('form') references in the scoped set
 * resolve against nothing (the bug behind the 2026-07-31 "No data for
 * node" report). Requires `nodes` for the type check; omitting it keeps
 * the legacy forward-only behavior.
 */
export function runScopeForRoots(
    edges: MinimalEdge[],
    rootIds: Iterable<string>,
    nodes?: Array<{ id: string; type?: string | null }>
): Set<string> {
    const adj = new Map<string, string[]>();
    const pred = new Map<string, string[]>();
    for (const edge of edges) {
        const targets = adj.get(edge.source);
        if (targets) targets.push(edge.target);
        else adj.set(edge.source, [edge.target]);
        const sources = pred.get(edge.target);
        if (sources) sources.push(edge.source);
        else pred.set(edge.target, [edge.source]);
    }

    const seen = new Set(rootIds);
    const queue = [...seen];
    while (queue.length > 0) {
        const id = queue.shift()!;
        for (const target of adj.get(id) ?? []) {
            if (!seen.has(target)) {
                seen.add(target);
                queue.push(target);
            }
        }
    }

    if (nodes) {
        const typeOf = new Map(nodes.map((n) => [n.id, n.type ?? '']));
        const backfillQueue = [...seen];
        const backfillSeen = new Set(seen);
        while (backfillQueue.length > 0) {
            const id = backfillQueue.shift()!;
            for (const predId of pred.get(id) ?? []) {
                if (backfillSeen.has(predId)) continue;
                backfillSeen.add(predId);
                const canonical = resolveNodeType(typeOf.get(predId) ?? '');
                if (
                    canonical.startsWith('interface-') ||
                    canonical === 'state-manager'
                ) {
                    seen.add(predId);
                    backfillQueue.push(predId);
                }
            }
        }
    }

    return withWiredToolProviders(edges, seen);
}
