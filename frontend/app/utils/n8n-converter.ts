/**
 * Utilities for converting n8n workflow JSON to NoClick JSON and ReactFlow nodes and edges.
 *
 * This module handles parsing n8n workflow JSON from clipboard and converting
 * it into NoClick JSON and ReactFlow-compatible format for display in the FlowCanvas.
 */

import { Node, Edge } from '@xyflow/react';
import {
    N8nWorkflow,
    N8nNode,
    isN8nWorkflow,
    isStickyNote,
    getReactFlowNodeType
} from '~/types/n8n';
import { generateShortSuffix } from '~/utils/nodeIdGenerator';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

interface ConversionResult {
    nodes: Node[];
    edges: Edge[];
    workflow: N8nWorkflow;
}

/**
 * Generates a unique ReactFlow node ID based on n8n node.
 * Format: n8n_{prefix}_{index} (e.g., "n8n_a7bx_0", "n8n_a7bx_1")
 */
function generateN8nNodeId(n8nNode: N8nNode, index: number, uniquePrefix: string): string {
    return `${uniquePrefix}_${index}`;
}

/**
 * Generates Python code representation for an n8n node.
 */
function generatePythonCodeForN8nNode(n8nNode: N8nNode): string {
    const lines: string[] = [];

    lines.push(`# Imported from n8n workflow`);
    lines.push(`# Node: ${n8nNode.name}`);
    lines.push(`# Type: ${n8nNode.type}`);

    if (n8nNode.notes) {
        lines.push(`# Notes: ${n8nNode.notes}`);
    }

    if (n8nNode.parameters && Object.keys(n8nNode.parameters).length > 0) {
        lines.push('');
        lines.push('# Parameters:');
        const paramLines = JSON.stringify(n8nNode.parameters, null, 2)
            .split('\n')
            .map(line => `# ${line}`);
        lines.push(...paramLines);
    }

    lines.push('');
    lines.push('# TODO: Implement node logic here');

    return lines.join('\n');
}

/**
 * Converts an n8n node to a ReactFlow node.
 */
function convertN8nNodeToReactFlow(n8nNode: N8nNode, index: number, uniquePrefix: string): Node {
    const nodeId = generateN8nNodeId(n8nNode, index, uniquePrefix);
    const nodeType = getReactFlowNodeType(n8nNode);

    // n8n positions are [x, y], ReactFlow uses {x, y}
    const position = {
        x: n8nNode.position[0],
        y: n8nNode.position[1]
    };

    // Create node label from name and optional notes
    let label = n8nNode.name;
    if (n8nNode.notes && n8nNode.notesInFlow) {
        label += `\n${n8nNode.notes}`;
    }

    // Build node data based on node type
    const data: Record<string, any> = {
        label,
        metadata: {
            source: 'n8n',
            originalType: n8nNode.type,
            originalName: n8nNode.name,
        }
    };

    if (isStickyNote(n8nNode)) {
        // For sticky notes (UI nodes)
        data.content = n8nNode.parameters?.content || n8nNode.content || '';
        data.color = n8nNode.parameters?.color || n8nNode.color || 0;
        data.isSticky = true;
    } else {
        // For regular nodes (Python nodes)
        data.code = generatePythonCodeForN8nNode(n8nNode);
        if (n8nNode.parameters) {
            data.parameters = n8nNode.parameters;
        }
    }

    const node: Node = createWorkflowNode(nodeId, nodeType, position, data, { configValid: false });

    // Set dimensions if available (for sticky notes)
    if (n8nNode.width || n8nNode.height || n8nNode.parameters?.width || n8nNode.parameters?.height) {
        node.style = {
            width: n8nNode.width || n8nNode.parameters?.width || 240,
            height: n8nNode.height || n8nNode.parameters?.height || 200,
        };
    }

    return node;
}

/**
 * Creates a map of n8n node names to ReactFlow node IDs.
 */
function createNodeNameToIdMap(n8nWorkflow: N8nWorkflow, uniquePrefix: string): Map<string, string> {
    const map = new Map<string, string>();

    n8nWorkflow.nodes.forEach((n8nNode, index) => {
        const nodeId = generateN8nNodeId(n8nNode, index, uniquePrefix);
        map.set(n8nNode.name, nodeId);
    });

    return map;
}

/**
 * Converts n8n connections to ReactFlow edges.
 */
function convertN8nConnectionsToEdges(
    n8nWorkflow: N8nWorkflow,
    nodeNameToIdMap: Map<string, string>,
    uniquePrefix: string
): Edge[] {
    const edges: Edge[] = [];
    let edgeIndex = 0;

    // Iterate through all source nodes in connections
    for (const [sourceNodeName, connectionTypes] of Object.entries(n8nWorkflow.connections)) {
        const sourceId = nodeNameToIdMap.get(sourceNodeName);
        if (!sourceId) continue;

        // Iterate through connection types (main, ai_languageModel, etc.)
        for (const [connectionType, connectionArrays] of Object.entries(connectionTypes)) {
            // connectionArrays is an array of arrays of connection targets
            connectionArrays.forEach((connectionArray, outputIndex) => {
                if (!Array.isArray(connectionArray)) return;

                // Each connection in the array represents a target
                connectionArray.forEach((connection) => {
                    const targetId = nodeNameToIdMap.get(connection.node);
                    if (!targetId) return;

                    edges.push({
                        id: `${uniquePrefix}_e${edgeIndex++}`,
                        source: sourceId,
                        target: targetId,
                        type: 'smoothstep',
                        animated: true,
                        style: {
                            stroke: '#22c55e',
                            strokeWidth: 3,
                            opacity: 0.8
                        },
                        data: {
                            connectionType,
                            outputIndex,
                            targetIndex: connection.index
                        }
                    });
                });
            });
        }
    }

    return edges;
}

/**
 * Parses n8n workflow JSON and converts it to ReactFlow nodes and edges.
 */
export function convertN8nWorkflowToReactFlow(workflowJson: string | object): ConversionResult {
    // Parse JSON if it's a string
    let workflowData: any;
    if (typeof workflowJson === 'string') {
        try {
            workflowData = JSON.parse(workflowJson);
        } catch (error) {
            throw new Error(`Invalid JSON: ${error instanceof Error ? error.message : 'Unknown error'}`);
        }
    } else {
        workflowData = workflowJson;
    }

    // Validate it's an n8n workflow
    if (!isN8nWorkflow(workflowData)) {
        throw new Error('Invalid n8n workflow format: missing required fields (nodes, connections)');
    }

    const workflow: N8nWorkflow = workflowData;

    // Generate unique prefix for this paste operation to avoid ID collisions
    // Format: n8n_{shortId} (e.g., "n8n_a7bx")
    const uniquePrefix = `n8n_${generateShortSuffix()}`;

    // Convert nodes
    const nodes = workflow.nodes.map((n8nNode, index) =>
        convertN8nNodeToReactFlow(n8nNode, index, uniquePrefix)
    );

    // Create name-to-ID mapping
    const nodeNameToIdMap = createNodeNameToIdMap(workflow, uniquePrefix);

    // Convert connections to edges
    const edges = convertN8nConnectionsToEdges(workflow, nodeNameToIdMap, uniquePrefix);

    return {
        nodes,
        edges,
        workflow
    };
}

/**
 * Attempts to parse clipboard data as n8n workflow JSON.
 * Returns null if parsing fails or data is not n8n format.
 */
export function parseClipboardAsN8nWorkflow(clipboardData: string): ConversionResult | null {
    try {
        return convertN8nWorkflowToReactFlow(clipboardData);
    } catch (error) {
        console.error('Failed to parse clipboard as n8n workflow:', error);
        return null;
    }
}

/**
 * Parses clipboard text as an n8n workflow and returns the raw workflow
 * object (not ReactFlow nodes). Use this when handing the paste to the
 * agentic builder — the brain translates it and node drafting read the source
 * parameters via n8n_refs, so the frontend should NOT pre-convert to nodes.
 */
export function extractN8nWorkflowFromClipboard(clipboardData: string): N8nWorkflow | null {
    let data: unknown;
    try {
        data = JSON.parse(clipboardData);
    } catch {
        return null;
    }
    return isN8nWorkflow(data) ? data : null;
}
