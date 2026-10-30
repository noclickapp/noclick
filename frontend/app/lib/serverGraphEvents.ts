// A server write's builder events (`mcp:builder_event`: the graph service's room, the workflow MCP, the builder)
// applied to a copy of the graph. One reducer for the canvas (`useMCPBuilderEvents`, which animates them) and for
// the canvas's per-step base in `liveGraphStore` (what the server holds, which a conflict's three-way merge reads).
import type { Edge, Node } from '@xyflow/react';
import { applyNodeUpdate, createWorkflowNode, rawConfigToPayload } from '~/lib/applyNodeUpdate';
// Node dimensions come from the serialized icon singleton (dashboard loader), not the registry: importing the
// registry would pull its component graph into every bundle that applies these events.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';

export const GRAPH_EVENT_TYPES = new Set([
    'node_start',
    'node_updated',
    'node_removed',
    'edge_added',
    'edge_removed',
    'layout_applied',
]);

type EventData = Record<string, any>;

/** The nodes after the event; `animate` marks them for the canvas (adding, settled, moving). */
export function serverNodesAfter(nodes: Node[], eventType: string, data: EventData, animate = false): Node[] {
    switch (eventType) {
        case 'node_start': {
            const raw = data.node;
            if (!raw?.id || nodes.some((n) => n.id === raw.id)) return nodes;
            const node = createWorkflowNode(
                raw.id,
                raw.type,
                raw.position || { x: 250, y: 150 },
                {
                    ...(raw.label ? { label: raw.label } : {}),
                    ...(raw.operation ? { operation: raw.operation } : {}),
                    ...(raw.goal ? { goal: raw.goal } : {}),
                    ...(raw.content !== undefined ? { content: raw.content } : {}),
                    ...(raw.color !== undefined ? { color: raw.color } : {}),
                },
                animate ? { mcpAnimationState: 'adding' } : undefined,
            );
            // Initial dimensions for resizable nodes (sticky notes + interface blocks).
            if (raw.type === 'stickyNote' && (raw.width || raw.height)) {
                node.style = { width: raw.width || 200, height: raw.height || 200 };
                node.width = raw.width || 200;
                node.height = raw.height || 200;
            } else if (raw.type?.startsWith('interface-')) {
                const def = getNodeIconMeta(raw.type);
                node.style = { width: def?.dimensions.width || 350, height: def?.dimensions.height || 200 };
            }
            return [...nodes, node];
        }
        case 'node_updated': {
            // `config` is the backend's flat blob (config fields plus metadata like credentialIds and label):
            // rawConfigToPayload routes each key to its place in the node's data.
            const { nodeId, config, type, position } = data;
            if (!nodeId) return nodes;
            const payload = {
                ...rawConfigToPayload(config || {}),
                ...(animate ? { extras: { mcpAnimationState: 'complete' } } : {}),
            };
            if (!nodes.some((n) => n.id === nodeId)) {
                if (!type) return nodes;
                return [...nodes, applyNodeUpdate(createWorkflowNode(nodeId, type, position || { x: 250, y: 150 }, {}),
                    payload)];
            }
            return nodes.map((n) => (n.id === nodeId ? applyNodeUpdate(n, payload) : n));
        }
        case 'node_removed':
            return data.nodeId ? nodes.filter((n) => n.id !== data.nodeId) : nodes;
        case 'layout_applied': {
            const { positions, sticky_updates } = data;
            if (!positions || typeof positions !== 'object') return nodes;
            return nodes.map((n) => {
                const position = positions[n.id];
                if (!position) return n;
                const dims = sticky_updates?.[n.id];
                const style = animate ? { ...n.style, transition: 'transform 0.5s ease' } : n.style;
                return {
                    ...n,
                    position,
                    ...(dims
                        ? { width: dims.width, height: dims.height, style: { ...style, width: dims.width, height: dims.height } }
                        : animate ? { style } : {}),
                };
            });
        }
        default:
            return nodes;
    }
}

/** The edges after the event; `animate` draws a new one as the canvas does. */
export function serverEdgesAfter(edges: Edge[], eventType: string, data: EventData, animate = false): Edge[] {
    switch (eventType) {
        case 'node_removed':
            return data.removedEdgeIds?.length ? edges.filter((e) => !data.removedEdgeIds.includes(e.id)) : edges;
        case 'edge_added': {
            const raw = data.edge;
            if (!raw?.id || edges.some((e) => e.id === raw.id)) return edges;
            return [...edges, {
                id: raw.id,
                source: raw.source,
                target: raw.target,
                ...(raw.sourceHandle ? { sourceHandle: raw.sourceHandle } : {}),
                ...(raw.targetHandle ? { targetHandle: raw.targetHandle } : {}),
                ...(animate ? {
                    type: 'animated',
                    animated: true,
                    style: { stroke: 'hsl(var(--foreground))', strokeWidth: 3, opacity: 0.8, strokeDasharray: '5 5' },
                    data: { isAnimating: false },
                } : {}),
            } as Edge];
        }
        case 'edge_removed':
            return data.edgeId ? edges.filter((e) => e.id !== data.edgeId) : edges;
        default:
            return edges;
    }
}
