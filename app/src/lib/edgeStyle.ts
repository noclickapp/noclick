// How a workflow's connections look, the one place it's said: a connection the canvas makes, and one read from a saved
// graph that carries no look of its own, both drawn by the canvas's animated edge with the default stroke.
import type { Edge } from '@xyflow/react';
import { DEFAULT_EDGE_STYLE } from '@/lib/nodeSizes';

/**
 * Creates a styled edge with consistent appearance across the workflow.
 * Use this function instead of manually specifying edge styles to ensure consistency.
 * Uses 'animated' type which maps to AnimatedWorkflowEdge (bezier curves).
 */
export function createStyledEdge(params: {
    id?: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
    type?: string;
}): Edge {
    const { id, source, target, sourceHandle, targetHandle, type = 'animated' } = params;
    return {
        id: id || `e_${source}_${target}`,
        source,
        target,
        sourceHandle,
        targetHandle,
        type,
        animated: true,
        style: { ...DEFAULT_EDGE_STYLE },
        data: { isAnimating: false },
    };
}

/**
 * Drop edges duplicating an identical connection (same endpoints + handles).
 * Stale canvas state has produced doubled edges, which render two stacked
 * midpoint chips (hovering one shows its delete button on top of the twin's
 * chip) and double-count dependencies. First occurrence wins.
 */
export function dedupeEdges(edges: Edge[]): Edge[] {
    const seen = new Set<string>();
    return edges.filter((e) => {
        const key = `${e.source}|${e.sourceHandle ?? ''}|${e.target}|${e.targetHandle ?? ''}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

/**
 * Applies default styling to an existing edge or array of edges.
 * Useful when loading edges from backend that may not have styling.
 * Uses 'animated' type which maps to AnimatedWorkflowEdge (bezier curves).
 */
export function applyEdgeStyle(edge: Edge): Edge {
    return {
        ...edge,
        type: edge.type || 'animated',
        animated: true,
        style: { ...DEFAULT_EDGE_STYLE },
        data: { isAnimating: false, ...edge.data },
    };
}
