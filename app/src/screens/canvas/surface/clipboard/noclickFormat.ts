// The canvas's own clipboard and file format, read back into steps. Two shapes hold the same thing:
//   1. a copy:  { type: 'noclick-workflow', nodes: [...], edges: [...] }
//   2. a file:  { name: '...', workflow_data: { nodes: [...], edges: [...] } }
// Every step read gets a new id, and references between the steps read together (`{{ $('id').field }}`, the older
// `{{id.path}}`) follow their steps to the new ids.
import type { Edge, Node } from '@xyflow/react';
import { generateEdgeId, generateNodeId } from '@/lib/nodeIdGenerator';
import { applyNodeUpdate, createWorkflowNode, normalizeNodeUpdatePayload } from '../../applyNodeUpdate';
import type { ClipboardParseResult, ClipboardParser, InterfaceLayoutItem } from './types';

/** `config` with each reference to a step in `idMap` pointing at its new id: the `$('id')` accessor (`{{ $('id').field.map(...) }}`)
 *  and the older `{{id.path}}`. A reference to a step that isn't being pasted is left as it is. */
function updateReferencesInConfig(config: unknown, idMap: Map<string, string>): unknown {
    if (typeof config === 'string') {
        // `$('id')` / `$("id")`: the quoted id is replaced in place, the rest of the expression untouched.
        let out = config.replace(/\$\(\s*(['"])([^'"]+)\1\s*\)/g, (match, quote, nodeId) => {
            const newId = idMap.get(nodeId);
            return newId ? `$(${quote}${newId}${quote})` : match;
        });
        // `{{oldId.path}}` (the `$` exclusion keeps this off the accessors handled above).
        out = out.replace(/\{\{([^.}$]+)\.([^}]+)\}\}/g, (match, nodeId, path) => {
            const newId = idMap.get(nodeId);
            return newId ? `{{${newId}.${path}}}` : match;
        });
        return out;
    }
    if (Array.isArray(config)) return config.map((item) => updateReferencesInConfig(item, idMap));
    if (config && typeof config === 'object') {
        const result: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(config)) result[key] = updateReferencesInConfig(value, idMap);
        return result;
    }
    return config;
}

export const noClickParser: ClipboardParser = {
    name: 'NoClick Workflow',
    priority: 100,

    parse(text: string): ClipboardParseResult | null {
        try {
            const data = JSON.parse(text);

            let nodes, edges, interfaceData;
            if (data.type === 'noclick-workflow' && data.nodes && data.edges) {
                nodes = data.nodes;
                edges = data.edges;
                interfaceData = data.interface;
            } else if (data.workflow_data?.nodes && data.workflow_data?.edges) {
                nodes = data.workflow_data.nodes;
                edges = data.workflow_data.edges;
                interfaceData = data.workflow_data.interface;
            } else {
                return null;
            }

            // New ids first, so every reference can be pointed at them afterwards.
            const idMap = new Map<string, string>();
            const parsedNodes: Node[] = nodes.map((node: any) => {
                const newId = generateNodeId(node.type);
                idMap.set(node.id, newId);
                // A step with no settings isn't one this format wrote.
                if (!node.config) {
                    console.error('[noclick format] a step has no config:', node);
                    throw new Error(`Clipboard node ${node.id} is missing config`);
                }
                const pastedNode = createWorkflowNode(newId, node.type, node.position, node.config, { configValid: false });
                // A step that was resized (a block of a page, a note) keeps its size.
                if (node.width || node.height) {
                    (pastedNode as any).style = {
                        ...(node.width ? { width: node.width } : {}),
                        ...(node.height ? { height: node.height } : {}),
                    };
                }
                return pastedNode;
            });

            // References follow their steps. The rewritten data goes back through the node update helpers, so each
            // field lands where the data model keeps it.
            parsedNodes.forEach((node, idx) => {
                const rewritten = updateReferencesInConfig(node.data, idMap) as Record<string, unknown>;
                parsedNodes[idx] = applyNodeUpdate({ ...node, data: {} }, normalizeNodeUpdatePayload(rewritten));
            });

            // A page with its own code names steps as quoted strings (`const QUEUE_READ = 'sheets_ownf'`), which the
            // pass above doesn't see. Only an id between matching quotes is replaced: a bare match would also change
            // an identifier that happens to hold the id (a step "supergreen" inside `supergreenSpots`).
            parsedNodes.forEach((node, idx) => {
                if (node.type !== 'interface-html-react') return;
                const config = (node.data.config as Record<string, unknown> | undefined) || {};
                if (typeof config.jsx_source !== 'string') return;
                let jsx = config.jsx_source;
                for (const [oldId, newId] of idMap) {
                    const escaped = oldId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const pattern = new RegExp(`(['"\`])${escaped}\\1`, 'g');
                    jsx = jsx.replace(pattern, `$1${newId}$1`);
                }
                parsedNodes[idx] = applyNodeUpdate(node, { config: { jsx_source: jsx } });
            });

            const parsedEdges: Edge[] = edges.map((edge: any) => ({
                id: generateEdgeId(),
                source: idMap.get(edge.source) || edge.source,
                target: idMap.get(edge.target) || edge.target,
                sourceHandle: edge.sourceHandle,
                targetHandle: edge.targetHandle,
                type: edge.type || 'animated',
                animated: true,
                style: { stroke: 'hsl(var(--foreground))', strokeWidth: 3, opacity: 0.8, strokeDasharray: '5 5' },
                data: { isAnimating: false },
            }));

            // A page's grid names its blocks by their steps' ids: they follow too, and a block whose step wasn't
            // pasted is left out.
            let interfaceLayout: InterfaceLayoutItem[] | undefined;
            if (interfaceData?.layout && Array.isArray(interfaceData.layout)) {
                interfaceLayout = interfaceData.layout
                    .map((item: any) => {
                        const newId = idMap.get(item.i);
                        return newId ? { ...item, i: newId } : null;
                    })
                    .filter(Boolean) as InterfaceLayoutItem[];
            }

            const result: ClipboardParseResult = { nodes: parsedNodes, edges: parsedEdges };
            if (interfaceLayout && interfaceLayout.length > 0) result.interface = { layout: interfaceLayout };
            return result;
        } catch {
            return null;
        }
    },
};
