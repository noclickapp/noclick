import { useEffect, useRef, useState } from 'react';
import { Position, useStoreApi, type Node, type Edge } from '@xyflow/react';
import { toast } from 'sonner';
import { EVENTS } from '~/lib/analytics-events';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelect';
import { getBlockTypeForNodeType } from '~/components/interface/blockRegistry';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import {
    createStyledEdge,
    DEFAULT_NODE_HEIGHT,
    DEFAULT_NODE_WIDTH,
} from '~/utils/workflowLayout';
import {
    getDimensionsByType,
    getNodeMetadata,
} from '~/components/workflow/nodes/nodeRegistry';
import type { WorkflowInterfaceHandle } from '~/components/interface/WorkflowInterface';

interface AddConnectedNodeDetail {
    nodeType?: string;
    keepSearch?: boolean;
    initialConfig?: Record<string, unknown> | null;
    initialOperation?: string | null;
    /** Explicit source for direct adds (e.g. the provider hint's one-click
     *  "add AI agent") — bypasses the primed-source flow so the helper never
     *  has to open in picker mode first. */
    source?: ClickToAddSource;
    /** Explicit target handle on the new node. pickTargetHandle can only
     *  discover handles from a live instance of the type — pass this when the
     *  wiring must be deterministic even for the first instance on canvas
     *  (provider top → agent 'bottom'). */
    targetHandle?: string;
    /** Splice the new node into this edge directly, without priming the picker
     *  first. The edge "+" click flow primes `insertRef` and completes on the
     *  next pick; a drop onto that "+" already knows the node, so it carries the
     *  splice in one event. */
    insert?: ClickToInsertEdge;
    /** Reverse the edge so it runs new → primed source instead of source → new,
     *  with `sourceHandle` naming the handle on the NEW node. Needed for the
     *  agent-tools drop: the dropped provider is the edge SOURCE (its 'top') and
     *  the agent the TARGET (its 'bottom'). */
    reverseEdge?: { sourceHandle: string };
}

// Clear space left BETWEEN the two nodes' facing edges. Measured edge-to-edge,
// not origin-to-origin: anchoring on position alone made the gap depend on the
// source's size, so a wide node (the 210px agent) left a ~10px sliver while a
// 90px node left ~130px.
const NODE_GAP_H = 130;
// Vertical stacks need a touch more: tool edges render a midpoint chip and node
// labels hang below the node box.
const NODE_GAP_V = 140;

// Half-extents of a typical node — biases a standalone placement so the node
// lands visually centred rather than top-left-anchored at the target point.
const STANDALONE_HALF_W = 90;
const STANDALONE_HALF_H = 45;
// Step between consecutive standalone adds so repeated clicks fan out instead
// of stacking exactly; wraps after a few steps so it never marches off-screen.
const STANDALONE_CASCADE_STEP = 36;
const STANDALONE_CASCADE_WRAP = 5;

// Flow-space position at the centre of the canvas area still visible above the
// FlowHelperView panel. Derived from the live ReactFlow transform so the node
// lands where the user is actually looking, regardless of pan/zoom.
function computeStandalonePosition(
    state: {
        transform: readonly [number, number, number];
        width: number;
        height: number;
    },
    flowHelperHeight: number,
    cascadeIndex: number
): { x: number; y: number } {
    const [tx, ty, zoom] = state.transform;
    const paneW = state.width || 1200;
    const paneH = state.height || 800;
    const visibleH = Math.max(paneH - flowHelperHeight, 200);
    const cascade =
        (cascadeIndex % STANDALONE_CASCADE_WRAP) * STANDALONE_CASCADE_STEP;
    const screenX = paneW / 2 + cascade;
    const screenY = visibleH / 2 + cascade;
    return {
        x: (screenX - tx) / zoom - STANDALONE_HALF_W,
        y: (screenY - ty) / zoom - STANDALONE_HALF_H,
    };
}

/** Live box of a node already on canvas — ReactFlow's measured size once it has
 *  rendered, else the type's declared dimensions. */
function nodeSize(node: Node): { width: number; height: number } {
    const measured = node.measured;
    if (measured?.width && measured?.height) {
        return { width: measured.width, height: measured.height };
    }
    return typeSize(node.type);
}

/** Declared box of a node type that isn't on canvas yet (nothing to measure).
 *  The registry's per-definition `dimensions` is the authoritative size the node
 *  components actually render at; workflowLayout's DEFAULT_NODE_* covers the
 *  standard automation node for types that declare none. */
function typeSize(type: string | undefined): { width: number; height: number } {
    const dims = type ? getDimensionsByType(type) : undefined;
    return dims
        ? { width: dims.width, height: dims.height }
        : { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
}

// Stands in for the not-yet-created node inside a sibling-row layout.
const NEW_NODE_KEY = '__new__';

/**
 * Lay every node already wired to `sourceNode`'s handle — plus the one being
 * added — into one row centred on the source, and return their new positions
 * (the new node under NEW_NODE_KEY).
 *
 * Placing only the new node isn't enough: each addition would fan out in a
 * single direction, so a fourth tool sat three slots to the right of its agent
 * instead of the row staying centred beneath it.
 *
 * `reverse` selects which end of the edge the siblings live on — tool providers
 * point INTO the agent (edge.target === agent), everything else hangs off it.
 */
function layoutSiblingRow({
    sourceNode,
    handleId,
    reverse,
    axis,
    along,
    newSize,
    nodes,
    edges,
}: {
    sourceNode: Node;
    handleId: string | null;
    reverse: boolean;
    axis: 'x' | 'y';
    /** The fixed coordinate shared by the row (its distance from the source). */
    along: number;
    newSize: { width: number; height: number };
    nodes: Node[];
    edges: Edge[];
}): Map<string, { x: number; y: number }> {
    const siblingIds = edges
        .filter((e) =>
            reverse
                ? e.target === sourceNode.id &&
                  (e.targetHandle ?? null) === handleId
                : e.source === sourceNode.id &&
                  (e.sourceHandle ?? null) === handleId
        )
        .map((e) => (reverse ? e.source : e.target));

    // Keep the row in the order it already reads on screen, new node last.
    const siblings = siblingIds
        .map((id) => nodes.find((n) => n.id === id))
        .filter((n): n is Node => !!n)
        .sort((a, b) => a.position[axis] - b.position[axis]);

    const entries = [
        ...siblings.map((n) => ({ id: n.id, size: nodeSize(n) })),
        { id: NEW_NODE_KEY, size: newSize },
    ];

    const gap = axis === 'x' ? NODE_GAP_H : NODE_GAP_V;
    const extent = (s: { width: number; height: number }) =>
        axis === 'x' ? s.width : s.height;
    const total =
        entries.reduce((sum, e) => sum + extent(e.size), 0) +
        gap * (entries.length - 1);

    const srcSize = nodeSize(sourceNode);
    const sourceCentre =
        axis === 'x'
            ? sourceNode.position.x + srcSize.width / 2
            : sourceNode.position.y + srcSize.height / 2;

    const out = new Map<string, { x: number; y: number }>();
    let cursor = sourceCentre - total / 2;
    for (const e of entries) {
        out.set(
            e.id,
            axis === 'x' ? { x: cursor, y: along } : { x: along, y: cursor }
        );
        cursor += extent(e.size) + gap;
    }
    return out;
}

/** Everything reachable downstream of `startId`, so an insert can push the whole
 *  tail of the flow right rather than shoving one node into its own successor.
 *  `stopId` (the insert's upstream node) is never included — a loop-back edge
 *  would otherwise drag the upstream side along too. */
function descendantsOf(
    startId: string,
    stopId: string,
    edges: Edge[]
): Set<string> {
    const out = new Set<string>([startId]);
    const queue = [startId];
    while (queue.length > 0) {
        const id = queue.shift()!;
        for (const e of edges) {
            if (e.source !== id) continue;
            if (e.target === stopId || out.has(e.target)) continue;
            out.add(e.target);
            queue.push(e.target);
        }
    }
    return out;
}

// Mirror of the source handle's side: an edge emerging from one side of a
// node should land on the opposite side of the target.
const OPPOSITE_POSITION: Record<Position, Position> = {
    [Position.Top]: Position.Bottom,
    [Position.Bottom]: Position.Top,
    [Position.Left]: Position.Right,
    [Position.Right]: Position.Left,
};

// Single-slot source pointer: set when the user clicks a node's "+" hint,
// consumed when they pick a target from the node picker.
interface ClickToAddSource {
    nodeId: string;
    handleId: string | null;
    handlePosition: Position;
    handleOffsetFromCenter: number;
}

// Single-slot edge-insert pointer: set when the user clicks an edge's "+"
// midpoint button, consumed when they pick a node from the picker. The picked
// node is spliced into the edge (source→new→target) at `position` (flow coords).
interface ClickToInsertEdge {
    edgeId: string;
    source: string;
    target: string;
    sourceHandle: string | null;
    targetHandle: string | null;
    position: { x: number; y: number };
}

interface UseClickToAddNodeParams {
    /** Live nodes ref (avoids stale-closure reads during async flows). */
    nodesRef: React.MutableRefObject<Node[]>;
    setNodes: (updater: (prev: Node[]) => Node[]) => void;
    setEdges: (updater: (prev: Edge[]) => Edge[]) => void;
    setSelectedNode: (node: Node | null) => void;
    setIsConfigViewExpanded: (expanded: boolean) => void;
    setFlowHelperActiveTab: (
        tab: 'home' | 'config' | 'credentials' | null
    ) => void;
    /** True while FlowHelperView is expanded — used to clear pending source on close. */
    isConfigViewExpanded: boolean;
    /** Marks a node as freshly added so the Config tab opens in Edit view. */
    setFreshlyDroppedNodeId: (nodeId: string | null) => void;
    broadcastNodeAdd: (node: Node) => void;
    /** Collab sync for the edge rewiring an insert performs (drop the spliced
     *  edge, add the two replacements) + the connected click-to-add edge. */
    broadcastEdgeAdd: (edge: Edge) => void;
    broadcastEdgeRemove: (edgeId: string) => void;
    workflowInterfaceRef: React.MutableRefObject<WorkflowInterfaceHandle | null>;
    /** Live FlowHelperView height — standalone click-adds land in the visible
     *  canvas area above the panel. */
    flowHelperHeightRef: React.MutableRefObject<number>;
    /** Pans/zooms the canvas to centre a node — focuses a standalone add. */
    panToNode: (nodeId: string) => void;
    /** Syncs a programmatic position change. An edge-insert slides downstream
     *  nodes right; without this they'd move only on the inserting client. */
    broadcastNodeDrag: (
        nodeId: string,
        position: { x: number; y: number }
    ) => void;
    logActivity: (event: string, props: Record<string, unknown>) => void;
    workflowId?: string;
}

// Wires the click-to-add pipeline:
//
// 1. `noclick:open-flow-helper-from-node` (dispatched by a node's "+" hint)
//    stashes a source pointer and opens the helper on the picker tab.
// 2. When the helper closes, the pending source is cleared so the next
//    open doesn't inherit a stale target.
// 3. `noclick:add-connected-node` (dispatched by the node preview's onClick)
//    creates the picked node and switches the helper to the config tab.
//    With a primed source the node lands 220px off the source handle with a
//    styled edge between them; with no source it lands standalone in the
//    centre of the visible canvas.
//
// Returns `clickToAddEnabled` (true while a source is primed) so the node
// picker can swap its drag-hint copy to advertise the connected flow.
export function useClickToAddNode({
    nodesRef,
    setNodes,
    setEdges,
    setSelectedNode,
    setIsConfigViewExpanded,
    setFlowHelperActiveTab,
    isConfigViewExpanded,
    setFreshlyDroppedNodeId,
    broadcastNodeAdd,
    broadcastEdgeAdd,
    broadcastEdgeRemove,
    workflowInterfaceRef,
    flowHelperHeightRef,
    panToNode,
    broadcastNodeDrag,
    logActivity,
    workflowId,
}: UseClickToAddNodeParams) {
    const [clickToAddEnabled, setClickToAddEnabled] = useState(false);
    const sourceRef = useRef<ClickToAddSource | null>(null);
    // Set while an edge-insert is primed; mutually exclusive with sourceRef.
    const insertRef = useRef<ClickToInsertEdge | null>(null);
    // Cascade counter for standalone adds so repeated clicks don't stack.
    const standaloneAddCountRef = useRef(0);
    // Lets the connect handler peek at live node handle bounds without subscribing.
    const storeApi = useStoreApi();

    // Handler 1: node hints the source
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail;
            const nodeId = detail?.nodeId as string | undefined;
            if (!nodeId) return;
            sourceRef.current = {
                nodeId,
                handleId: detail?.handleId ?? null,
                handlePosition:
                    (detail?.handlePosition as Position | undefined) ??
                    Position.Right,
                handleOffsetFromCenter:
                    typeof detail?.offsetFromCenter === 'number'
                        ? detail.offsetFromCenter
                        : 0,
            };
            setClickToAddEnabled(true);
            setIsConfigViewExpanded(true);
            setFlowHelperActiveTab('home');
        };
        document.addEventListener(
            'noclick:open-flow-helper-from-node',
            handler
        );
        return () =>
            document.removeEventListener(
                'noclick:open-flow-helper-from-node',
                handler
            );
    }, [setIsConfigViewExpanded, setFlowHelperActiveTab]);

    // Handler 1b: edge "+" button primes an insert. Opens the same picker as the
    // node-hint flow, but stashes the edge to splice into instead of a source
    // handle to chain off. The two pointers are mutually exclusive.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail;
            if (!detail?.edgeId || !detail?.source || !detail?.target) return;
            insertRef.current = {
                edgeId: detail.edgeId,
                source: detail.source,
                target: detail.target,
                sourceHandle: detail.sourceHandle ?? null,
                targetHandle: detail.targetHandle ?? null,
                position: detail.position ?? { x: 0, y: 0 },
            };
            sourceRef.current = null;
            setClickToAddEnabled(true);
            setIsConfigViewExpanded(true);
            setFlowHelperActiveTab('home');
        };
        document.addEventListener('noclick:insert-node-on-edge', handler);
        return () =>
            document.removeEventListener(
                'noclick:insert-node-on-edge',
                handler
            );
    }, [setIsConfigViewExpanded, setFlowHelperActiveTab]);

    // Clear pending source/insert when the helper closes
    useEffect(() => {
        if (!isConfigViewExpanded) {
            sourceRef.current = null;
            insertRef.current = null;
            setClickToAddEnabled(false);
        }
    }, [isConfigViewExpanded]);

    // Handler 2: picker picks a node → create it, connected to a primed
    // source or standalone in the visible canvas when nothing is primed.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent<AddConnectedNodeDetail>).detail;
            const nodeType = detail?.nodeType;
            if (!nodeType) return;
            // A primed insert (edge "+") splices the picked node into an existing
            // edge; it takes precedence over source-chaining and standalone adds.
            // A drop onto the edge "+" carries its own splice and never primes.
            const insert = detail?.insert ?? insertRef.current;

            // Keyboard sequence-add (node search): keep the search focused and chain
            // the next node off this one, instead of jumping into its config. An
            // insert is a one-shot splice, so sequence-add doesn't apply to it.
            const keepSearch = !insert && !!detail?.keepSearch;

            // Singleton-node guards — mirror the drag-drop path's checks.
            if (
                nodeType === 'on-error' &&
                nodesRef.current.some((n) => n.type === 'on-error')
            ) {
                toast.error('Only one On Error node is allowed per workflow');
                return;
            }

            // An insert whose edge endpoints were deleted mid-pick has nothing to
            // splice into — abort rather than wire a dangling node.
            if (
                insert &&
                !(
                    nodesRef.current.some((n) => n.id === insert.source) &&
                    nodesRef.current.some((n) => n.id === insert.target)
                )
            ) {
                insertRef.current = null;
                setClickToAddEnabled(false);
                setIsConfigViewExpanded(false);
                return;
            }

            // A primed source that was since deleted falls back to standalone.
            const source = !insert
                ? (detail?.source ?? sourceRef.current)
                : null;
            const sourceNode = source
                ? nodesRef.current.find((n) => n.id === source.nodeId)
                : undefined;
            const connected = !!source && !!sourceNode;

            // Insert: centre the new node on the edge midpoint. Connected: place
            // along the axis the source handle points, with the perpendicular axis
            // carrying the multi-handle branch offset (scaled 5x so the ~18px
            // visual split between conditional/iteration branches becomes a ~90px
            // separation, about a node-height). Standalone: drop it in the centre
            // of the visible canvas.
            let newPosition: { x: number; y: number };
            let targetHandle: string | undefined;
            // Existing nodes this add has to move: an insert pushes the downstream
            // flow right to make room; a connected add re-centres the row of
            // siblings on the handle. Applied in the same setNodes as the add.
            let repositions: Map<string, { x: number; y: number }> | null = null;
            if (insert) {
                const added = typeSize(nodeType);
                const from = nodesRef.current.find((n) => n.id === insert.source);
                const to = nodesRef.current.find((n) => n.id === insert.target);
                // Centre on the midpoint the user dropped at, then enforce a real
                // gap on each side — a tight edge would otherwise overlap both
                // neighbours.
                let x = insert.position.x - added.width / 2;
                if (from) {
                    const fromRight = from.position.x + nodeSize(from).width;
                    x = Math.max(x, fromRight + NODE_GAP_H);
                }
                newPosition = { x, y: insert.position.y - added.height / 2 };
                if (to) {
                    const shiftBy = x + added.width + NODE_GAP_H - to.position.x;
                    if (shiftBy > 0) {
                        const ids = descendantsOf(
                            insert.target,
                            insert.source,
                            storeApi.getState().edges
                        );
                        repositions = new Map();
                        for (const n of nodesRef.current) {
                            if (!ids.has(n.id)) continue;
                            repositions.set(n.id, {
                                x: n.position.x + shiftBy,
                                y: n.position.y,
                            });
                        }
                    }
                }
            } else if (connected) {
                const offsetAlongBranch = source!.handleOffsetFromCenter * 5;
                // Edge-to-edge spacing: measure both boxes so the visible gap is
                // the same whatever the two nodes' sizes are. The perpendicular
                // axis centres the new node on the source rather than aligning
                // their top-left corners — two differently-sized nodes looked
                // off-kilter when anchored on position alone.
                const src = nodeSize(sourceNode!);
                const added = typeSize(nodeType);
                const centredX =
                    sourceNode!.position.x +
                    src.width / 2 -
                    added.width / 2 +
                    offsetAlongBranch;
                const centredY =
                    sourceNode!.position.y +
                    src.height / 2 -
                    added.height / 2 +
                    offsetAlongBranch;
                // Axis the new node fans out along when the first spot is taken.
                let spreadAxis: 'x' | 'y';
                switch (source!.handlePosition) {
                    case Position.Top:
                        newPosition = {
                            x: centredX,
                            y:
                                sourceNode!.position.y -
                                added.height -
                                NODE_GAP_V,
                        };
                        spreadAxis = 'x';
                        break;
                    case Position.Bottom:
                        newPosition = {
                            x: centredX,
                            y: sourceNode!.position.y + src.height + NODE_GAP_V,
                        };
                        spreadAxis = 'x';
                        break;
                    case Position.Left:
                        newPosition = {
                            x: sourceNode!.position.x - added.width - NODE_GAP_H,
                            y: centredY,
                        };
                        spreadAxis = 'y';
                        break;
                    default:
                        newPosition = {
                            x: sourceNode!.position.x + src.width + NODE_GAP_H,
                            y: centredY,
                        };
                        spreadAxis = 'y';
                }
                // Re-lay the WHOLE row of siblings on this handle (the existing
                // ones plus this one) centred on the source. Placing only the new
                // node meant each addition marched off in one direction and left
                // the row lopsided under its agent.
                const row = layoutSiblingRow({
                    sourceNode: sourceNode!,
                    handleId: source!.handleId,
                    reverse: !!detail?.reverseEdge,
                    axis: spreadAxis,
                    along: spreadAxis === 'x' ? newPosition.y : newPosition.x,
                    newSize: added,
                    nodes: nodesRef.current,
                    edges: storeApi.getState().edges,
                });
                // layoutSiblingRow always places NEW_NODE_KEY — it appends the
                // entry itself, so this lookup is total.
                newPosition = row.get(NEW_NODE_KEY)!;
                row.delete(NEW_NODE_KEY);
                if (row.size > 0) repositions = row;
                // Pick a target handle on the side opposite the source. We can't
                // statically know a node type's handle layout, so we peek at any
                // live instance of the same type for a target handle at that
                // position; if none exists, fall back to ReactFlow's default
                // (typically the left input). This generalizes the tool/mcp/etc.
                // top → agent.bottom wiring to any node type that exposes a
                // matching handle.
                // A reversed edge names the new node's handle itself, so there's
                // nothing to discover — the new node is the source, not the target.
                targetHandle = detail?.reverseEdge
                    ? undefined
                    : (detail?.targetHandle ??
                      pickTargetHandle(
                          storeApi.getState().nodeLookup,
                          nodeType,
                          OPPOSITE_POSITION[source!.handlePosition]
                      ));
            } else {
                newPosition = computeStandalonePosition(
                    storeApi.getState(),
                    flowHelperHeightRef.current,
                    standaloneAddCountRef.current++
                );
            }

            // No default operation by default. Operation-search hits can pass
            // initialOperation explicitly so the picked action opens selected.
            const nodeData: Record<string, unknown> =
                nodeType === 'stickyNote'
                    ? { content: '', color: 8 }
                    : { credentialIds: {} };

            // Picker-supplied seed (e.g. Agent tile clicked while a CLI/model
            // query is in the search bar) — mirrors the drag-drop path.
            const initialOperation = detail?.initialOperation;
            if (initialOperation) {
                nodeData.operation = initialOperation;
            }
            const initialConfig = detail?.initialConfig;
            if (initialConfig && Object.keys(initialConfig).length > 0) {
                nodeData.config = {
                    ...(nodeData.config ?? {}),
                    ...initialConfig,
                };
            }

            const newNodeId = generateNodeId(nodeType);
            const newNode = createWorkflowNode(
                newNodeId,
                nodeType,
                newPosition,
                nodeData
            );
            if (nodeType === 'stickyNote') {
                newNode.style = { width: 200, height: 200 };
            } else if (nodeType.startsWith('interface-')) {
                const nodeDef = getNodeMetadata(nodeType);
                newNode.style = {
                    width: nodeDef?.dimensions.width ?? 350,
                    height: nodeDef?.dimensions.height ?? 200,
                };
            }

            logActivity(EVENTS.NODE_ADDED, {
                node_id: newNodeId,
                node_type: nodeType,
                workflow_id: workflowId,
                source: insert
                    ? 'click_to_add_insert'
                    : connected
                      ? 'click_to_add'
                      : 'click_to_add_standalone',
            });

            // Add node and mark it selected in a single update so a quick
            // follow-up click doesn't race with a deferred selection. A
            // programmatic select never opens the config view (only a real
            // node click does), so sequence-add keeps the node search focused.
            // An insert also slides the downstream nodes right in the same pass,
            // so the new node lands in real space rather than on top of them.
            setNodes((prev) =>
                [...prev, newNode].map((n) => {
                    const moved =
                        n.id === newNodeId ? undefined : repositions?.get(n.id);
                    return moved
                        ? { ...n, position: moved, selected: false }
                        : { ...n, selected: n.id === newNodeId };
                })
            );
            // Broadcast AFTER the update, never from inside the updater — React
            // re-invokes updaters (StrictMode, discarded concurrent renders), and
            // a broadcast in there would fire twice, or fire for a render that
            // never commits.
            if (repositions) {
                for (const [id, position] of repositions) {
                    broadcastNodeDrag(id, position);
                }
            }
            if (insert) {
                // Splice the new node into the edge: drop the original edge, then
                // wire source→new (keeping the original source handle) and
                // new→target (keeping the original target handle).
                const edgeIn = createStyledEdge({
                    source: insert.source,
                    target: newNodeId,
                    sourceHandle: insert.sourceHandle ?? undefined,
                });
                const edgeOut = createStyledEdge({
                    source: newNodeId,
                    target: insert.target,
                    targetHandle: insert.targetHandle ?? undefined,
                });
                setEdges((prev) => [
                    ...prev.filter((edge) => edge.id !== insert.edgeId),
                    edgeIn,
                    edgeOut,
                ]);
                broadcastEdgeRemove(insert.edgeId);
                broadcastEdgeAdd(edgeIn);
                broadcastEdgeAdd(edgeOut);
            } else if (connected) {
                const reverse = detail?.reverseEdge;
                const newEdge = createStyledEdge(
                    reverse
                        ? {
                              source: newNodeId,
                              target: source!.nodeId,
                              sourceHandle: reverse.sourceHandle,
                              targetHandle: source!.handleId ?? undefined,
                          }
                        : {
                              source: source!.nodeId,
                              target: newNodeId,
                              sourceHandle: source!.handleId ?? undefined,
                              targetHandle,
                          }
                );
                setEdges((prev) => [...prev, newEdge]);
                broadcastEdgeAdd(newEdge);
            }
            broadcastNodeAdd(newNode);

            // Auto-select credentials (cache-first + background refresh) — parity
            // with the drag-drop path so click-added nodes get the same default.
            if (nodeType !== 'stickyNote') {
                autoSelectCredentialsForNewNode(
                    newNode,
                    setNodes,
                    workflowId ?? null
                );
            }

            // Reverse auto-sync for interface nodes — parity with drag-drop path
            if (nodeType.startsWith('interface-')) {
                const blockType = getBlockTypeForNodeType(nodeType);
                if (blockType)
                    workflowInterfaceRef.current?.addBlock(
                        newNodeId,
                        blockType
                    );
            }

            if (keepSearch) {
                // Sequence-add: re-prime the source to the just-added node so the
                // next one chains off it, and leave the search focused (no config
                // switch / freshly-dropped autofocus).
                sourceRef.current = {
                    nodeId: newNodeId,
                    handleId: null,
                    handlePosition: Position.Right,
                    handleOffsetFromCenter: 0,
                };
                setClickToAddEnabled(true);
                // Centre the new node like an arrow-key move (highlight + pan).
                requestAnimationFrame(() => panToNode(newNodeId));
            } else {
                // Consume source/insert + switch to config so user can immediately set up the new node.
                // Mark as freshly dropped so the Config tab opens in Edit view.
                sourceRef.current = null;
                insertRef.current = null;
                setClickToAddEnabled(false);
                setFreshlyDroppedNodeId(newNodeId);
                setSelectedNode(newNode);
                setFlowHelperActiveTab('config');

                // A standalone add isn't anchored to anything already in view, so
                // pan/zoom the canvas to centre the new node. Defer one frame so
                // the node-mount + config-panel renders commit first — panning in
                // the same tick makes the animation compete with those renders and
                // stutter. Mirrors the deferred-pan pattern used by deep-link and
                // errored-node navigation. (panToNode retries until the node is
                // rendered, so it's safe even if the commit isn't done yet.) An
                // insert lands on the hovered edge (already in view) — no pan.
                if (!connected && !insert)
                    requestAnimationFrame(() => panToNode(newNodeId));
            }
        };
        document.addEventListener('noclick:add-connected-node', handler);
        return () =>
            document.removeEventListener('noclick:add-connected-node', handler);
    }, [
        nodesRef,
        setNodes,
        setEdges,
        setSelectedNode,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setFreshlyDroppedNodeId,
        broadcastNodeAdd,
        broadcastEdgeAdd,
        broadcastEdgeRemove,
        workflowInterfaceRef,
        flowHelperHeightRef,
        panToNode,
        broadcastNodeDrag,
        logActivity,
        workflowId,
        storeApi,
    ]);

    return { clickToAddEnabled, sourceRef };
}

// Look up a target handle id at the given position on any existing node of
// `nodeType`, so the edge for a click-to-add lands on the right side instead
// of the default input. Returns `undefined` when no live instance has a
// matching handle (or no instance of the type exists yet).
function pickTargetHandle(
    nodeLookup: {
        values(): Iterable<{
            type?: string;
            internals: {
                handleBounds?: {
                    target?: { id?: string | null; position: Position }[] | null;
                };
            };
        }>;
    },
    nodeType: string,
    desiredPosition: Position
): string | undefined {
    for (const node of nodeLookup.values()) {
        if (node.type !== nodeType) continue;
        const match = node.internals.handleBounds?.target?.find(
            (h) => h.position === desiredPosition
        );
        if (match) return match.id ?? undefined;
    }
    return undefined;
}
