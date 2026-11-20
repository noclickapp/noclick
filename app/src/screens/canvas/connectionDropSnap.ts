// connectionDropSnap — pure resolver for edge drags released over a node's BODY
// instead of a handle dot: given the drag origin and the drop node's handles, it
// picks the best opposite-side handle (natural counterpart first, then closest to
// the pointer) so users don't have to land drops precisely on the small circles.
// Consumed by FlowCanvas's onConnectEnd; validity still flows through the canvas
// isValidConnection rules, so nothing connectable-by-snap isn't connectable by hand.

import type { Connection } from '@xyflow/react';

/** A prospective handle on the drop node, with its center in flow coordinates. */
export interface DropHandleCandidate {
    id: string | null;
    x: number;
    y: number;
}

// Default dataflow handle ids differ per component (AutomationNode uses no id,
// AIAgentNode/ToolNode use 'left'/'right') — treat both spellings as the default.
const DEFAULT_INPUT_IDS = new Set<string | null>([null, 'left']);
const DEFAULT_OUTPUT_IDS = new Set<string | null>([null, 'right']);

// The handle a body drop "means", per the canvas wiring vocabulary: provider
// top ↔ agent/MCP bottom, state-manager output ↔ serverless 'state', everything
// else ↔ the default dataflow input/output. Non-natural handles (error output,
// conditional branches) stay reachable by distance when no natural handle is
// valid, but never steal a center-of-node drop from the default.
function isNaturalCounterpart(
    candidateId: string | null,
    opts: {
        fromHandleType: 'source' | 'target';
        fromHandleId: string | null;
        fromNodeType: string | null | undefined;
    }
): boolean {
    const { fromHandleType, fromHandleId, fromNodeType } = opts;
    if (fromHandleType === 'source') {
        if (fromHandleId === 'top') return candidateId === 'bottom';
        if (fromNodeType === 'state-manager') return candidateId === 'state';
        return DEFAULT_INPUT_IDS.has(candidateId);
    }
    // Dragging backwards out of an input: resolve the source-side handle.
    if (fromHandleId === 'bottom') return candidateId === 'top';
    if (fromHandleId === 'state') return candidateId === 'output';
    return DEFAULT_OUTPUT_IDS.has(candidateId);
}

export function resolveBodyDropConnection(args: {
    fromNodeId: string;
    fromNodeType: string | null | undefined;
    /** Real (hint-normalized) handle id the drag started from. */
    fromHandleId: string | null;
    fromHandleType: 'source' | 'target';
    dropNodeId: string;
    /** Pointer release position in flow coordinates. */
    dropPoint: { x: number; y: number };
    candidates: DropHandleCandidate[];
    isValidConnection: (connection: Connection) => boolean;
}): Connection | null {
    const {
        fromNodeId,
        fromNodeType,
        fromHandleId,
        fromHandleType,
        dropNodeId,
        dropPoint,
        candidates,
        isValidConnection,
    } = args;
    if (dropNodeId === fromNodeId) return null;

    let best: {
        connection: Connection;
        natural: boolean;
        dist: number;
    } | null = null;
    for (const candidate of candidates) {
        const connection: Connection =
            fromHandleType === 'source'
                ? {
                      source: fromNodeId,
                      sourceHandle: fromHandleId,
                      target: dropNodeId,
                      targetHandle: candidate.id,
                  }
                : {
                      source: dropNodeId,
                      sourceHandle: candidate.id,
                      target: fromNodeId,
                      targetHandle: fromHandleId,
                  };
        if (!isValidConnection(connection)) continue;
        const natural = isNaturalCounterpart(candidate.id, {
            fromHandleType,
            fromHandleId,
            fromNodeType,
        });
        const dist = Math.hypot(
            candidate.x - dropPoint.x,
            candidate.y - dropPoint.y
        );
        if (
            !best ||
            (natural && !best.natural) ||
            (natural === best.natural && dist < best.dist)
        ) {
            best = { connection, natural, dist };
        }
    }
    return best?.connection ?? null;
}
