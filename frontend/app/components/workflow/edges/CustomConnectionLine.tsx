/**
 * Custom connection line component for edge dragging.
 * Uses the same backward edge routing logic as AnimatedWorkflowEdge
 * to show a curved path when dragging an edge backward (right to left).
 */
import React from 'react';
import {
    ConnectionLineComponentProps,
    getBezierPath,
    Position,
} from '@xyflow/react';
import { getBackwardEdgePath } from './AnimatedWorkflowEdge';
import { fromHintHandleId } from '../nodes/base/NextStepHint';

export function CustomConnectionLine({
    fromX,
    fromY,
    fromPosition,
    toX,
    toY,
    toPosition,
    fromHandle,
    fromNode,
    connectionLineStyle,
}: ConnectionLineComponentProps) {
    // When the connection originates from a hint handle (the dashed-line stub
    // overlaying the regular source dot), redirect the visual start point to the
    // corresponding real handle so the line emerges from the dot.
    const realId = fromHintHandleId(fromHandle?.id);
    if (realId !== undefined && fromNode) {
        const real = fromNode.internals?.handleBounds?.source?.find(
            (h) => (h.id ?? null) === realId
        );
        if (real) {
            const nodePos = fromNode.internals.positionAbsolute;
            fromX = nodePos.x + real.x + real.width / 2;
            fromY = nodePos.y + real.y + real.height / 2;
            fromPosition = real.position;
        }
    }

    // Detect if this is a "backward" connection (dragging to the left).
    // Only applies to horizontal edges. Vertical edges (e.g. Tool→Agent
    // bottom/top connections) should always use the standard bezier path.
    const isVerticalEdge =
        fromPosition === Position.Top ||
        fromPosition === Position.Bottom ||
        toPosition === Position.Top ||
        toPosition === Position.Bottom;
    const isBackward = !isVerticalEdge && toX < fromX - 20;

    // Use custom path for backward edges, standard bezier for forward edges
    const path = isBackward
        ? getBackwardEdgePath(fromX, fromY, toX, toY)
        : getBezierPath({
              sourceX: fromX,
              sourceY: fromY,
              sourcePosition: fromPosition || Position.Right,
              targetX: toX,
              targetY: toY,
              targetPosition: toPosition || Position.Left,
          })[0];

    return (
        <g>
            <path
                d={path}
                fill="none"
                style={{
                    stroke:
                        connectionLineStyle?.stroke ||
                        'hsl(var(--canvas-edge))',
                }}
                strokeWidth={connectionLineStyle?.strokeWidth || 3}
                opacity={connectionLineStyle?.opacity || 0.8}
                strokeDasharray={connectionLineStyle?.strokeDasharray || '5 5'}
                className="animated"
            />
        </g>
    );
}
