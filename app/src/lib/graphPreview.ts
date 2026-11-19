// A workflow's graph as it's saved, and the slim projection a preview draws from it: positions, types and the pairs
// each connection joins, so a list of workflows doesn't keep every step's settings (a sticky note's text, a mocked
// output) just to draw a thumbnail.
import { isTriggerSourceLite } from '@/lib/nodeIconRegistry';

/** A step in the saved shape: its id, type, place on the canvas and settings. */
export interface SavedNode {
    id: string;
    type?: string;
    position: { x: number; y: number };
    config: Record<string, unknown>;
}

/** A connection in the saved shape. */
export interface SavedEdge {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

/** A workflow's graph as it's saved ({nodes, edges}). */
export interface SavedGraph {
    nodes: SavedNode[];
    edges: SavedEdge[];
}

export interface GraphPreviewNode {
    id: string;
    type: string;
    x: number;
    y: number;
    width?: number;
    height?: number;
    /** Agent nodes only: config.model, so the preview can render the harness logo (AgentModelIcon). */
    agentModel?: string;
    /** Sticky notes only: the n8n-style palette index (config.color), so the preview tints them like the canvas. */
    stickyColor?: number;
    /** Set (true) only when the node is disabled / has a mocked output — the preview mirrors the canvas states. */
    disabled?: boolean;
    mocked?: boolean;
}

export interface GraphPreviewEdge {
    source: string;
    target: string;
    /** 'bottom' marks tools-provider wiring (provider top → agent underside); anchors differ from dataflow. */
    targetHandle?: string;
}

export interface GraphPreview {
    nodes: GraphPreviewNode[];
    edges: GraphPreviewEdge[];
}

const asFiniteNumber = (v: unknown): number | undefined => {
    // parseFloat tolerates style-sourced dimensions like "320px".
    const n = typeof v === 'string' ? parseFloat(v) : v;
    return typeof n === 'number' && Number.isFinite(n) ? n : undefined;
};

// Loose view of the untyped workflow_data blob — every field verified before use.
interface RawGraphBlob {
    nodes?: Array<{
        id?: unknown;
        type?: unknown;
        position?: { x?: unknown; y?: unknown } | null;
        width?: unknown;
        height?: unknown;
        config?: {
            model?: unknown;
            color?: unknown;
            operation?: unknown;
            disabled?: unknown;
            mockedOutput?: unknown;
        } | null;
    } | null>;
    edges?: Array<{
        source?: unknown;
        target?: unknown;
        sourceId?: unknown;
        targetId?: unknown;
        targetHandle?: unknown;
    } | null>;
}

/** Project the raw workflow_data blob down to the preview shape. An empty-but-present
 *  nodes array yields an empty preview (rendered as a blank canvas); undefined only
 *  when the entry carries no graph blob at all (e.g. shared-with-me listings). */
export function buildGraphPreview(workflowData: unknown): GraphPreview | undefined {
    const blob = (workflowData ?? {}) as RawGraphBlob;
    const rawNodes = blob.nodes;
    if (!Array.isArray(rawNodes)) return undefined;

    const nodes: GraphPreviewNode[] = [];
    // type + selected operation per node id for edge filtering below; operation is
    // deliberately NOT retained on the projection.
    const metaById = new Map<string, { type: string; operation?: string }>();
    for (const n of rawNodes) {
        const x = asFiniteNumber(n?.position?.x);
        const y = asFiniteNumber(n?.position?.y);
        if (typeof n?.id !== 'string' || typeof n.type !== 'string' || x === undefined || y === undefined) continue;
        metaById.set(n.id, {
            type: n.type,
            operation: typeof n.config?.operation === 'string' ? n.config.operation : undefined,
        });
        nodes.push({
            id: n.id,
            type: n.type,
            x,
            y,
            width: asFiniteNumber(n.width),
            height: asFiniteNumber(n.height),
            agentModel:
                n.type === 'agent' && typeof n.config?.model === 'string' ? n.config.model : undefined,
            stickyColor:
                n.type === 'stickyNote' && typeof n.config?.color === 'number' ? n.config.color : undefined,
            disabled: n.config?.disabled === true || undefined,
            mocked: n.config?.mockedOutput != null || undefined,
        });
    }

    const rawEdges = Array.isArray(blob.edges) ? blob.edges : [];
    const edges: GraphPreviewEdge[] = [];
    for (const e of rawEdges) {
        // Older blobs use sourceId/targetId.
        const source = e?.source ?? e?.sourceId;
        const target = e?.target ?? e?.targetId;
        if (typeof source !== 'string' || typeof target !== 'string') continue;
        const src = metaById.get(source);
        if (!src || !metaById.has(target)) continue;
        const targetHandle = typeof e?.targetHandle === 'string' ? e.targetHandle : undefined;
        // Mirror the canvas: a tools edge whose source currently has a TRIGGER
        // operation selected is an invalid legacy combo the canvas never renders
        // (trigger/provider mutual exclusivity) — don't draw it here either.
        if (targetHandle === 'bottom' && isTriggerSourceLite(src.type, src.operation)) continue;
        edges.push({ source, target, targetHandle });
    }

    return { nodes, edges };
}
