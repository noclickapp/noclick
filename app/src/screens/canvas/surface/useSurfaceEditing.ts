// What the canvas does with each change React Flow reports: steps added, moved, resized, selected and removed,
// connections made and removed, a connection dropped on a step's body. Each lands in the graph the canvas holds (its
// store, graph/liveGraphStore.ts) and in its undo history; the host hears what it passes on (other people editing live,
// the Interface tab's blocks, its own tombstones). Connections are judged by connectionRules.ts.
import { useCallback, useRef, type MutableRefObject, type RefObject } from 'react';
import {
    addEdge,
    applyEdgeChanges,
    applyNodeChanges,
    useReactFlow,
    type Connection,
    type Edge,
    type EdgeChange,
    type FinalConnectionState,
    type Node,
    type NodeChange,
    type NodeDimensionChange,
} from '@xyflow/react';
import { applyEdgeStyle } from '@/lib/edgeStyle';
import { hasValidPosition } from '../applyNodeUpdate';
import { resolveBodyDropConnection } from '../connectionDropSnap';
import { setGraphDragging } from '../graph/liveGraphStore';
import { fromHintHandleId } from '../nodes/NextStepHint';
import { perfState } from '../perfState';
import { consumePointerDrivenDelete } from '../pointerDelete';
import { connectionAllowed, normalizeConnection, type ConnectionRoles } from './connectionRules';

/** The canvas's undo history, as each edit records itself in it. */
export interface SurfaceHistory {
    /** The graph after an edit: one step back. */
    captureState: (nodes: Node[], edges: Edge[]) => void;
    /** A drag begins: what follows until `endBatch` is one step back. */
    startBatch: () => void;
    endBatch: (nodes: Node[], edges: Edge[]) => void;
}

/** What the host hears of each edit, beyond the graph it holds. */
export interface SurfaceListeners {
    /** A step removed (before the graph takes the removal). */
    removed?: (nodeId: string) => void;
    /** A step resized by its handles (a note), not measured again. */
    resized?: (nodeId: string, dimensions: { width: number; height: number }) => void;
    /** A step dragged to `position`, as it moves. */
    dragged?: (nodeId: string, position: { x: number; y: number }) => void;
    edgeAdded?: (edge: Edge) => void;
    edgeRemoved?: (edgeId: string) => void;
}

export interface SurfaceEditingOptions {
    /** The workflow, whose saves wait while a step is dragged. */
    workflowId: string | undefined;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    setEdges: (update: (edges: Edge[]) => Edge[]) => void;
    /** The graph as it stands, read where an edit judges it (refs: an edit sees the latest). */
    nodesRef: RefObject<Node[]>;
    edgesRef: RefObject<Edge[]>;
    history: SurfaceHistory;
    /** What each step is by its type, as connections are judged. */
    roles: ConnectionRoles;
    /** True while the canvas shows a copy it's still reading: nothing moves, resizes or connects. */
    syncingRef: RefObject<boolean>;
    /** Set while a step is dragged; the host reads it too. */
    draggingRef: MutableRefObject<boolean>;
    /** The canvas's element: it takes `perf-optimizing` while a step is dragged. */
    canvasRef: RefObject<HTMLElement | null>;
    /** Brings a step into view: the one a removal selects in its place. */
    panToNode: (nodeId: string) => void;
    /** Stacks the steps (notes under the rest). */
    layer: (nodes: Node[]) => Node[];
    /** Nodes that aren't steps (another person's pointer drawn as a node): their changes are no edits. */
    ignored?: (nodeId: string) => boolean;
    /** Only looked at (a replay of a run, a workflow its viewer may only view): steps are selected and measured, and
     *  nothing moves, resizes, connects or is removed. */
    frozen?: boolean;
    on?: SurfaceListeners;
}

export interface SurfaceEditing {
    isValidConnection: (connection: Connection | Edge) => boolean;
    onNodesChange: (changes: NodeChange[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection) => void;
    onConnectEnd: (event: MouseEvent | TouchEvent, state: FinalConnectionState) => void;
}

function clientPoint(event: MouseEvent | TouchEvent): { clientX: number; clientY: number } {
    return 'changedTouches' in event ? event.changedTouches[0] : event;
}

/** The step a single removal selects in its place: the nearest to its left, else the nearest. */
function nearestAfterRemoval(removed: Node | undefined, remaining: Node[]): Node | null {
    // Only positioned steps: one with no position throwing here would stop the whole update, and the step would never go.
    const steps = remaining.filter((n) => n.type !== 'stickyNote' && !n.id?.startsWith('cursor-') && hasValidPosition(n));
    if (!removed || !hasValidPosition(removed) || removed.type === 'stickyNote' || steps.length === 0) return null;
    const { x: rx, y: ry } = removed.position;
    const leftward = steps.filter((n) => n.position.x < rx);
    const pool = leftward.length > 0 ? leftward : steps;
    const dist = (n: Node) => Math.abs(n.position.x - rx) + Math.abs(n.position.y - ry);
    return pool.reduce((a, b) => (dist(b) < dist(a) ? b : a));
}

/** The canvas's editing handlers for React Flow (the module's header). Each reads the graph and the options as they are
 *  when it's called, and is a new function only when one it calls is (so React Flow's own updates follow the host's). */
export function useSurfaceEditing(options: SurfaceEditingOptions): SurfaceEditing {
    const latest = useRef(options);
    latest.current = options;
    const { getInternalNode, screenToFlowPosition } = useReactFlow();
    const { setNodes, setEdges, history, layer, panToNode, frozen, on } = options;
    const { captureState, startBatch, endBatch } = history;

    const isValidConnection = useCallback((connection: Connection | Edge) => {
        const { nodesRef, edgesRef, roles } = latest.current;
        return connectionAllowed(connection, nodesRef.current ?? [], edgesRef.current ?? [], roles);
    }, []);

    const onNodesChange = useCallback((incoming: NodeChange[]) => {
        const { workflowId, setNodes, edgesRef, history, syncingRef, draggingRef, canvasRef, panToNode, layer, ignored, frozen, on } = latest.current;
        let changes = incoming;
        // A frozen canvas is only looked at: steps are selected and measured, never moved, resized or removed (a step's
        // delete pill reaches here as React Flow's own removal).
        if (frozen) {
            changes = changes.filter((c) => c.type === 'select' || (c.type === 'dimensions' && typeof (c as NodeDimensionChange).resizing !== 'boolean'));
            if (changes.length === 0) return;
        }
        // A copy still being read is drawn, not edited.
        if (syncingRef.current) {
            changes = changes.filter((c) => c.type !== 'position' && c.type !== 'dimensions');
            if (changes.length === 0) return;
        }
        const steps = ignored ? changes.filter((c) => !('id' in c) || !ignored(c.id)) : changes;
        if (steps.length === 0) return;

        for (const change of steps) {
            if (change.type === 'remove') on?.removed?.(change.id);
        }
        // A resize by a note's handles carries `resizing`; a step measured again doesn't, and isn't passed on.
        for (const change of steps) {
            if (change.type === 'dimensions' && typeof (change as NodeDimensionChange).resizing === 'boolean') {
                const dims = (change as NodeDimensionChange).dimensions;
                if (dims) on?.resized?.(change.id, { width: dims.width, height: dims.height });
            }
        }

        const dragStart = steps.some((c) => c.type === 'position' && c.dragging === true);
        const dragEnd = steps.some((c) => c.type === 'position' && c.dragging === false);
        if (dragStart && !draggingRef.current) {
            draggingRef.current = true;
            if (workflowId) setGraphDragging(workflowId, true);
            canvasRef.current?.classList.add('perf-optimizing');
            perfState.shouldOptimize = true;
            history.startBatch();
        }

        setNodes((nds) => {
            let updated = applyNodeChanges(steps, nds);
            if (draggingRef.current) {
                for (const change of steps) {
                    if (change.type === 'position' && change.position) on?.dragged?.(change.id, change.position);
                }
            }
            // Stacking is worked out again once a drag lands, not on every frame of it.
            if (!(draggingRef.current && !dragEnd)) updated = layer(updated);

            // One step removed by a person: the selection moves to the step beside it, so where they were isn't lost.
            // A drag, a copy being read, or several removed at once (a build, a multi-select) keep their own.
            const removals = steps.filter((c) => c.type === 'remove');
            if (removals.length === 1 && !draggingRef.current && !syncingRef.current) {
                const removed = nds.find((n) => n.id === (removals[0] as { id: string }).id);
                const next = nearestAfterRemoval(removed, updated);
                if (next) {
                    updated = updated.map((n) => ({ ...n, selected: n.id === next.id }));
                    // Deleted with the pointer (the delete pill), the view stays where the pointer is; from the keyboard,
                    // it follows the selection.
                    if (!consumePointerDrivenDelete()) setTimeout(() => panToNode(next.id), 0);
                }
            }

            if (dragEnd && draggingRef.current) {
                draggingRef.current = false;
                if (workflowId) setGraphDragging(workflowId, false);
                canvasRef.current?.classList.remove('perf-optimizing');
                perfState.shouldOptimize = false;
                setTimeout(() => history.endBatch(updated, edgesRef.current ?? []), 0);
            } else if (!draggingRef.current && !dragStart) {
                setTimeout(() => history.captureState(updated, edgesRef.current ?? []), 0);
            }
            return updated;
        });
    }, [setNodes, layer, startBatch, endBatch, captureState, on?.dragged, on?.removed, on?.resized, panToNode]);

    const onEdgesChange = useCallback((incoming: EdgeChange[]) => {
        const { setEdges, nodesRef, history, frozen, on } = latest.current;
        const changes = frozen ? incoming.filter((c) => c.type === 'select') : incoming;
        if (changes.length === 0) return;
        for (const change of changes) {
            if (change.type === 'remove') on?.edgeRemoved?.(change.id);
        }
        setEdges((eds) => {
            const updated = applyEdgeChanges(changes, eds);
            setTimeout(() => history.captureState(nodesRef.current ?? [], updated), 0);
            return updated;
        });
    }, [setEdges, captureState, on?.edgeRemoved]);

    const onConnect = useCallback((raw: Connection) => {
        const { setNodes, setEdges, nodesRef, history, syncingRef, frozen, on } = latest.current;
        if (syncingRef.current || frozen) return;
        const params = normalizeConnection(raw);
        setEdges((eds) => {
            const next = addEdge(params, eds);
            const styled = applyEdgeStyle(next[next.length - 1]);
            const edges = [...next.slice(0, -1), styled];
            on?.edgeAdded?.(styled);
            setTimeout(() => history.captureState(nodesRef.current ?? [], edges), 0);
            return edges;
        });

        // A state manager into a code step's state input: the code reads it as its `state` input.
        if (params.targetHandle === 'state' && params.source && params.target) {
            const nodes = nodesRef.current ?? [];
            const source = nodes.find((n) => n.id === params.source);
            const target = nodes.find((n) => n.id === params.target);
            if (source?.type === 'state-manager' && target?.type === 'automation-serverless-function') {
                setNodes((nds) =>
                    nds.map((node) => {
                        if (node.id !== params.target) return node;
                        const data = node.data || {};
                        const config = (data.config as Record<string, unknown>) || {};
                        const inputs = Array.isArray(config.function_inputs) ? (config.function_inputs as Array<{ name: string; value: string }>) : [];
                        // An earlier connection's entry may be stale.
                        const others = inputs.filter((input) => input.name !== 'state');
                        return {
                            ...node,
                            data: { ...data, config: { ...config, function_inputs: [...others, { name: 'state', value: `{{${params.source}.state}}` }] } },
                        };
                    })
                );
            }
        }
    }, [setNodes, setEdges, captureState, on?.edgeAdded]);

    // A connection dragged onto a step's body (or an invalid handle) lands on the nearest handle it can take, so a drop
    // needn't hit the small dot; one dropped on a valid handle connected already (`onConnect`).
    const onConnectEnd = useCallback(
        (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
            const { frozen, syncingRef } = latest.current;
            if (frozen || syncingRef.current) return;
            if (state.isValid) return;
            const { fromNode, fromHandle } = state;
            if (!fromNode || !fromHandle) return;

            const { clientX, clientY } = clientPoint(event);
            // A mouse's mouseup is aimed at what's under the pointer; a touch's touchend at where the drag began.
            const el = 'changedTouches' in event ? document.elementFromPoint(clientX, clientY) : (event.target as Element | null);
            const dropNodeId = el?.closest('.react-flow__node')?.getAttribute('data-id');
            if (!dropNodeId || dropNodeId === fromNode.id) return;

            const internal = getInternalNode(dropNodeId);
            const handleBounds = internal?.internals.handleBounds;
            const candidates = (fromHandle.type === 'source' ? handleBounds?.target : handleBounds?.source) ?? [];
            if (!internal || candidates.length === 0) return;

            const origin = internal.internals.positionAbsolute;
            const realFromId = fromHintHandleId(fromHandle.id);
            const connection = resolveBodyDropConnection({
                fromNodeId: fromNode.id,
                fromNodeType: fromNode.type,
                fromHandleId: realFromId === undefined ? (fromHandle.id ?? null) : realFromId,
                fromHandleType: fromHandle.type,
                dropNodeId,
                dropPoint: screenToFlowPosition({ x: clientX, y: clientY }),
                candidates: candidates.map((h) => ({ id: h.id ?? null, x: origin.x + h.x + h.width / 2, y: origin.y + h.y + h.height / 2 })),
                isValidConnection,
            });
            if (connection) onConnect(connection);
        },
        [frozen, getInternalNode, screenToFlowPosition, isValidConnection, onConnect]
    );

    return { isValidConnection, onNodesChange, onEdgesChange, onConnect, onConnectEnd };
}
