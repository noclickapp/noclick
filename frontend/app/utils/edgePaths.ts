// Shared backward-edge routing for workflow canvases and previews. Extracted from
// AnimatedWorkflowEdge (which also had a copy in ForkCanvas) into a leaf module so
// the always-mounted workflow-browser preview can route loop-backs identically
// without importing @xyflow/react-dependent component modules.

/** A horizontal edge routes backward (loop-back under the nodes) when the target
 *  handle sits left of the source handle by more than this (canvas px). */
export const BACKWARD_EDGE_X_THRESHOLD = 20;

/**
 * Creates a custom path for backward edges that curves under the nodes.
 * Uses rounded corners with arc segments for clean, professional-looking routing.
 *
 * Path structure:
 *   Source ──┐
 *            │ (arc corner)
 *            ↓
 *   ╭────────╯
 *   │
 *   ↑ (arc corner)
 *   └──── Target
 *
 * Each corner is a quarter-circle arc with consistent radius. Coordinates are the
 * source/target HANDLE positions in canvas pixels (the constants below assume the
 * canvas's ~90px node with the handle at its vertical center).
 */
export function getBackwardEdgePath(
    sourceX: number,
    sourceY: number,
    targetX: number,
    targetY: number
): string {
    // Node is ~90px tall, handle is at center, so bottom edge is ~45px below handle
    const nodeHalfHeight = 45;
    // Padding from node edge to where the vertical edge segment runs
    // Extra space needed to clear the node label that sits below the node
    const edgePadding = 42;
    // Corner radius for smooth turns (must be <= edgePadding)
    const radius = 15;
    // Extra vertical space below the lower node
    const loopOffset = 30;

    // Calculate key Y positions
    const sourceBottomY = sourceY + nodeHalfHeight + edgePadding;
    const targetBottomY = targetY + nodeHalfHeight + edgePadding;
    const loopY = Math.max(sourceBottomY, targetBottomY) + loopOffset;

    // X positions for vertical segments (with padding from handles)
    const rightX = sourceX + edgePadding; // Vertical segment on source side
    const leftX = targetX - edgePadding; // Vertical segment on target side

    // Clamp radius if nodes are very close together to avoid overlapping arcs
    const horizontalDistance = rightX - leftX;
    const effectiveRadius = Math.min(radius, horizontalDistance / 4);

    // Build path with rounded corners using arc commands
    // Arc syntax: A rx ry x-rotation large-arc-flag sweep-flag x y
    // sweep-flag: 1 = clockwise (all our turns are clockwise as we go around)

    return [
        // Start at source handle
        `M ${sourceX} ${sourceY}`,
        // Horizontal right to corner
        `L ${rightX - effectiveRadius} ${sourceY}`,
        // Arc: turn down (clockwise)
        `A ${effectiveRadius} ${effectiveRadius} 0 0 1 ${rightX} ${sourceY + effectiveRadius}`,
        // Vertical down to bottom corner
        `L ${rightX} ${loopY - effectiveRadius}`,
        // Arc: turn left (clockwise)
        `A ${effectiveRadius} ${effectiveRadius} 0 0 1 ${rightX - effectiveRadius} ${loopY}`,
        // Horizontal left to target side corner
        `L ${leftX + effectiveRadius} ${loopY}`,
        // Arc: turn up (clockwise)
        `A ${effectiveRadius} ${effectiveRadius} 0 0 1 ${leftX} ${loopY - effectiveRadius}`,
        // Vertical up toward target
        `L ${leftX} ${targetY + effectiveRadius}`,
        // Arc: turn right toward target (clockwise)
        `A ${effectiveRadius} ${effectiveRadius} 0 0 1 ${leftX + effectiveRadius} ${targetY}`,
        // Horizontal right to target handle
        `L ${targetX} ${targetY}`,
    ].join(' ');
}
