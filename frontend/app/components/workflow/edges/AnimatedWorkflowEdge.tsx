/**
 * Custom animated edge that shows a traveling circle when data flows through.
 * Used to visualize workflow execution progress in real-time.
 *
 * For "backward" edges (target to the left of source), creates a curved path
 * that routes around nodes instead of cutting diagonally through them.
 */
import React, { memo, useEffect, useRef, useState } from 'react';
import {
    BaseEdge,
    Edge,
    EdgeLabelRenderer,
    EdgeProps,
    getBezierPath,
    Position,
    useReactFlow,
    useStore,
} from '@xyflow/react';
import { Plus, Trash2, Wrench } from 'lucide-react';
import { NODE_DELETE_BTN_CLASSES } from '../nodes/nodeChrome';
import { CanvasDropTarget } from '~/components/workflow/CanvasDropTarget';
// From the schema-free leaf: this edge renders inside the marketing canvas
// previews, whose chunk must not pull the full ~9MB schema registry.
import { isAgentToolProviderType } from '~/utils/nodeMeta';
import { getBackwardEdgePath, BACKWARD_EDGE_X_THRESHOLD } from '~/utils/edgePaths';

// "Insert node here" button — a rounded SQUARE (vs the round delete pill) so the
// two midpoint actions read distinctly. Neutral zinc hover, no colour cue.
// Clicking it opens the node picker primed to splice the picked node into this
// edge (see useClickToAddNode's insert flow).
const NODE_INSERT_BTN_CLASSES =
    'w-[25px] h-[25px] rounded-[7px] flex items-center justify-center text-foreground/80 bg-card backdrop-blur-sm border border-border/60 dark:border-zinc-700/60 shadow-[0_2px_8px_rgba(0,0,0,0.4)] transition-colors duration-200 hover:bg-accent dark:hover:bg-zinc-700 hover:text-foreground hover:border-muted-foreground/40 dark:hover:border-zinc-500 hover:shadow-[0_4px_12px_rgba(0,0,0,0.5)] active:scale-95';

// Hit box for the midpoint drop target. Bigger than the 25px "+" so it's an easy
// drop, small enough that dnd-kit's smallest-area-wins collision still lets a
// near-miss land on the canvas instead of splicing the edge.
const EDGE_DROP_HIT_SIZE = 40;

/**
 * Custom data type for animated workflow edges.
 * Contains animation state used to trigger visual effects during workflow execution.
 */
type AnimatedEdgeData = {
    isAnimating?: boolean;
};

type AnimatedEdge = Edge<AnimatedEdgeData>;

// Backward-edge routing lives in ~/utils/edgePaths (leaf module) so the
// workflow-browser preview can share it; re-exported for existing importers.
export { getBackwardEdgePath };

function AnimatedWorkflowEdge({
    id,
    source,
    target,
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    sourceHandleId,
    targetHandleId,
    style = {},
    markerEnd,
    data,
    selected,
}: EdgeProps<AnimatedEdge>) {
    // Detect if this is a "backward" edge (target is to the left of source)
    // Only applies to horizontal edges (Left→Right). Vertical edges (e.g. Tool→Agent
    // bottom/top connections) should always use the standard bezier path.
    const isVerticalEdge = sourcePosition === Position.Top || sourcePosition === Position.Bottom
        || targetPosition === Position.Top || targetPosition === Position.Bottom;
    const isBackwardEdge = !isVerticalEdge && targetX < sourceX - BACKWARD_EDGE_X_THRESHOLD;

    // Compute bezier midpoint regardless of routing — used both as the edge
    // path for forward edges and as the delete-button anchor for forward edges.
    const [bezierPath, bezierLabelX, bezierLabelY] = getBezierPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
    });

    // Use custom path for backward edges, standard bezier for forward edges
    const edgePath = isBackwardEdge
        ? getBackwardEdgePath(sourceX, sourceY, targetX, targetY)
        : bezierPath;

    // Anchor for the hover delete button. Backward edges loop under the nodes,
    // so we put the button at the bottom of that loop instead of the (empty)
    // straight midpoint between source and target.
    const labelX = isBackwardEdge ? (sourceX + targetX) / 2 : bezierLabelX;
    const labelY = isBackwardEdge
        ? Math.max(sourceY, targetY) + 117
        : bezierLabelY;

    const isAnimating = data?.isAnimating || false;
    const animateRef = useRef<SVGAnimateMotionElement>(null);
    const opacityAnimateRef = useRef<SVGAnimateElement>(null);
    const prevIsAnimatingRef = useRef<boolean | undefined>(undefined);

    // Two hover sources so the button doesn't disappear when the cursor moves
    // from the edge path onto the button itself — EdgeLabelRenderer portals the
    // button outside the <g>, so leaving the edge unmounts it mid-travel.
    const [isEdgeHovered, setIsEdgeHovered] = useState(false);
    const [isButtonHovered, setIsButtonHovered] = useState(false);
    const isReadOnly =
        (data as { isReadOnly?: boolean } | undefined)?.isReadOnly === true;
    const showDelete = !isReadOnly && (isEdgeHovered || isButtonHovered);
    const { deleteElements } = useReactFlow();

    // Top→bottom edges carry TOOLS into an agent (ToolNode/MCP/alarm/filesystem
    // and integration tool providers), not dataflow — label them so the two
    // edge kinds are distinguishable at a glance. Hidden while the delete
    // button occupies the same midpoint anchor. Integration providers show
    // their allowlisted-action count ("0 tools" included) and turn amber when
    // the provider node itself is incomplete (missing credentials / empty
    // allowlist) — the wiring exists but the agent gets nothing usable.
    // Read via a useStore SUBSCRIPTION (not getNode(): the edge is memoized
    // and node-data changes don't touch its props). The selector encodes its
    // result as one primitive string so Object.is keeps re-renders scoped to
    // actual changes (an object return would have a fresh identity per flush).
    const isToolEdge = sourceHandleId === 'top' && targetHandleId === 'bottom';
    const providerState = useStore((s) => {
        if (!isToolEdge) return '';
        const node = s.nodeLookup.get(source);
        if (!node) return '';
        // Hosting-mode MCP → agent: the bundle's count is the SUM of its
        // bottom-wired providers' allowlists; incomplete if any provider (or
        // the MCP node itself) is. External mode (no wired providers) keeps
        // the generic 'tools' label — external tool counts aren't knowable
        // without connecting.
        if (node.type === 'mcp-server') {
            let count = 0;
            let any = false;
            let incomplete =
                (node.data as Record<string, unknown> | undefined)
                    ?.configValid === false;
            for (const e of s.edges) {
                if (e.target !== source || e.targetHandle !== 'bottom')
                    continue;
                const p = s.nodeLookup.get(e.source);
                if (!p || !isAgentToolProviderType(p.type)) continue;
                any = true;
                const pOps = (
                    p.data?.config as Record<string, unknown> | undefined
                )?.agent_tool_operations;
                count += Array.isArray(pOps) ? pOps.length : 0;
                if (
                    (p.data as Record<string, unknown> | undefined)
                        ?.configValid === false
                )
                    incomplete = true;
            }
            return any ? `${count}:${incomplete ? 1 : 0}` : '';
        }
        if (!isAgentToolProviderType(node.type)) return '';
        const data = node.data as Record<string, unknown> | undefined;
        const config = data?.config as Record<string, unknown> | undefined;
        const ops = config?.agent_tool_operations;
        const count = Array.isArray(ops) ? ops.length : 0;
        const incomplete = data?.configValid === false;
        return `${count}:${incomplete ? 1 : 0}`;
    });
    const [providerToolCount, providerIncompleteRaw] = providerState
        ? [
              Number(providerState.split(':')[0]),
              providerState.split(':')[1] === '1',
          ]
        : [null, false];
    // In a read-only preview the allowlist isn't picked yet (bare scaffold), so a
    // "0 tools" / incomplete-amber chip reads as broken. Fall back to the generic
    // "tools" label and drop the warning there; on the editor both stay a real
    // "wire it up" signal.
    const previewBare = isReadOnly && providerToolCount === 0;
    const providerIncomplete = providerIncompleteRaw && !isReadOnly;
    // Legacy tool sources (ToolNode/MCP/alarm/filesystem) have no countable
    // allowlist — keep the generic label for them; ditto a bare read-only preview.
    const toolEdgeLabel =
        providerToolCount !== null && !previewBare
            ? `${providerToolCount} tool${providerToolCount === 1 ? '' : 's'}`
            : 'tools';

    // Restart animation programmatically when isAnimating changes from false to true
    useEffect(() => {
        const wasAnimating = prevIsAnimatingRef.current;

        // Only trigger animation when transitioning from false to true (not on initial mount)
        if (
            wasAnimating === false &&
            isAnimating &&
            animateRef.current &&
            opacityAnimateRef.current
        ) {
            console.log(
                `[AnimatedWorkflowEdge] Restarting animation for edge ${id}`
            );
            // Force restart both animations
            animateRef.current.beginElement();
            opacityAnimateRef.current.beginElement();
        }

        // Update previous value for next render
        prevIsAnimatingRef.current = isAnimating;
    }, [isAnimating, id]);

    // Force the stroke to --canvas-edge (white in dark, soft gray in
    // light) regardless of the color baked into stored edges — historically all
    // edges were created with a hardcoded white stroke, invisible on the light
    // canvas. Dark mode is unchanged (--canvas-edge = white). The selection cue is a
    // soft blurred halo (below) rather than a recolor, so the line stays uniform.
    const effectiveStyle = {
        ...style,
        stroke: 'hsl(var(--canvas-edge))',
        ...(selected ? { opacity: 1 } : {}),
    };

    return (
        <g
            onMouseEnter={() => setIsEdgeHovered(true)}
            onMouseLeave={() => setIsEdgeHovered(false)}
        >
            {selected && (
                <path
                    d={edgePath}
                    fill="none"
                    strokeOpacity={0.22}
                    strokeWidth={12}
                    strokeLinecap="round"
                    style={{
                        pointerEvents: 'none',
                        filter: 'blur(3.5px)',
                        stroke: 'hsl(var(--canvas-edge))',
                    }}
                />
            )}
            <BaseEdge
                id={id}
                path={edgePath}
                style={effectiveStyle}
                markerEnd={markerEnd}
            />

            {/* Invisible wider path purely for hover detection — the rendered
                edge is 1-2px so it's hard to hit. This 20px stroke gives a
                forgiving hit zone without changing what's drawn. */}
            <path
                d={edgePath}
                fill="none"
                stroke="transparent"
                strokeWidth={20}
                style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
            />

            {/* Always render circle, but control visibility with opacity animation */}
            <circle
                r="6"
                opacity="0"
                style={{
                    pointerEvents: 'none',
                    fill: 'hsl(var(--canvas-edge))',
                }}
            >
                <animateMotion
                    ref={animateRef}
                    dur="0.8s"
                    path={edgePath}
                    rotate="auto"
                    repeatCount="1"
                    fill="freeze"
                    begin="indefinite"
                />
                {/* Fade in/out for smoother appearance */}
                <animate
                    ref={opacityAnimateRef}
                    attributeName="opacity"
                    values="0;1;1;0"
                    keyTimes="0;0.1;0.9;1"
                    dur="0.8s"
                    fill="freeze"
                    begin="indefinite"
                />
            </circle>

            {/* Tool edges keep ONE persistent anchored container that owns its
                hover state and swaps chip ↔ delete button. The chip must be
                hoverable itself: with pointer-events none, hover only counted
                over the edge's invisible 20px hit path BEHIND the chip — on
                near-vertical tool edges the chip's ends stick out of that
                corridor, so hovering them never revealed the delete button.
                Persisting the container across the swap keeps mouseleave
                firing (an unmounting chip can't deliver one). zIndex 1000:
                EdgeLabelRenderer's container can render UNDER the SVG edges
                layer, occluding the chip / swallowing clicks. */}
            {isToolEdge && (
                <EdgeLabelRenderer>
                    <div
                        className="nodrag nopan"
                        onMouseEnter={() =>
                            !isReadOnly && setIsButtonHovered(true)
                        }
                        onMouseLeave={() => setIsButtonHovered(false)}
                        style={{
                            position: 'absolute',
                            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
                            pointerEvents: isReadOnly ? 'none' : 'all',
                            zIndex: 1000,
                        }}
                    >
                        {/* The chip stays mounted as the container's SIZE-GIVER
                            (visibility-hidden while delete shows) with the button
                            absolutely centered over it. Swapping children outright
                            shrank the container mid-hover, and a fast-moving cursor
                            could miss the layout-induced mouseleave — leaving the
                            delete button stuck until the next hover cycle. */}
                        <div
                            className={`flex items-center gap-1 px-1.5 py-px rounded-full bg-popover/95 border text-[9px] font-medium select-none ${
                                providerIncomplete
                                    ? 'border-amber-500/50 text-amber-600 dark:text-amber-400'
                                    : 'border-border dark:border-zinc-700/60 text-muted-foreground'
                            }`}
                            style={{
                                visibility: showDelete ? 'hidden' : 'visible',
                            }}
                            title={
                                providerIncomplete
                                    ? 'Provider node is incomplete — connect credentials / select actions'
                                    : undefined
                            }
                        >
                            <Wrench size={8} />
                            {toolEdgeLabel}
                        </div>
                        {showDelete && (
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    deleteElements({ edges: [{ id }] });
                                }}
                                className={NODE_DELETE_BTN_CLASSES}
                                style={{
                                    position: 'absolute',
                                    left: '50%',
                                    top: '50%',
                                    transform: 'translate(-50%, -50%)',
                                }}
                                title="Delete edge"
                            >
                                <Trash2 size={12} />
                            </button>
                        )}
                    </div>
                </EdgeLabelRenderer>
            )}

            {/* Always-mounted drop target at the midpoint: dropping a palette node
                here splices it into the edge, same as clicking the "+". It can't
                hang off the hover-revealed "+" below — that one needs a real mouse
                hover, which never happens mid-drag (the pointer is on the drag
                overlay), so during a drag this renders its OWN "+" the moment a
                node drag starts. Without it every insert target is invisible while
                dragging and there's nothing to aim at. pointer-events stay off so
                it never interferes with edge hover or clicks; dnd-kit hit-tests the
                rect, not the pointer target. */}
            {!isReadOnly && !isToolEdge && (
                <EdgeLabelRenderer>
                    {/* The positioning transform MUST live on this wrapper, not on
                        the droppable itself: dnd-kit measures droppables with
                        getTransformAgnosticClientRect, which strips the element's
                        own transform — putting it on the droppable made dnd-kit
                        measure this target back at the renderer's origin (hundreds
                        of px away), so drops on the "+" never registered. */}
                    <div
                        className="nodrag nopan pointer-events-none"
                        style={{
                            position: 'absolute',
                            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
                            zIndex: 1001,
                        }}
                    >
                        <CanvasDropTarget
                            id={`edge-insert-drop-${id}`}
                            kind="edge-insert-drop"
                            payload={{
                                edgeId: id,
                                source,
                                target,
                                sourceHandle: sourceHandleId ?? null,
                                targetHandle: targetHandleId ?? null,
                                position: { x: labelX, y: labelY },
                            }}
                            accepts={(t) => t !== 'stickyNote'}
                            style={{
                                width: EDGE_DROP_HIT_SIZE,
                                height: EDGE_DROP_HIT_SIZE,
                            }}
                        >
                            {({ isOver, isCandidate }) =>
                                isCandidate ? (
                                    // Visible for the whole drag (isCandidate), not
                                    // just when hit (isOver) — you have to see the
                                    // targets to aim at one. Grows + fills on hit.
                                    <div className="absolute inset-0 flex items-center justify-center">
                                        <div
                                            className={`flex items-center justify-center rounded-md border-2 border-dashed transition-all duration-150 ${
                                                isOver
                                                    ? 'h-7 w-7 border-primary bg-primary/25 text-primary dark:border-foreground dark:bg-foreground/25 dark:text-foreground'
                                                    : 'h-5 w-5 border-muted-foreground/50 bg-card/80 text-muted-foreground dark:border-zinc-500'
                                            }`}
                                        >
                                            <Plus size={isOver ? 14 : 11} />
                                        </div>
                                    </div>
                                ) : null
                            }
                        </CanvasDropTarget>
                    </div>
                </EdgeLabelRenderer>
            )}

            {/* Hover-revealed midpoint actions for dataflow edges: insert a node
                into the edge, or delete the edge. zinc-900 base; the insert
                button is a rounded square with a neutral hover, the delete
                button is round and flushes red. */}
            {showDelete && !isToolEdge && (
                <EdgeLabelRenderer>
                    <div
                        className="nodrag nopan flex items-center gap-1.5"
                        onMouseEnter={() => setIsButtonHovered(true)}
                        onMouseLeave={() => setIsButtonHovered(false)}
                        style={{
                            position: 'absolute',
                            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
                            pointerEvents: 'all',
                            // EdgeLabelRenderer's container can render under the
                            // SVG edges layer, hiding the buttons (looks like
                            // reduced opacity) and swallowing clicks. Force it
                            // above with a high z-index.
                            zIndex: 1000,
                        }}
                    >
                        {/* Insert a node into this edge. Hands the picker the
                            edge's endpoints + handles and its flow-space midpoint
                            (labelX/labelY are already flow coords) so the picked
                            node lands centered on the edge and splices in:
                            source→new→target. */}
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                document.dispatchEvent(
                                    new CustomEvent(
                                        'noclick:insert-node-on-edge',
                                        {
                                            detail: {
                                                edgeId: id,
                                                source,
                                                target,
                                                sourceHandle:
                                                    sourceHandleId ?? null,
                                                targetHandle:
                                                    targetHandleId ?? null,
                                                position: {
                                                    x: labelX,
                                                    y: labelY,
                                                },
                                            },
                                        }
                                    )
                                );
                            }}
                            className={NODE_INSERT_BTN_CLASSES}
                            title="Insert node here"
                        >
                            <Plus size={12} />
                        </button>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                deleteElements({ edges: [{ id }] });
                            }}
                            className={NODE_DELETE_BTN_CLASSES}
                            title="Delete edge"
                        >
                            <Trash2 size={12} />
                        </button>
                    </div>
                </EdgeLabelRenderer>
            )}
        </g>
    );
}

export default memo(AnimatedWorkflowEdge);
