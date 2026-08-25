// Converts workflow XML (from _workflow_to_xml in mcp_server.py) to ReactFlow
// Node[] and Edge[] arrays. Handles both positioned and unpositioned nodes.

import type { Node, Edge } from '@xyflow/react';
import { applyEdgeStyle } from '~/utils/workflowLayout';

interface ParsedNode {
    id: string;
    type: string;
    x: number;
    y: number;
    width: number;
    height: number;
    label?: string;
    attrs: Record<string, string>;
}

interface ParsedEdge {
    from: string;
    to: string;
    handle?: string;
    type?: string;
}

// Node types in the XML match ReactFlow registered types exactly (e.g. "automation-slack")
// No normalization needed.

/** Parse workflow XML into raw node/edge data */
export function parseWorkflowXml(xml: string): { nodes: ParsedNode[]; edges: ParsedEdge[] } {
    const nodes: ParsedNode[] = [];
    const edges: ParsedEdge[] = [];

    // Parse <node ... /> tags
    const nodeRegex = /<node\s+([^>]*?)\s*\/>/g;
    let m: RegExpExecArray | null;
    while ((m = nodeRegex.exec(xml)) !== null) {
        const attrs = parseAttrs(m[1]);
        nodes.push({
            id: attrs.id || '',
            type: attrs.type || '',
            x: parseFloat(attrs.x || '0'),
            y: parseFloat(attrs.y || '0'),
            width: parseFloat(attrs.width || '90'),
            height: parseFloat(attrs.height || '90'),
            label: attrs.label,
            attrs,
        });
    }

    // Parse <edge ... /> tags
    const edgeRegex = /<edge\s+([^>]*?)\s*\/>/g;
    while ((m = edgeRegex.exec(xml)) !== null) {
        const attrs = parseAttrs(m[1]);
        edges.push({
            from: attrs.from || '',
            to: attrs.to || '',
            handle: attrs.handle,
            type: attrs.type,
        });
    }

    return { nodes, edges };
}

function unescapeXml(s: string): string {
    return s.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

function parseAttrs(attrString: string): Record<string, string> {
    const attrs: Record<string, string> = {};
    const regex = /(\w+)\s*=\s*"([^"]*)"/g;
    let m: RegExpExecArray | null;
    while ((m = regex.exec(attrString)) !== null) {
        attrs[m[1]] = unescapeXml(m[2]);
    }
    return attrs;
}

/** Convert parsed XML to ReactFlow format */
export function toReactFlowData(
    parsed: ReturnType<typeof parseWorkflowXml>,
): { nodes: Node[]; edges: Edge[] } {
    let { nodes: parsedNodes, edges: parsedEdges } = parsed;

    // Auto-layout if no positions (all zeros)
    const allZero = parsedNodes.every((n) => n.x === 0 && n.y === 0);
    if (allZero && parsedNodes.length > 1) {
        parsedNodes = autoLayout(parsedNodes, parsedEdges);
    }

    const LAYOUT_ATTRS = new Set(['id', 'type', 'x', 'y', 'width', 'height', 'label']);

    const rfNodes: Node[] = parsedNodes.map((n) => {
        // Parse each attr and put it BOTH at top-level data (metadata reads like
        // data.operation / data.disabled) AND under data.config, because node
        // components read config fields from data.config (the authoritative model,
        // see CLAUDE.md). Without data.config a config-nested read silently renders
        // empty — e.g. the provider tools-count badge reads
        // data.config.agent_tool_operations, and the error-output handle reads
        // data.config._settings.
        const config: Record<string, unknown> = {};
        const data: Record<string, unknown> = { label: n.label };
        for (const [key, val] of Object.entries(n.attrs)) {
            if (LAYOUT_ATTRS.has(key)) continue;
            let parsed: unknown;
            try { parsed = JSON.parse(val); } catch { parsed = val; }
            data[key] = parsed;
            config[key] = parsed;
        }
        // has_mock is a display flag, not a config field: map it to mockedOutput.
        if (data.has_mock) { data.mockedOutput = true; delete data.has_mock; delete config.has_mock; }
        data.config = config;

        // Nodes that fill 100% of their container need explicit dimensions.
        // Interface nodes and sticky notes rely on parent sizing; automation nodes auto-size.
        const needsExplicitSize = n.type.startsWith('interface-') || n.type === 'stickyNote';
        const style = needsExplicitSize
            ? { width: Math.max(n.width, n.type === 'stickyNote' ? 200 : 250),
                height: Math.max(n.height, n.type === 'stickyNote' ? 150 : 120) }
            : undefined;

        return {
            id: n.id,
            type: n.type,
            position: { x: n.x, y: n.y },
            data,
            ...(style && { style }),
        };
    });

    const rfEdges: Edge[] = parsedEdges.map((e, i) => {
        // Tool-provider edges wire a provider's TOP handle into the agent's BOTTOM
        // handle (mirrors backend workflow_ops.resolve_tools_edge / PROVIDER_*_HANDLE).
        // _workflow_to_xml marks them type="tools"; a legacy handle="top" means the same.
        // Without the explicit target handle they'd attach to the agent's default input
        // and the provider→agent edge would render wrong (or not at all).
        const isToolsEdge = e.type === 'tools' || e.handle === 'top';
        return applyEdgeStyle({
            id: `e-${e.from}-${e.to}-${i}`,
            source: e.from,
            target: e.to,
            sourceHandle: isToolsEdge ? 'top' : e.handle,
            ...(isToolsEdge && { targetHandle: 'bottom' }),
        } as Edge);
    });

    return { nodes: rfNodes, edges: rfEdges };
}

/** Simple topological layered layout for nodes without positions */
function autoLayout(nodes: ParsedNode[], edges: ParsedEdge[]): ParsedNode[] {
    const adjacency = new Map<string, string[]>();
    const inDegree = new Map<string, number>();
    const nodeMap = new Map<string, ParsedNode>();

    for (const n of nodes) {
        nodeMap.set(n.id, { ...n });
        adjacency.set(n.id, []);
        inDegree.set(n.id, 0);
    }

    for (const e of edges) {
        adjacency.get(e.from)?.push(e.to);
        inDegree.set(e.to, (inDegree.get(e.to) || 0) + 1);
    }

    // Kahn's algorithm for topological layers
    const layers: string[][] = [];
    let queue = [...nodes.filter((n) => (inDegree.get(n.id) || 0) === 0).map((n) => n.id)];

    while (queue.length > 0) {
        layers.push([...queue]);
        const next: string[] = [];
        for (const id of queue) {
            for (const child of adjacency.get(id) || []) {
                const deg = (inDegree.get(child) || 1) - 1;
                inDegree.set(child, deg);
                if (deg === 0) next.push(child);
            }
        }
        queue = next;
    }

    // Position layers left-to-right
    const H_GAP = 180;
    const V_GAP = 120;
    let x = 40;
    for (const layer of layers) {
        const totalHeight = layer.reduce((sum, id) => sum + (nodeMap.get(id)?.height || 90), 0) + V_GAP * (layer.length - 1);
        let y = Math.max(40, (600 - totalHeight) / 2);
        for (const id of layer) {
            const n = nodeMap.get(id)!;
            n.x = x;
            n.y = y;
            y += (n.height || 90) + V_GAP;
        }
        x += Math.max(...layer.map((id) => nodeMap.get(id)?.width || 90)) + H_GAP;
    }

    return nodes.map((n) => nodeMap.get(n.id) || n);
}
