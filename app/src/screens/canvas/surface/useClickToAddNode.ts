// Adding a step by a click, wherever the click is:
//
// 1. A step's "+" (`noclick:open-flow-helper-from-node`, from its next-step hint) remembers the step and the handle the
//    "+" hangs off, and opens the palette for a pick.
// 2. A connection's "+" (`noclick:insert-node-on-edge`) remembers the connection instead: the pick is spliced into it.
// 3. The pick (`noclick:add-connected-node`, from the palette or a hint that knows what it adds; or `add`) makes the
//    step: after the remembered step, on the side its handle points, connected to it and in a row with what already
//    hangs there; inside the remembered connection, what follows moved along to make room; or, with nothing remembered,
//    on its own in the middle of what's in view.
//
// Closing the palette forgets what was remembered. The host hears each thing done (the step, the connections, what
// moved), and says how its palette opens, closes and how much of the canvas it covers.
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Position, useStoreApi, type Edge, type Node } from '@xyflow/react';
import { toast } from 'sonner';
import { createStyledEdge } from '@/lib/edgeStyle';
import { generateNodeId } from '@/lib/nodeIdGenerator';
import { createWorkflowNode } from '../applyNodeUpdate';
import { useNextFrame } from '@/lib/useLater';
import { nodeSize, stepDimensions, typeSize, type StepSize } from './stepSize';

/** A step asked for: its type, with what the palette's search seeded and where it goes. */
export interface AddStepRequest {
    nodeType?: string;
    /** Picked from the keyboard, one after another: the palette stays, and the next pick chains off this step. */
    keepSearch?: boolean;
    /** Settings it starts with (a model the search named). */
    initialConfig?: Record<string, unknown> | null;
    /** The operation it starts on (one the search found). */
    initialOperation?: string | null;
    /** The step it goes after, named by the asker (a hint that adds without a pick), in place of a remembered one. */
    source?: ClickToAddSource;
    /** The new step's handle the connection lands on. Without it, a handle on the side facing the source is looked for
     *  on a step of the same type already drawn: name it when the first of a type must wire a certain way (a tool's top
     *  into an agent's `bottom`). */
    targetHandle?: string;
    /** The connection it's spliced into, named by the asker (a step dropped on a connection's "+"), in place of a
     *  remembered one. */
    insert?: ClickToInsertEdge;
    /** The connection runs from the new step to the source, `sourceHandle` being the new step's: a tool dropped on an
     *  agent is the connection's start (its `top`), the agent its end (its `bottom`). */
    reverseEdge?: { sourceHandle: string };
}

/** The step a pick goes after: the handle its "+" hangs off, the side that handle is on, and how far along that side
 *  (a branch's offset from the middle). */
export interface ClickToAddSource {
    nodeId: string;
    handleId: string | null;
    handlePosition: Position;
    handleOffsetFromCenter: number;
}

/** The connection a pick is spliced into (source → new → target), at `position` on the canvas. */
export interface ClickToInsertEdge {
    edgeId: string;
    source: string;
    target: string;
    sourceHandle: string | null;
    targetHandle: string | null;
    position: { x: number; y: number };
}

/** How a step was added: on its own, after a step, or into a connection; and whether the palette stays for the next. */
export interface StepAdded {
    how: 'standalone' | 'connected' | 'insert';
    chained: boolean;
}

export interface ClickToAddListeners {
    /** The step added, already in the graph with its connections. */
    added?: (node: Node, added: StepAdded) => void;
    /** A step already there moved to make room (a row re-centred, what follows an insert). */
    moved?: (nodeId: string, position: { x: number; y: number }) => void;
    edgeAdded?: (edge: Edge) => void;
    edgeRemoved?: (edgeId: string) => void;
}

export interface ClickToAddOptions {
    /** The steps as they stand, read when a pick lands. */
    nodesRef: RefObject<Node[]>;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    setEdges: (update: (edges: Edge[]) => Edge[]) => void;
    /** The palette picks come from. */
    palette: {
        /** Whether it's open: once it closes, what a pick was for is forgotten. */
        open: boolean;
        /** Opens it for a pick. */
        show: () => void;
        /** Closes it (the connection a pick was for is gone). */
        hide: () => void;
        /** How much of the canvas's height it covers, so a step added on its own lands in what's still in view. */
        covers?: () => number;
    };
    /** Brings a step into view. */
    panToNode: (nodeId: string) => void;
    on?: ClickToAddListeners;
}

export interface ClickToAdd {
    /** Adds the step asked for, as a pick does. */
    add: (request: AddStepRequest) => void;
    /** True while a step or a connection is remembered for the next pick. */
    primed: boolean;
}

/** Asks the canvas for a step from anywhere on the page (a palette drawn outside the canvas's own frame): the canvas's
 *  click-to-add hears it as a pick. */
export function requestStep(request: AddStepRequest): void {
    document.dispatchEvent(new CustomEvent('noclick:add-connected-node', { detail: request }));
}

// Clear space between the two steps' facing sides, measured edge to edge: measured from their corners, the gap would
// depend on the source's size (a wide agent left a sliver, a small step a gulf).
const NODE_GAP_H = 130;
// A little more between steps stacked vertically: a tools connection draws a chip at its middle, and labels hang below.
const NODE_GAP_V = 140;

// Half a typical step, so one added on its own lands centred on the point rather than hanging from it.
const STANDALONE_HALF_W = 90;
const STANDALONE_HALF_H = 45;
// How far each further step added on its own lands from the last, wrapping after a few so they never march off.
const STANDALONE_CASCADE_STEP = 36;
const STANDALONE_CASCADE_WRAP = 5;

/** The middle of the canvas still in view above the palette, in the canvas's own coordinates, read from React Flow's
 *  transform as it is now (wherever it's panned and zoomed). */
function computeStandalonePosition(state: { transform: readonly [number, number, number]; width: number; height: number }, covered: number, cascadeIndex: number): { x: number; y: number } {
    const [tx, ty, zoom] = state.transform;
    const paneW = state.width || 1200;
    const paneH = state.height || 800;
    const visibleH = Math.max(paneH - covered, 200);
    const cascade = (cascadeIndex % STANDALONE_CASCADE_WRAP) * STANDALONE_CASCADE_STEP;
    const screenX = paneW / 2 + cascade;
    const screenY = visibleH / 2 + cascade;
    return {
        x: (screenX - tx) / zoom - STANDALONE_HALF_W,
        y: (screenY - ty) / zoom - STANDALONE_HALF_H,
    };
}

// Stands in for the step being added while a row is laid out.
const NEW_NODE_KEY = '__new__';

/** Every step already on `sourceNode`'s handle, and the one being added, in one row centred on the source: their new
 *  places (the new step's under NEW_NODE_KEY). Placing only the new one would fan each addition out to one side, a
 *  fourth tool three places right of its agent. `reverse` says which end of the connection the row is on: tools point
 *  into their agent (the connection ends at it); everything else hangs off the source. */
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
    /** The coordinate the row shares (its distance from the source). */
    along: number;
    newSize: StepSize;
    nodes: Node[];
    edges: Edge[];
}): Map<string, { x: number; y: number }> {
    const siblingIds = edges
        .filter((e) => (reverse ? e.target === sourceNode.id && (e.targetHandle ?? null) === handleId : e.source === sourceNode.id && (e.sourceHandle ?? null) === handleId))
        .map((e) => (reverse ? e.source : e.target));

    // In the order the row already reads, the new step last.
    const siblings = siblingIds
        .map((id) => nodes.find((n) => n.id === id))
        .filter((n): n is Node => !!n)
        .sort((a, b) => a.position[axis] - b.position[axis]);

    const entries = [...siblings.map((n) => ({ id: n.id, size: nodeSize(n) })), { id: NEW_NODE_KEY, size: newSize }];

    const gap = axis === 'x' ? NODE_GAP_H : NODE_GAP_V;
    const extent = (s: StepSize) => (axis === 'x' ? s.width : s.height);
    const total = entries.reduce((sum, e) => sum + extent(e.size), 0) + gap * (entries.length - 1);

    const srcSize = nodeSize(sourceNode);
    const sourceCentre = axis === 'x' ? sourceNode.position.x + srcSize.width / 2 : sourceNode.position.y + srcSize.height / 2;

    const out = new Map<string, { x: number; y: number }>();
    let cursor = sourceCentre - total / 2;
    for (const e of entries) {
        out.set(e.id, axis === 'x' ? { x: cursor, y: along } : { x: along, y: cursor });
        cursor += extent(e.size) + gap;
    }
    return out;
}

/** Everything downstream of `startId`, so an insert moves the whole tail along rather than one step into the next.
 *  `stopId` (the step before the insert) is never among them: a connection looping back would drag that side too. */
function descendantsOf(startId: string, stopId: string, edges: Edge[]): Set<string> {
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

// A connection leaving one side of a step lands on the opposite side of the next.
const OPPOSITE_POSITION: Record<Position, Position> = {
    [Position.Top]: Position.Bottom,
    [Position.Bottom]: Position.Top,
    [Position.Left]: Position.Right,
    [Position.Right]: Position.Left,
};

/** A handle on the `desiredPosition` side of some step of `nodeType` already drawn, so the new step's connection lands
 *  on the right side; undefined when none is drawn or none has one (React Flow then picks the step's default). */
function pickTargetHandle(
    nodeLookup: { values(): Iterable<{ type?: string; internals: { handleBounds?: { target?: { id?: string | null; position: Position }[] | null } } }> },
    nodeType: string,
    desiredPosition: Position
): string | undefined {
    for (const node of nodeLookup.values()) {
        if (node.type !== nodeType) continue;
        const match = node.internals.handleBounds?.target?.find((h) => h.position === desiredPosition);
        if (match) return match.id ?? undefined;
    }
    return undefined;
}

export function useClickToAddNode(options: ClickToAddOptions): ClickToAdd {
    const latest = useRef(options);
    latest.current = options;
    const paletteOpen = options.palette.open;

    const [primed, setPrimed] = useState(false);
    const sourceRef = useRef<ClickToAddSource | null>(null);
    // Set while a connection is remembered; never together with a remembered step.
    const insertRef = useRef<ClickToInsertEdge | null>(null);
    // How many steps were added on their own, so each lands a little further on.
    const standaloneAddCountRef = useRef(0);
    // React Flow's store, read as a pick lands (handles' places, the transform) without drawing again for it.
    const storeApi = useStoreApi();
    const nextFrame = useNextFrame();

    // A step's "+".
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail;
            const nodeId = detail?.nodeId as string | undefined;
            if (!nodeId) return;
            sourceRef.current = {
                nodeId,
                handleId: detail?.handleId ?? null,
                handlePosition: (detail?.handlePosition as Position | undefined) ?? Position.Right,
                handleOffsetFromCenter: typeof detail?.offsetFromCenter === 'number' ? detail.offsetFromCenter : 0,
            };
            setPrimed(true);
            latest.current.palette.show();
        };
        document.addEventListener('noclick:open-flow-helper-from-node', handler);
        return () => document.removeEventListener('noclick:open-flow-helper-from-node', handler);
    }, []);

    // A connection's "+".
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
            setPrimed(true);
            latest.current.palette.show();
        };
        document.addEventListener('noclick:insert-node-on-edge', handler);
        return () => document.removeEventListener('noclick:insert-node-on-edge', handler);
    }, []);

    // The palette closed: what a pick was for is forgotten.
    useEffect(() => {
        if (!paletteOpen) {
            sourceRef.current = null;
            insertRef.current = null;
            setPrimed(false);
        }
    }, [paletteOpen]);

    const add = useCallback(
        (detail: AddStepRequest) => {
            const { nodesRef, setNodes, setEdges, palette, panToNode, on } = latest.current;
            const nodes = nodesRef.current ?? [];
            const nodeType = detail?.nodeType;
            if (!nodeType) return;
            // A remembered connection comes before a remembered step and a step on its own. A step dropped on a
            // connection's "+" names the connection itself.
            const insert = detail?.insert ?? insertRef.current;

            // Picks from the keyboard, one after another: the palette stays and the next chains off this one. A splice
            // is a single pick, so this doesn't apply to it.
            const keepSearch = !insert && !!detail?.keepSearch;

            // A workflow holds one error handler.
            if (nodeType === 'on-error' && nodes.some((n) => n.type === 'on-error')) {
                toast.error('Only one On Error node is allowed per workflow');
                return;
            }

            // The remembered connection's ends were removed before the pick: nothing to splice into.
            if (insert && !(nodes.some((n) => n.id === insert.source) && nodes.some((n) => n.id === insert.target))) {
                insertRef.current = null;
                setPrimed(false);
                palette.hide();
                return;
            }

            // A remembered step removed since lands the pick on its own.
            const source = !insert ? (detail?.source ?? sourceRef.current) : null;
            const sourceNode = source ? nodes.find((n) => n.id === source.nodeId) : undefined;
            const connected = !!source && !!sourceNode;

            let newPosition: { x: number; y: number };
            let targetHandle: string | undefined;
            // Steps already there that this add moves, in the same update as the add.
            let repositions: Map<string, { x: number; y: number }> | null = null;
            if (insert) {
                const added = typeSize(nodeType);
                const from = nodes.find((n) => n.id === insert.source);
                const to = nodes.find((n) => n.id === insert.target);
                // Centred on the connection's middle, then a real gap kept on each side: a short connection would
                // otherwise put it over both neighbours.
                let x = insert.position.x - added.width / 2;
                if (from) {
                    const fromRight = from.position.x + nodeSize(from).width;
                    x = Math.max(x, fromRight + NODE_GAP_H);
                }
                newPosition = { x, y: insert.position.y - added.height / 2 };
                if (to) {
                    const shiftBy = x + added.width + NODE_GAP_H - to.position.x;
                    if (shiftBy > 0) {
                        const ids = descendantsOf(insert.target, insert.source, storeApi.getState().edges);
                        repositions = new Map();
                        for (const n of nodes) {
                            if (!ids.has(n.id)) continue;
                            repositions.set(n.id, { x: n.position.x + shiftBy, y: n.position.y });
                        }
                    }
                }
            } else if (connected) {
                // A branch's handle sits a little off its side's middle: scaled up, the branches' steps land about a
                // step's height apart.
                const offsetAlongBranch = source!.handleOffsetFromCenter * 5;
                // Both boxes measured, so the gap reads the same whatever their sizes; across the gap, the new step is
                // centred on the source rather than sharing its corner.
                const src = nodeSize(sourceNode!);
                const added = typeSize(nodeType);
                const centredX = sourceNode!.position.x + src.width / 2 - added.width / 2 + offsetAlongBranch;
                const centredY = sourceNode!.position.y + src.height / 2 - added.height / 2 + offsetAlongBranch;
                // The way the row runs when the first place is taken.
                let spreadAxis: 'x' | 'y';
                switch (source!.handlePosition) {
                    case Position.Top:
                        newPosition = { x: centredX, y: sourceNode!.position.y - added.height - NODE_GAP_V };
                        spreadAxis = 'x';
                        break;
                    case Position.Bottom:
                        newPosition = { x: centredX, y: sourceNode!.position.y + src.height + NODE_GAP_V };
                        spreadAxis = 'x';
                        break;
                    case Position.Left:
                        newPosition = { x: sourceNode!.position.x - added.width - NODE_GAP_H, y: centredY };
                        spreadAxis = 'y';
                        break;
                    default:
                        newPosition = { x: sourceNode!.position.x + src.width + NODE_GAP_H, y: centredY };
                        spreadAxis = 'y';
                }
                const row = layoutSiblingRow({
                    sourceNode: sourceNode!,
                    handleId: source!.handleId,
                    reverse: !!detail?.reverseEdge,
                    axis: spreadAxis,
                    along: spreadAxis === 'x' ? newPosition.y : newPosition.x,
                    newSize: added,
                    nodes,
                    edges: storeApi.getState().edges,
                });
                // The row always places the new step.
                newPosition = row.get(NEW_NODE_KEY)!;
                row.delete(NEW_NODE_KEY);
                if (row.size > 0) repositions = row;
                // A reversed connection names the new step's handle itself: nothing to look for.
                targetHandle = detail?.reverseEdge
                    ? undefined
                    : (detail?.targetHandle ?? pickTargetHandle(storeApi.getState().nodeLookup, nodeType, OPPOSITE_POSITION[source!.handlePosition]));
            } else {
                newPosition = computeStandalonePosition(storeApi.getState(), palette.covers?.() ?? 0, standaloneAddCountRef.current++);
            }

            // No operation unless the search found one: the step's panel opens on the choice.
            const nodeData: Record<string, unknown> = nodeType === 'stickyNote' ? { content: '', color: 8 } : { credentialIds: {} };
            const initialOperation = detail?.initialOperation;
            if (initialOperation) nodeData.operation = initialOperation;
            const initialConfig = detail?.initialConfig;
            if (initialConfig && Object.keys(initialConfig).length > 0) {
                nodeData.config = { ...((nodeData.config as Record<string, unknown> | undefined) ?? {}), ...initialConfig };
            }

            const newNodeId = generateNodeId(nodeType);
            const newNode = createWorkflowNode(newNodeId, nodeType, newPosition, nodeData);
            if (nodeType === 'stickyNote') {
                newNode.style = { width: 200, height: 200 };
            } else if (nodeType.startsWith('interface-')) {
                // A block of a page is drawn at its own size.
                const dims = stepDimensions(nodeType);
                newNode.style = { width: dims?.width ?? 350, height: dims?.height ?? 200 };
            }

            // Added and selected in one update, so a click right after never races a selection made later; what the add
            // moves goes in the same pass, so the new step lands in real space rather than on top of them.
            setNodes((prev) =>
                [...prev, newNode].map((n) => {
                    const moved = n.id === newNodeId ? undefined : repositions?.get(n.id);
                    return moved ? { ...n, position: moved, selected: false } : { ...n, selected: n.id === newNodeId };
                })
            );
            // Told after the update, never from inside it: React may run an update twice, or for a render it drops.
            if (repositions) {
                for (const [id, position] of repositions) on?.moved?.(id, position);
            }
            if (insert) {
                // Spliced in: the connection goes, source → new keeps its source handle, new → target its target handle.
                const edgeIn = createStyledEdge({ source: insert.source, target: newNodeId, sourceHandle: insert.sourceHandle ?? undefined });
                const edgeOut = createStyledEdge({ source: newNodeId, target: insert.target, targetHandle: insert.targetHandle ?? undefined });
                setEdges((prev) => [...prev.filter((edge) => edge.id !== insert.edgeId), edgeIn, edgeOut]);
                on?.edgeRemoved?.(insert.edgeId);
                on?.edgeAdded?.(edgeIn);
                on?.edgeAdded?.(edgeOut);
            } else if (connected) {
                const reverse = detail?.reverseEdge;
                const newEdge = createStyledEdge(
                    reverse
                        ? { source: newNodeId, target: source!.nodeId, sourceHandle: reverse.sourceHandle, targetHandle: source!.handleId ?? undefined }
                        : { source: source!.nodeId, target: newNodeId, sourceHandle: source!.handleId ?? undefined, targetHandle }
                );
                setEdges((prev) => [...prev, newEdge]);
                on?.edgeAdded?.(newEdge);
            }
            on?.added?.(newNode, { how: insert ? 'insert' : connected ? 'connected' : 'standalone', chained: keepSearch });

            if (keepSearch) {
                // The next pick chains off this step.
                sourceRef.current = { nodeId: newNodeId, handleId: null, handlePosition: Position.Right, handleOffsetFromCenter: 0 };
                setPrimed(true);
                nextFrame(() => panToNode(newNodeId));
            } else {
                sourceRef.current = null;
                insertRef.current = null;
                setPrimed(false);
                // A step on its own isn't beside anything in view: it's brought into view, a frame later so the pan
                // doesn't compete with the step being drawn. A splice lands on the connection that was under the
                // pointer, and a connected step beside its source.
                if (!connected && !insert) nextFrame(() => panToNode(newNodeId));
            }
        },
        [storeApi, nextFrame]
    );

    // A pick, from wherever it's made.
    useEffect(() => {
        const handler = (e: Event) => add((e as CustomEvent<AddStepRequest>).detail);
        document.addEventListener('noclick:add-connected-node', handler);
        return () => document.removeEventListener('noclick:add-connected-node', handler);
    }, [add]);

    return { add, primed };
}
