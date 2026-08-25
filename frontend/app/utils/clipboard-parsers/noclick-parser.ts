/**
 * Parser for NoClick workflow formats (clipboard and complete/database formats).
 * Supports two formats:
 * 1. Basic clipboard: { type: 'noclick-workflow', nodes: [...], edges: [...] }
 * 2. Complete/database: { name: '...', workflow_data: { nodes: [...], edges: [...] } }
 * When pasting, generates new IDs and updates all references ({{nodeId.path}}) to point to new IDs.
 */

import { Node, Edge } from '@xyflow/react';
import { ClipboardParser, ClipboardParseResult, InterfaceLayoutItem } from './types';
import { generateNodeId, generateEdgeId } from '~/utils/nodeIdGenerator';
import { applyNodeUpdate, createWorkflowNode, normalizeNodeUpdatePayload } from '~/lib/applyNodeUpdate';

/**
 * Recursively updates reference strings in config to use new node IDs — both the
 * `$('id')` accessor form (e.g. {{ $('id').field.map(...) }}) AND the legacy
 * `{{id.path}}` form. Only updates references to nodes that are in the idMap (nodes
 * being pasted together). External references (to nodes not in selection) are kept
 * unchanged. Without the accessor branch, pasted `$()` references keep the old ids
 * and break.
 */
function updateReferencesInConfig(
    config: unknown,
    idMap: Map<string, string>
): unknown {
    if (typeof config === 'string') {
        // New `$('id')` / `$("id")` accessor form — remap the quoted node id in place,
        // leaving the rest of the JS expression (`.field.split(...)`) untouched.
        let out = config.replace(/\$\(\s*(['"])([^'"]+)\1\s*\)/g, (match, quote, nodeId) => {
            const newId = idMap.get(nodeId);
            return newId ? `$(${quote}${newId}${quote})` : match;
        });
        // Legacy `{{oldId.path}}` form ($-accessor blocks are handled above; the `$`
        // exclusion keeps this from re-touching them).
        out = out.replace(/\{\{([^.}$]+)\.([^}]+)\}\}/g, (match, nodeId, path) => {
            const newId = idMap.get(nodeId);
            return newId ? `{{${newId}.${path}}}` : match; // Keep original if not in map
        });
        return out;
    }
    if (Array.isArray(config)) {
        return config.map(item => updateReferencesInConfig(item, idMap));
    }
    if (config && typeof config === 'object') {
        const result: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(config)) {
            result[key] = updateReferencesInConfig(value, idMap);
        }
        return result;
    }
    return config; // primitives (number, boolean, null, undefined)
}

/**
 * Parses NoClick workflow JSON formats from clipboard or file import.
 * Supports both basic clipboard format and complete database/template format.
 */
export const noClickParser: ClipboardParser = {
    name: 'NoClick Workflow',
    priority: 100, // Primary format, check first

    parse(text: string): ClipboardParseResult | null {
        try {
            const data = JSON.parse(text);

            // Support both formats
            let nodes, edges, workflowName, interfaceData;

            if (data.type === 'noclick-workflow' && data.nodes && data.edges) {
                // Basic clipboard format
                nodes = data.nodes;
                edges = data.edges;
                interfaceData = data.interface;
            } else if (data.workflow_data?.nodes && data.workflow_data?.edges) {
                // Complete/database/template format
                nodes = data.workflow_data.nodes;
                edges = data.workflow_data.edges;
                workflowName = data.name;
                interfaceData = data.workflow_data.interface;
            } else {
                return null;
            }

            // Log workflow name if importing a named workflow
            if (workflowName) {
                console.log(`Importing workflow: ${workflowName}`);
            }

            // Generate new IDs for pasted nodes to avoid conflicts
            // Two-pass approach: first generate all IDs, then update references
            const idMap = new Map<string, string>();

            // First pass: generate new IDs and create nodes with original config
            // Transient keys to strip from clipboard config before pasting
            const transientKeys = new Set(['configValid', '_hasPresetPosition']);

            const parsedNodes: Node[] = nodes.map((node: any) => {
                const newId = generateNodeId(node.type);
                idMap.set(node.id, newId);

                // STRICT: Clipboard format must have node.config
                if (!node.config) {
                    console.error('[noclick-parser] Node missing config in clipboard data:', node);
                    throw new Error(`Clipboard node ${node.id} is missing config`);
                }
                const pastedNode = createWorkflowNode(newId, node.type, node.position, node.config, { configValid: false });
                // Restore canvas dimensions for resizable nodes
                if (node.width || node.height) {
                    (pastedNode as any).style = {
                        ...(node.width ? { width: node.width } : {}),
                        ...(node.height ? { height: node.height } : {}),
                    };
                }
                return pastedNode;
            });

            // Second pass: update references in all node configs to use new IDs
            // This handles {{oldNodeId.path}} -> {{newNodeId.path}} transformations.
            // Route the rewritten data through normalizeNodeUpdatePayload +
            // applyNodeUpdate so config fields and top-level metadata land at
            // the right slots per the TOP_LEVEL_FIELDS registry — avoids the
            // in-place mutation that bypassed the contract.
            parsedNodes.forEach((node, idx) => {
                const rewritten = updateReferencesInConfig(node.data, idMap) as Record<string, unknown>;
                parsedNodes[idx] = applyNodeUpdate(
                    { ...node, data: {} },
                    normalizeNodeUpdatePayload(rewritten),
                );
            });

            // Third pass: replace bare node IDs in jsx_source for interface-html-react nodes.
            // updateReferencesInConfig only catches {{nodeId.path}} template refs; JSX components
            // also hardcode node IDs as quoted string literals (e.g. const QUEUE_READ = 'sheets_ownf').
            // Only match IDs surrounded by matching quotes — naive substring replacement corrupts
            // identifiers that happen to contain the old ID (e.g. node id "oldNode" inside the
            // variable name `oldNodeSummary`).
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

            // Update edge references to use new node IDs
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

            // Remap interface layout item IDs to new node IDs
            let interfaceLayout: InterfaceLayoutItem[] | undefined;
            if (interfaceData?.layout && Array.isArray(interfaceData.layout)) {
                interfaceLayout = interfaceData.layout
                    .map((item: any) => {
                        const newId = idMap.get(item.i);
                        if (!newId) return null; // Skip items not in the pasted selection
                        return { ...item, i: newId };
                    })
                    .filter(Boolean) as InterfaceLayoutItem[];
            }

            const result: ClipboardParseResult = { nodes: parsedNodes, edges: parsedEdges };
            if (interfaceLayout && interfaceLayout.length > 0) {
                result.interface = { layout: interfaceLayout };
            }
            return result;
        } catch {
            return null;
        }
    },
};
