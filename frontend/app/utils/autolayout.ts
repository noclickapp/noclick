// Deterministic autolayout algorithm for workflow nodes.
// Implements a Sugiyama-style layered graph drawing that arranges nodes left-to-right.
// Ported from backend/debug_autolayout.py to work with React Flow's Node/Edge types.

import type { Node, Edge } from '@xyflow/react';
import { getDimensionsByType } from '~/components/workflow/nodes/nodeRegistry';

// ─── Layout Constants ────────────────────────────────────────────────────────

// Sized so 90px-wide automation nodes still have ~50px clearance when they
// expand to ~220px during the agentic builder's editing panel. Kept in sync
// with backend/utils/autolayout.py.
const H_GAP = 180;
const V_GAP = 80;
const SUBGRAPH_GAP = 300;
const LOOP_Y_OFFSET = 100;
const BRANCH_Y_OFFSET = 120;
const RIGHT_Y_OFFSET = -100;
const DEFAULT_WIDTH = 90;
const DEFAULT_HEIGHT = 90;
// Gap from agent bottom to the attached tool row — sized so the agent's
// label, run-status pill, and the edges' "N tools" chips fit between them.
const TOOL_ATTACH_V_GAP = 180;
// Extra gap when the agent also renders a "Used by interface" badge in its
// bottom stack (an interface-html-react node references it by id).
const TOOL_ATTACH_BADGE_EXTRA = 40;
// Horizontal gap between attached tools — sized so each tool's label below
// it doesn't collide with its neighbor's.
const TOOL_ATTACH_H_GAP = 90;

// Stability constants for pinned-node autolayout (DynaDAG-style).
// When pinnedNodeIds is provided, pinned nodes resist movement.
const PINNED_ORDER_ALPHA = 0.1; // 10% barycenter, 90% current order for pinned nodes
const PINNED_Y_BETA = 0.1; // 10% computed Y, 90% current Y for pinned nodes
const PINNED_POS_BLEND = 0.1; // Final position blend: 10% computed, 90% original for pinned nodes

// ─── Dimension Resolution ────────────────────────────────────────────────────

type Dims = [number, number]; // [width, height]

function getDims(node: Node): Dims {
    if (node.measured?.width && node.measured?.height) {
        return [node.measured.width, node.measured.height];
    }
    if (node.width && node.height) {
        return [node.width, node.height];
    }
    const regDims = node.type ? getDimensionsByType(node.type) : undefined;
    if (regDims) {
        return [regDims.width, regDims.height];
    }
    return [DEFAULT_WIDTH, DEFAULT_HEIGHT];
}

// ─── Handle Y Offsets ────────────────────────────────────────────────────────

function handleYOffset(edge: Edge, reverse = false, diamondEdges?: Set<string>, handlePositions?: Map<string, number>): number {
    const sh = edge.sourceHandle || '';
    const sign = reverse ? -1 : 1;
    if (sh === 'loop') return sign * LOOP_Y_OFFSET;
    if (sh === 'false') return sign * BRANCH_Y_OFFSET;
    if (sh === 'true') return sign * -BRANCH_Y_OFFSET;
    if (sh === 'right') return sign * RIGHT_Y_OFFSET;
    if (diamondEdges?.has(edge.id)) return sign * BRANCH_Y_OFFSET;
    const hp = handlePositions?.get(edge.id);
    if (hp !== undefined) return sign * hp * BRANCH_Y_OFFSET;
    return 0;
}

// ─── Back-Edge Detection ─────────────────────────────────────────────────────

function detectBackEdges(
    nodeIds: Set<string>,
    fwdAdj: Map<string, [string, Edge][]>,
    nodeMap: Map<string, Node>,
): Set<string> {
    const backEdgeIds = new Set<string>();

    // Phase 1: Structural detection for iteration loops
    const iterationNodes: string[] = [];
    for (const nid of nodeIds) {
        if (nodeMap.get(nid)?.type === 'iteration') {
            iterationNodes.push(nid);
        }
    }

    for (const iterNid of iterationNodes) {
        // Find all nodes reachable from iteration's "loop" output
        const loopDescendants = new Set<string>();
        const queue: string[] = [];
        for (const [v, e] of fwdAdj.get(iterNid) || []) {
            if (e.sourceHandle === 'loop' && nodeIds.has(v)) {
                queue.push(v);
            }
        }

        while (queue.length > 0) {
            const u = queue.shift()!;
            if (loopDescendants.has(u) || u === iterNid) continue;
            loopDescendants.add(u);
            for (const [w, e2] of fwdAdj.get(u) || []) {
                if (w !== iterNid && nodeIds.has(w) && !loopDescendants.has(w)) {
                    queue.push(w);
                }
            }
        }

        // Mark edges from loop descendants back to the iteration
        for (const desc of loopDescendants) {
            for (const [v, e] of fwdAdj.get(desc) || []) {
                if (v === iterNid) {
                    backEdgeIds.add(e.id);
                }
            }
        }
    }

    // Phase 2: Iterative DFS for any remaining cycles
    const remainingFwd = new Map<string, [string, Edge][]>();
    for (const nid of nodeIds) {
        const adj: [string, Edge][] = [];
        for (const [v, e] of fwdAdj.get(nid) || []) {
            if (!backEdgeIds.has(e.id) && nodeIds.has(v)) {
                adj.push([v, e]);
            }
        }
        remainingFwd.set(nid, adj);
    }

    const WHITE = 0, GRAY = 1, BLACK = 2;
    const color = new Map<string, number>();
    for (const nid of nodeIds) color.set(nid, WHITE);

    // Compute in-degree for priority ordering
    const inDeg = new Map<string, number>();
    for (const nid of nodeIds) inDeg.set(nid, 0);
    for (const nid of nodeIds) {
        for (const [v] of remainingFwd.get(nid) || []) {
            inDeg.set(v, (inDeg.get(v) || 0) + 1);
        }
    }

    const sources = [...nodeIds].filter(n => (inDeg.get(n) || 0) === 0).sort();
    const nonSources = [...nodeIds].filter(n => (inDeg.get(n) || 0) > 0).sort();

    // Iterative DFS using explicit stack
    for (const startNid of [...sources, ...nonSources]) {
        if (color.get(startNid) !== WHITE) continue;

        const stack: { nid: string; idx: number }[] = [{ nid: startNid, idx: 0 }];
        color.set(startNid, GRAY);

        while (stack.length > 0) {
            const top = stack[stack.length - 1];
            const adj = remainingFwd.get(top.nid) || [];

            if (top.idx >= adj.length) {
                color.set(top.nid, BLACK);
                stack.pop();
                continue;
            }

            const [v, e] = adj[top.idx];
            top.idx++;

            if (color.get(v) === GRAY) {
                backEdgeIds.add(e.id);
            } else if (color.get(v) === WHITE) {
                color.set(v, GRAY);
                stack.push({ nid: v, idx: 0 });
            }
        }
    }

    return backEdgeIds;
}

// ─── Graph Utilities ─────────────────────────────────────────────────────────

function findConnectedComponents(nodeIds: Set<string>, edges: Edge[]): Set<string>[] {
    const adj = new Map<string, Set<string>>();
    for (const nid of nodeIds) adj.set(nid, new Set());

    for (const e of edges) {
        if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
            adj.get(e.source)!.add(e.target);
            adj.get(e.target)!.add(e.source);
        }
    }

    const visited = new Set<string>();
    const components: Set<string>[] = [];

    for (const nid of [...nodeIds].sort()) {
        if (visited.has(nid)) continue;
        const comp = new Set<string>();
        const queue = [nid];
        while (queue.length > 0) {
            const u = queue.shift()!;
            if (visited.has(u)) continue;
            visited.add(u);
            comp.add(u);
            for (const v of adj.get(u) || []) {
                if (!visited.has(v)) queue.push(v);
            }
        }
        components.push(comp);
    }

    components.sort((a, b) => b.size - a.size);
    return components;
}

// ─── Overlap Resolution ──────────────────────────────────────────────────────

function resolveOverlaps(
    layerNodes: string[],
    yCenters: Map<string, number>,
    dims: Map<string, Dims>,
    gap: number,
): void {
    if (layerNodes.length <= 1) return;
    const sorted = [...layerNodes].sort((a, b) => yCenters.get(a)! - yCenters.get(b)!);

    // Record original center for symmetric expansion
    let originalSum = 0;
    for (const nid of sorted) originalSum += yCenters.get(nid)!;
    const originalCenter = originalSum / sorted.length;

    // Push overlapping nodes apart
    for (let i = 1; i < sorted.length; i++) {
        const prev = sorted[i - 1];
        const curr = sorted[i];
        const prevBottom = yCenters.get(prev)! + dims.get(prev)![1] / 2;
        const currTop = yCenters.get(curr)! - dims.get(curr)![1] / 2;
        if (currTop - prevBottom < gap) {
            yCenters.set(curr, prevBottom + gap + dims.get(curr)![1] / 2);
        }
    }

    // Re-center to preserve the original mean Y (symmetric expansion)
    let newSum = 0;
    for (const nid of sorted) newSum += yCenters.get(nid)!;
    const newCenter = newSum / sorted.length;
    const shift = originalCenter - newCenter;
    if (Math.abs(shift) > 1) {
        for (const nid of sorted) {
            yCenters.set(nid, yCenters.get(nid)! + shift);
        }
    }
}

// ─── Core Layout ─────────────────────────────────────────────────────────────

function layoutSubgraph(
    nodeIds: Set<string>,
    nodeMap: Map<string, Node>,
    edges: Edge[],
    dims: Map<string, Dims>,
    pinnedNodeIds?: Set<string>,
): Map<string, { x: number; y: number }> {
    // Build adjacency
    const fwd = new Map<string, [string, Edge][]>();
    const bwd = new Map<string, [string, Edge][]>();
    for (const nid of nodeIds) {
        fwd.set(nid, []);
        bwd.set(nid, []);
    }
    for (const e of edges) {
        if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
            fwd.get(e.source)!.push([e.target, e]);
            bwd.get(e.target)!.push([e.source, e]);
        }
    }

    // Detect back-edges
    const backEdgeIds = detectBackEdges(nodeIds, fwd, nodeMap);

    // Collect back-edge source nodes (last node in loop body that links back)
    const backEdgeSources = new Set<string>();
    for (const e of edges) {
        if (backEdgeIds.has(e.id) && nodeIds.has(e.source)) {
            backEdgeSources.add(e.source);
        }
    }

    // Build DAG (forward adjacency without back-edges)
    const dagFwd = new Map<string, [string, Edge][]>();
    const dagBwd = new Map<string, [string, Edge][]>();
    const dagInDeg = new Map<string, number>();
    for (const nid of nodeIds) {
        dagFwd.set(nid, []);
        dagBwd.set(nid, []);
        dagInDeg.set(nid, 0);
    }
    for (const e of edges) {
        if (backEdgeIds.has(e.id)) continue;
        if (nodeIds.has(e.source) && nodeIds.has(e.target)) {
            dagFwd.get(e.source)!.push([e.target, e]);
            dagBwd.get(e.target)!.push([e.source, e]);
            dagInDeg.set(e.target, (dagInDeg.get(e.target) || 0) + 1);
        }
    }

    // ── Build handle position map for multi-output nodes (switch, etc.) ──
    // Maps edge.id -> normalized position in [-1, 1] based on handle ordering.
    const handlePositions = new Map<string, number>();
    for (const nid of nodeIds) {
        const node = nodeMap.get(nid)!;
        const ntype = node.type || '';
        const data = node.data as Record<string, unknown> | undefined;
        let handleOrder: string[] | null = null;
        if (ntype === 'switch') {
            const config = data?.config as Record<string, unknown> | undefined;
            const cases = config?.switch_cases as Array<{ value?: string }> | undefined;
            // Mirror SwitchNode's rendered handle order: cases first, then the
            // always-present "default" fallback last (unless a case owns that id).
            const caseValues = (Array.isArray(cases) ? cases : [])
                .map(c => c.value || '')
                .filter(Boolean);
            handleOrder = caseValues.includes('default')
                ? caseValues
                : [...caseValues, 'default'];
        }
        if (!handleOrder || handleOrder.length < 2) continue;
        const n = handleOrder.length;
        for (const [, edge] of dagFwd.get(nid) || []) {
            const sh = edge.sourceHandle || '';
            const idx = handleOrder.indexOf(sh);
            if (idx >= 0) {
                handlePositions.set(edge.id, (idx - (n - 1) / 2) / Math.max(1, (n - 1) / 2));
            }
        }
    }

    // Topological sort (Kahn's algorithm)
    const topo: string[] = [];
    const queue: string[] = [];
    for (const nid of [...nodeIds].sort()) {
        if (dagInDeg.get(nid) === 0) queue.push(nid);
    }
    const deg = new Map(dagInDeg);
    while (queue.length > 0) {
        const u = queue.shift()!;
        topo.push(u);
        for (const [v] of dagFwd.get(u) || []) {
            deg.set(v, deg.get(v)! - 1);
            if (deg.get(v) === 0) queue.push(v);
        }
    }
    for (const nid of nodeIds) {
        if (!topo.includes(nid)) topo.push(nid);
    }

    // ── Layer assignment (longest path from sources) ──
    const layer = new Map<string, number>();
    for (const nid of nodeIds) layer.set(nid, 0);
    for (const u of topo) {
        for (const [v] of dagFwd.get(u) || []) {
            layer.set(v, Math.max(layer.get(v)!, layer.get(u)! + 1));
        }
    }

    // Save node depth (longest path from any source) before compaction, for Y weighting
    const depth = new Map(layer);

    // ── Compaction: push source nodes closer to targets ──
    for (const nid of nodeIds) {
        if (dagInDeg.get(nid) === 0 && (dagFwd.get(nid)?.length || 0) > 0) {
            const minSuccLayer = Math.min(
                ...dagFwd.get(nid)!.map(([v]) => layer.get(v)!),
            );
            const desired = minSuccLayer - 1;
            if (desired > layer.get(nid)!) {
                layer.set(nid, desired);
            }
        }
    }

    // ── Compact side branches into predecessor's layer ──
    const compacted = new Set<string>();
    // Edges that start a diamond side-path get a Y offset to create visual branching
    const diamondSideEdgeIds = new Set<string>();
    const diamondSideNodes = new Set<string>();
    for (const nid of topo) {
        const preds = dagBwd.get(nid) || [];
        if (preds.length !== 1) continue;
        const [predId, predEdge] = preds[0];
        if (predEdge.sourceHandle === 'loop') continue;
        if (layer.get(nid) !== layer.get(predId)! + 1) continue;

        const otherSuccs = (dagFwd.get(predId) || []).filter(([v]) => v !== nid);
        if (!otherSuccs.some(([v]) => layer.get(v)! > layer.get(nid)!)) continue;

        const mySuccs = dagFwd.get(nid) || [];
        if (mySuccs.length > 0 && Math.min(...mySuccs.map(([v]) => layer.get(v)!)) < layer.get(predId)! + 2) {
            continue;
        }

        // Don't compact if this is a diamond pattern: the node's downstream
        // eventually converges with the predecessor's other successors.
        // Instead, mark the edge for Y-offset to create visual branching.
        const otherSuccIds = new Set(otherSuccs.map(([v]) => v));
        if (otherSuccIds.size > 0) {
            let isDiamond = false;
            const visited = new Set<string>();
            const bfsQueue = [nid];
            while (bfsQueue.length > 0) {
                const u = bfsQueue.shift()!;
                if (visited.has(u)) continue;
                visited.add(u);
                for (const [v] of dagFwd.get(u) || []) {
                    if (otherSuccIds.has(v)) { isDiamond = true; break; }
                    if (!visited.has(v)) bfsQueue.push(v);
                }
                if (isDiamond) break;
            }
            if (isDiamond) {
                diamondSideEdgeIds.add(predEdge.id);
                for (const v of visited) diamondSideNodes.add(v);
                continue;
            }
        }

        layer.set(nid, layer.get(predId)!);
        compacted.add(nid);
    }

    // ── Recompute layers after compaction ──
    for (const u of topo) {
        if (compacted.has(u)) {
            const predId = dagBwd.get(u)![0][0];
            layer.set(u, layer.get(predId)!);
            continue;
        }
        if (dagInDeg.get(u) === 0) continue;
        const preds = dagBwd.get(u) || [];
        if (preds.length > 0) {
            layer.set(u, Math.max(...preds.map(([pid]) => layer.get(pid)! + 1)));
        }
    }

    // ── Group by layer ──
    const layers = new Map<number, string[]>();
    for (const nid of nodeIds) {
        const L = layer.get(nid)!;
        if (!layers.has(L)) layers.set(L, []);
        layers.get(L)!.push(nid);
    }
    const maxLayer = Math.max(...layers.keys());

    // ── Ordering within layers ──
    const posInLayer = new Map<string, number>();

    function typePriority(nid: string): number {
        const t = nodeMap.get(nid)?.type || '';
        if (t.startsWith('trigger')) return 0;
        if (t.startsWith('interface')) return 1;
        return 2;
    }

    function typeSortKey(nid: string): string {
        return nodeMap.get(nid)?.type || '';
    }

    function handleOffset(e: Edge): number {
        const sh = e.sourceHandle || '';
        if (sh === 'loop') return 0.5;
        if (sh === 'false') return 0.4;
        if (sh === 'true') return -0.4;
        if (sh === 'right') return -0.3;
        const hp = handlePositions.get(e.id);
        if (hp !== undefined) return hp * 0.5;
        return 0;
    }

    function sortLayer(layerNodes: string[], bary: Map<string, number>, currentOrder?: Map<string, number>): void {
        if (!layerNodes.length) return;

        // Stability: blend barycenter with current order for pinned nodes
        if (currentOrder && pinnedNodeIds) {
            for (const nid of layerNodes) {
                if (pinnedNodeIds.has(nid) && currentOrder.has(nid)) {
                    const raw = bary.get(nid) || 0;
                    bary.set(nid, PINNED_ORDER_ALPHA * raw + (1 - PINNED_ORDER_ALPHA) * currentOrder.get(nid)!);
                }
            }
        }

        // Check if all predecessor-barycenters are effectively the same
        const predSets = new Map<string, string>();
        for (const nid of layerNodes) {
            const preds = (dagBwd.get(nid) || [])
                .filter(([pid]) => posInLayer.has(pid))
                .map(([pid]) => pid)
                .sort()
                .join(',');
            predSets.set(nid, preds);
        }
        const uniquePredSets = new Set(predSets.values());

        if (uniquePredSets.size === 1 && layerNodes.length > 2) {
            layerNodes.sort((a, b) => {
                const typeA = typeSortKey(a), typeB = typeSortKey(b);
                if (typeA !== typeB) return typeA < typeB ? -1 : 1;
                const baryDiff = (bary.get(a) || 0) - (bary.get(b) || 0);
                if (baryDiff !== 0) return baryDiff;
                return a < b ? -1 : 1;
            });
        } else {
            layerNodes.sort((a, b) => {
                const baryDiff = (bary.get(a) || 0) - (bary.get(b) || 0);
                if (baryDiff !== 0) return baryDiff;
                const typeA = typeSortKey(a), typeB = typeSortKey(b);
                if (typeA !== typeB) return typeA < typeB ? -1 : 1;
                return a < b ? -1 : 1;
            });
        }
    }

    // Stability: seed posInLayer from current Y positions for pinned nodes
    if (pinnedNodeIds) {
        const pinnedInComp = new Set([...nodeIds].filter(nid => pinnedNodeIds.has(nid)));
        for (let L = 0; L <= maxLayer; L++) {
            const pinnedInLayer = (layers.get(L) || []).filter(nid => pinnedInComp.has(nid));
            if (pinnedInLayer.length > 0) {
                pinnedInLayer.sort((a, b) =>
                    (nodeMap.get(a)!.position?.y ?? 0) - (nodeMap.get(b)!.position?.y ?? 0)
                );
                for (let i = 0; i < pinnedInLayer.length; i++) {
                    posInLayer.set(pinnedInLayer[i], i);
                }
            }
        }
    }

    // Multiple forward + backward sweeps
    for (let sweep = 0; sweep < 3; sweep++) {
        for (let L = 0; L <= maxLayer; L++) {
            const layerNodes = layers.get(L)!;
            if (L === 0 && sweep === 0) {
                layerNodes.sort((a, b) => {
                    const pa = typePriority(a), pb = typePriority(b);
                    if (pa !== pb) return pa - pb;
                    return a < b ? -1 : 1;
                });
            } else {
                const bary = new Map<string, number>();
                for (const nid of layerNodes) {
                    const vals: number[] = [];
                    for (const [pid, e] of dagBwd.get(nid) || []) {
                        if (posInLayer.has(pid)) {
                            vals.push(posInLayer.get(pid)! + handleOffset(e));
                        }
                    }
                    bary.set(nid, vals.length > 0
                        ? vals.reduce((a, b) => a + b, 0) / vals.length
                        : posInLayer.get(nid) || 0);
                }
                sortLayer(layerNodes, bary,
                    pinnedNodeIds ? new Map(posInLayer) : undefined);
            }
            for (let i = 0; i < layerNodes.length; i++) {
                posInLayer.set(layerNodes[i], i);
            }
        }

        // Backward sweep
        for (let L = maxLayer - 1; L >= 0; L--) {
            const layerNodes = layers.get(L)!;
            const bary = new Map<string, number>();
            for (const nid of layerNodes) {
                const vals = (dagFwd.get(nid) || [])
                    .filter(([v]) => posInLayer.has(v))
                    .map(([v]) => posInLayer.get(v)!);
                bary.set(nid, vals.length > 0
                    ? vals.reduce((a, b) => a + b, 0) / vals.length
                    : posInLayer.get(nid) || 0);
            }
            sortLayer(layerNodes, bary,
                pinnedNodeIds ? new Map(posInLayer) : undefined);
            for (let i = 0; i < layerNodes.length; i++) {
                posInLayer.set(layerNodes[i], i);
            }
        }
    }

    // ── X-coordinate assignment ──
    const layerX = new Map<number, number>();
    let x = 0;
    for (let L = 0; L <= maxLayer; L++) {
        const layerNodes = layers.get(L);
        if (!layerNodes || layerNodes.length === 0) {
            layerX.set(L, x);
            x += DEFAULT_WIDTH + H_GAP;
            continue;
        }
        layerX.set(L, x);
        const maxW = Math.max(...layerNodes.map(nid => dims.get(nid)![0]));
        x += maxW + H_GAP;
    }

    // ── Y-coordinate assignment ──
    const nodeY = new Map<string, number>();

    // Identify layers where a tall source node (e.g. interface-config-form) would displace
    // chain nodes via overlap resolution. Only applies when source height > chain height + V_GAP.
    // Tall sources are excluded from overlap resolution; small sources stay with chain nodes.
    const mixedLayers = new Set<number>();
    const tallSources = new Set<string>();
    for (let L = 0; L <= maxLayer; L++) {
        const ln = layers.get(L)!;
        const sources = ln.filter(n => dagInDeg.get(n) === 0);
        const chains = ln.filter(n => (dagInDeg.get(n) || 0) > 0);
        if (sources.length === 0 || chains.length === 0) continue;
        const maxChainH = Math.max(...chains.map(n => dims.get(n)![1]));
        const tallInLayer = sources.filter(n => dims.get(n)![1] > maxChainH + V_GAP);
        if (tallInLayer.length > 0) {
            mixedLayers.add(L);
            for (const n of tallInLayer) tallSources.add(n);
        }
    }

    function resolveLayer(L: number): void {
        if (mixedLayers.has(L)) {
            // Exclude only tall sources; small sources resolve with chain nodes
            const nonTall = layers.get(L)!.filter(n => !tallSources.has(n));
            resolveOverlaps(nonTall, nodeY, dims, V_GAP);
        } else {
            resolveOverlaps(layers.get(L)!, nodeY, dims, V_GAP);
        }
    }

    // Forward pass — two phases per layer
    for (let L = 0; L <= maxLayer; L++) {
        const deferred: string[] = [];
        for (const nid of layers.get(L)!) {
            const allVals: [number, number][] = [];
            const mainVals: [number, number][] = [];
            for (const [pid, e] of dagBwd.get(nid) || []) {
                if (nodeY.has(pid) && layer.get(pid)! < L) {
                    const y = nodeY.get(pid)! + handleYOffset(e, false, diamondSideEdgeIds, handlePositions);
                    const w = Math.max(1, depth.get(pid)!);
                    allVals.push([y, w]);
                    if (!diamondSideNodes.has(pid)) mainVals.push([y, w]);
                }
            }
            const vals = mainVals.length > 0 ? mainVals : allVals;
            if (vals.length > 0) {
                const totalW = vals.reduce((s, [, w]) => s + w, 0);
                nodeY.set(nid, vals.reduce((s, [y, w]) => s + y * w, 0) / totalW);
                // Stability: blend computed Y with current Y for pinned nodes
                if (pinnedNodeIds?.has(nid)) {
                    const curY = nodeMap.get(nid)!.position?.y ?? 0;
                    const curYCenter = curY + dims.get(nid)![1] / 2;
                    nodeY.set(nid, PINNED_Y_BETA * nodeY.get(nid)! + (1 - PINNED_Y_BETA) * curYCenter);
                }
            } else {
                deferred.push(nid);
            }
        }
        // Second pass: compacted nodes follow their same-layer predecessor
        for (const nid of deferred) {
            let found = false;
            for (const [pid] of dagBwd.get(nid) || []) {
                if (nodeY.has(pid) && layer.get(pid) === L) {
                    nodeY.set(nid, nodeY.get(pid)!);
                    found = true;
                    break;
                }
            }
            if (!found) {
                // Stability: pinned source nodes use their current Y instead of 0
                if (pinnedNodeIds?.has(nid)) {
                    const curY = nodeMap.get(nid)!.position?.y ?? 0;
                    nodeY.set(nid, curY + dims.get(nid)![1] / 2);
                } else {
                    nodeY.set(nid, 0);
                }
            }
        }
        resolveLayer(L);
    }

    // Iterative refinement — cross-layer edges only
    for (let refineIter = 0; refineIter < 3; refineIter++) {
        // Backward pass
        for (let L = maxLayer - 1; L >= 0; L--) {
            for (const nid of layers.get(L)!) {
                const crossSuccs = (dagFwd.get(nid) || []).filter(([v]) => layer.get(v)! > L);
                if (crossSuccs.length <= 1) continue;
                const crossPreds = (dagBwd.get(nid) || []).filter(([p]) => layer.get(p)! < L);
                const allVals: number[] = [];
                const mainVals: number[] = [];
                for (const [v, e] of crossSuccs) {
                    if (nodeY.has(v)) {
                        const y = nodeY.get(v)! + handleYOffset(e, true, diamondSideEdgeIds, handlePositions);
                        allVals.push(y);
                        if (!diamondSideNodes.has(v)) mainVals.push(y);
                    }
                }
                const vals = mainVals.length > 0 ? mainVals : allVals;
                if (vals.length > 0) {
                    const ideal = vals.reduce((a, b) => a + b, 0) / vals.length;
                    const nPred = crossPreds.length;
                    const keep = Math.min(0.8, 0.4 + 0.05 * nPred);
                    nodeY.set(nid, keep * nodeY.get(nid)! + (1 - keep) * ideal);
                    // Stability: pull pinned nodes back toward current Y
                    if (pinnedNodeIds?.has(nid)) {
                        const curY = nodeMap.get(nid)!.position?.y ?? 0;
                        const curYCenter = curY + dims.get(nid)![1] / 2;
                        nodeY.set(nid, PINNED_Y_BETA * nodeY.get(nid)! + (1 - PINNED_Y_BETA) * curYCenter);
                    }
                }
            }
            resolveLayer(L);
        }

        // Forward pass
        for (let L = 1; L <= maxLayer; L++) {
            for (const nid of layers.get(L)!) {
                const crossPreds = (dagBwd.get(nid) || []).filter(([p]) => layer.get(p)! < L);
                if (crossPreds.length === 0) continue;
                const crossSuccs = (dagFwd.get(nid) || []).filter(([v]) => layer.get(v)! > L);
                const allVals: [number, number][] = [];
                const mainVals: [number, number][] = [];
                for (const [pid, e] of crossPreds) {
                    if (nodeY.has(pid)) {
                        const y = nodeY.get(pid)! + handleYOffset(e, false, diamondSideEdgeIds, handlePositions);
                        const w = Math.max(1, depth.get(pid)!);
                        allVals.push([y, w]);
                        if (!diamondSideNodes.has(pid)) mainVals.push([y, w]);
                    }
                }
                const vals = mainVals.length > 0 ? mainVals : allVals;
                if (vals.length > 0) {
                    const totalW = vals.reduce((s, [, w]) => s + w, 0);
                    const ideal = vals.reduce((s, [y, w]) => s + y * w, 0) / totalW;
                    const nSucc = crossSuccs.length;
                    const keep = Math.min(0.8, 0.4 + 0.05 * nSucc);
                    nodeY.set(nid, keep * nodeY.get(nid)! + (1 - keep) * ideal);
                    // Stability: pull pinned nodes back toward current Y
                    if (pinnedNodeIds?.has(nid)) {
                        const curY = nodeMap.get(nid)!.position?.y ?? 0;
                        const curYCenter = curY + dims.get(nid)![1] / 2;
                        nodeY.set(nid, PINNED_Y_BETA * nodeY.get(nid)! + (1 - PINNED_Y_BETA) * curYCenter);
                    }
                }
            }
            resolveLayer(L);
        }
    }

    // ── Push back-edge source nodes down so backward edges clear the loop body ──
    for (const nid of backEdgeSources) {
        if (nodeY.has(nid)) {
            nodeY.set(nid, nodeY.get(nid)! + LOOP_Y_OFFSET);
        }
    }
    const affectedLayers = new Set<number>();
    for (const nid of backEdgeSources) affectedLayers.add(layer.get(nid)!);
    for (const L of affectedLayers) {
        resolveLayer(L);
    }

    // ── Reposition tall source nodes in mixed layers above the chain ──
    for (const L of mixedLayers) {
        const layerNodes = layers.get(L)!;
        const tallInLayer = layerNodes.filter(n => tallSources.has(n));
        const nonTall = layerNodes.filter(n => !tallSources.has(n));
        if (tallInLayer.length === 0 || nonTall.length === 0) continue;
        // Re-resolve overlaps among non-tall nodes (chain + small sources)
        resolveOverlaps(nonTall, nodeY, dims, V_GAP);
        // Position tall source nodes above the topmost non-tall node
        let topY = Math.min(...nonTall.map(n => nodeY.get(n)! - dims.get(n)![1] / 2));
        for (const src of [...tallInLayer].sort((a, b) => nodeY.get(b)! - nodeY.get(a)!)) {
            const srcH = dims.get(src)![1];
            nodeY.set(src, topY - V_GAP - srcH / 2);
            topY = nodeY.get(src)! - srcH / 2;
        }
    }

    // ── Convert to top-left positions ──
    const positions = new Map<string, { x: number; y: number }>();
    for (const nid of nodeIds) {
        const L = layer.get(nid)!;
        const [w, h] = dims.get(nid)!;
        const maxW = Math.max(...layers.get(L)!.map(n => dims.get(n)![0]));
        const xOffset = (maxW - w) / 2;
        positions.set(nid, {
            x: layerX.get(L)! + xOffset,
            y: nodeY.get(nid)! - h / 2,
        });
    }

    return positions;
}

// ─── Main Autolayout ─────────────────────────────────────────────────────────

/**
 * Applies deterministic autolayout to workflow nodes.
 * Arranges nodes in a clean left-to-right Sugiyama-style layout.
 * Sticky notes are excluded from layout and keep their original positions.
 * Disconnected subgraphs are laid out independently and stacked vertically.
 */
export function autolayout(nodes: Node[], edges: Edge[], pinnedNodeIds?: Set<string>): Node[] {
    const realNodes = nodes.filter(n => n.type !== 'stickyNote');
    if (realNodes.length === 0) return nodes;

    const nodeMap = new Map<string, Node>();
    const dimsMap = new Map<string, Dims>();
    for (const n of realNodes) {
        nodeMap.set(n.id, n);
        dimsMap.set(n.id, getDims(n));
    }
    const nodeIds = new Set(nodeMap.keys());

    // ── Separate tool→agent vertical attachments ──
    // Tool providers (tool/mcp-server/alarm/filesystem nodes AND integration
    // nodes in provider mode) connect into an agent's bottom handle and are
    // positioned below their agent rather than in the horizontal layout.
    // targetHandle === 'bottom' is the defining attribute of these edges;
    // sourceHandle === 'top' is the fallback for edges that lost their
    // targetHandle in a serialization hop. Both identify a tool provider
    // regardless of its source node type — integration providers (automation-*)
    // included, not just tool/mcp-server nodes. Mirrors backend/utils/autolayout.py.
    const toolAgentEdgeIds = new Set<string>();
    const agentTools = new Map<string, string[]>();
    for (const e of edges) {
        const srcNode = nodeMap.get(e.source);
        const tgtNode = nodeMap.get(e.target);
        // Consumers of provider attachments: agents AND hosting-mode MCP
        // nodes (providers hang below the MCP node, which itself may hang
        // below an agent — a 3-tier stack).
        if (!srcNode || !tgtNode || (tgtNode.type !== 'agent' && tgtNode.type !== 'mcp-server')) continue;
        // tgt is already an agent / mcp-server (guard above), so the top source
        // handle or the bottom target handle is unambiguously a provider wiring.
        const isProviderEdge = e.targetHandle === 'bottom' || e.sourceHandle === 'top';
        if (isProviderEdge) {
            toolAgentEdgeIds.add(e.id);
            if (!agentTools.has(e.target)) agentTools.set(e.target, []);
            agentTools.get(e.target)!.push(e.source);
        }
    }

    const attachedOnlyTools = new Set<string>();
    if (agentTools.size > 0) {
        const candidateTools = new Set<string>();
        for (const tids of agentTools.values()) for (const t of tids) candidateTools.add(t);
        for (const toolId of candidateTools) {
            const hasOther = edges.some(e =>
                !toolAgentEdgeIds.has(e.id) && (e.source === toolId || e.target === toolId)
            );
            if (!hasOther) attachedOnlyTools.add(toolId);
        }
    }

    // Per-agent vertical drop of its attached tool row. Agents referenced by an
    // interface-html-react node's code render an extra "Used by interface" badge
    // in their bottom stack (mirrors useInterfaceConsumers: a plain id-containment
    // check on jsx_source/content), so the row drops further. Used by the attach
    // positioning AND the unanchored-component stacking below (so fresh
    // disconnected nodes don't land inside the row).
    const interfaceCodes: string[] = [];
    for (const n of realNodes) {
        if (n.type !== 'interface-html-react') continue;
        const config = ((n.data as Record<string, unknown> | undefined)?.config ?? {}) as Record<string, unknown>;
        const jsx = typeof config.jsx_source === 'string' ? config.jsx_source : '';
        const html = typeof config.content === 'string' ? config.content : '';
        const code = `${jsx}\n${html}`;
        if (code.trim()) interfaceCodes.push(code);
    }
    const agentRowDrop = new Map<string, { drop: number; toolH: number }>();
    for (const [agentId, toolIds] of agentTools) {
        const attached = toolIds.filter(t => attachedOnlyTools.has(t));
        if (attached.length === 0) continue;
        const badge = interfaceCodes.some(code => code.includes(agentId));
        agentRowDrop.set(agentId, {
            drop: TOOL_ATTACH_V_GAP + (badge ? TOOL_ATTACH_BADGE_EXTRA : 0),
            toolH: Math.max(...attached.map(t => dimsMap.get(t)![1])),
        });
    }

    const layoutNodeIds = new Set([...nodeIds].filter(id => !attachedOnlyTools.has(id)));
    const layoutEdges = edges.filter(e => !toolAgentEdgeIds.has(e.id));

    const components = findConnectedComponents(layoutNodeIds, layoutEdges);

    const allPositions = new Map<string, { x: number; y: number }>();

    const hasRealAnchor = (nids: string[]) => {
        // True when any of these nodes has an explicit original position
        // (including (0, 0)) — otherwise a node legitimately at origin would
        // be misclassified as fresh and pushed into the stacking fallback.
        for (const nid of nids) {
            if (nodeMap.get(nid)?.position !== undefined) return true;
        }
        return false;
    };

    // For components whose anchor nodes have no real position (fresh/disconnected
    // nodes added without any prior layout), stack them vertically below the
    // previous one so they don't all collapse to (0,0).
    let nextUnanchoredY = 0;

    for (const comp of components) {
        const positions = layoutSubgraph(comp, nodeMap, layoutEdges, dimsMap, pinnedNodeIds);
        if (positions.size === 0) continue;

        // Shift the laid-out subgraph so its center matches the original center.
        // When pinnedNodeIds is set, anchor to pinned nodes' centroid only so
        // new nodes don't drag the centroid away from where existing nodes were.
        const anchorIds = pinnedNodeIds
            ? [...comp].filter(nid => pinnedNodeIds.has(nid) && positions.has(nid))
            : [...comp];
        if (anchorIds.length === 0) {
            // No pinned nodes in component (all new) — use all nodes
            for (const nid of comp) anchorIds.push(nid);
        }

        let dx: number;
        let dy: number;
        if (hasRealAnchor(anchorIds)) {
            let origSumX = 0, origSumY = 0;
            for (const nid of anchorIds) {
                const n = nodeMap.get(nid)!;
                origSumX += n.position?.x ?? 0;
                origSumY += n.position?.y ?? 0;
            }
            const origCx = origSumX / anchorIds.length;
            const origCy = origSumY / anchorIds.length;

            let layoutSumX = 0, layoutSumY = 0;
            for (const nid of anchorIds) {
                const p = positions.get(nid)!;
                layoutSumX += p.x;
                layoutSumY += p.y;
            }
            const layoutCx = layoutSumX / anchorIds.length;
            const layoutCy = layoutSumY / anchorIds.length;
            dx = origCx - layoutCx;
            dy = origCy - layoutCy;
        } else {
            // No anchor positions — stack below the previous unanchored component.
            const ys = [...positions.values()].map(p => p.y);
            const minY = ys.length ? Math.min(...ys) : 0;
            const maxY = ys.length ? Math.max(...ys) : 0;
            // Agents in this component may carry an attached tool row below
            // them (positioned after this loop) — extend the span so the next
            // stacked component doesn't land inside the row.
            let attachExtent = 0;
            for (const [aid, { drop, toolH }] of agentRowDrop) {
                if (positions.has(aid)) attachExtent = Math.max(attachExtent, drop + toolH);
            }
            dx = 0;
            dy = nextUnanchoredY - minY;
            nextUnanchoredY += (maxY - minY) + attachExtent + SUBGRAPH_GAP;
        }

        for (const [nid, p] of positions) {
            positions.set(nid, { x: p.x + dx, y: p.y + dy });
        }

        // Final position blend: pull pinned nodes toward their original positions.
        // This catches X displacement (from layer/compaction changes) that the
        // internal Y-stability blending cannot address.
        if (pinnedNodeIds) {
            for (const [nid, p] of positions) {
                if (pinnedNodeIds.has(nid)) {
                    const n = nodeMap.get(nid)!;
                    const origX = n.position?.x ?? p.x;
                    const origY = n.position?.y ?? p.y;
                    positions.set(nid, {
                        x: PINNED_POS_BLEND * p.x + (1 - PINNED_POS_BLEND) * origX,
                        y: PINNED_POS_BLEND * p.y + (1 - PINNED_POS_BLEND) * origY,
                    });
                }
            }
        }

        for (const [nid, pos] of positions) {
            allPositions.set(nid, pos);
        }
    }

    // ── Position attached tools centered below their consumers ──
    // Custom: a hosting-mode MCP node is itself attached below an agent,
    // and ITS providers attach below it — the inner row can only be placed
    // once the MCP node has a position, so loop until no row makes progress.
    const pendingRows = new Map(agentTools);
    while (pendingRows.size > 0) {
        let progressed = false;
        for (const [agentId, toolIds] of [...pendingRows]) {
            const tools = toolIds.filter(t => attachedOnlyTools.has(t)).sort();
            if (tools.length === 0) { pendingRows.delete(agentId); progressed = true; continue; }
            if (!allPositions.has(agentId)) continue;
            pendingRows.delete(agentId);
            progressed = true;

            const agentPos = allPositions.get(agentId)!;
            const [agentW, agentH] = dimsMap.get(agentId)!;
            const agentCx = agentPos.x + agentW / 2;

            // Flat row centered under the consumer. Attached tools have no
            // other edges by construction (see attachedOnlyTools), so nothing
            // hangs off them that could overlap a neighbor.
            const maxTw = Math.max(...tools.map(t => dimsMap.get(t)![0]));
            const hStep = maxTw + TOOL_ATTACH_H_GAP;

            const totalW = (tools.length - 1) * hStep + maxTw;
            const startX = agentCx - totalW / 2;
            const rowY = agentPos.y + agentH + agentRowDrop.get(agentId)!.drop;

            for (let i = 0; i < tools.length; i++) {
                allPositions.set(tools[i], {
                    x: startX + i * hStep,
                    y: rowY,
                });
            }
        }
        if (!progressed) break; // consumer never placed (kept original position)
    }

    // Return new Node[] with updated positions
    return nodes.map(node => {
        const newPos = allPositions.get(node.id);
        if (!newPos) return node; // sticky notes or unmatched nodes keep position
        return { ...node, position: newPos };
    });
}
