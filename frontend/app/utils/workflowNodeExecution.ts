/**
 * Utility functions for running individual workflow nodes.
 * Extracts the logic for building subset graphs when executing a single node
 * with its previous nodes' outputs as mocked data.
 */

import type { Node, Edge } from '@xyflow/react';
import { filterConfigForExecution } from '~/utils/nodeSchemas';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';

// Re-export for convenience
export { filterConfigForExecution };

// Note: stripRuntimeFields has been replaced by buildSaveConfig() in ~/lib/applyNodeUpdate.ts.
// buildSaveConfig uses an allowlist (data.config + known metadata) instead of a blocklist,
// preventing runtime state from accidentally leaking into saved data.

// Serialized execution graph shapes. They remain open to node-specific fields,
// while keeping graph identity typed for callers that compute execution sets.
interface WorkflowNode extends Record<string, unknown> {
    id: string;
    type?: string;
    position?: { x: number; y: number };
    config: Record<string, unknown>;
}

interface WorkflowEdge extends Record<string, unknown> {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

export function serializeNodeForExecution(node: Node): WorkflowNode {
    const config = filterConfigForExecution(node.type, buildSaveConfig(node));
    const serialized: WorkflowNode = {
        id: node.id,
        type: node.type,
        position: node.position,
        config,
    };
    const width = node.width ?? (node.style as Record<string, unknown> | undefined)?.width;
    const height = node.height ?? (node.style as Record<string, unknown> | undefined)?.height;
    if (width) serialized.width = width;
    if (height) serialized.height = height;
    return serialized;
}

export function serializeEdgeForExecution(edge: Edge): WorkflowEdge {
    return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
    };
}

export function serializeGraphForExecution(nodes: Node[], edges: Edge[]): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
    return {
        nodes: nodes.map(serializeNodeForExecution),
        edges: edges.map(serializeEdgeForExecution),
    };
}

/** Result of preparing a single node for execution */
export type PrepareNodeExecutionResult =
    | { success: true; nodes: WorkflowNode[]; edges: WorkflowEdge[] }
    | { success: false; error: string };

/**
 * Check if a node's config contains any {{nodeId...}} references to a given source node.
 */
function configReferencesNode(config: Record<string, any>, sourceNodeId: string): boolean {
    const pattern = `{{${sourceNodeId}`;
    const check = (val: unknown): boolean => {
        if (typeof val === 'string') return val.includes(pattern);
        if (Array.isArray(val)) return val.some(check);
        if (val && typeof val === 'object') return Object.values(val).some(check);
        return false;
    };
    return check(config);
}

/**
 * Detect if running forward-only from a start node would leave unresolved
 * upstream references. BFS-forward to collect reachable nodes, then scan
 * their configs for {{nodeId.field}} references to nodes outside the set.
 */
export function detectUpstreamReferences(
    startNodeId: string,
    nodes: Node[],
    edges: Edge[]
): { hasUpstreamRefs: boolean; referencedUpstreamNodeIds: string[] } {
    // BFS forward from startNodeId
    const forwardSet = new Set<string>();
    const queue = [startNodeId];
    while (queue.length > 0) {
        const id = queue.shift()!;
        if (forwardSet.has(id)) continue;
        forwardSet.add(id);
        for (const e of edges) {
            if (e.source === id && !forwardSet.has(e.target)) queue.push(e.target);
        }
    }

    const allNodeIds = new Set(nodes.map(n => n.id));
    const upstreamRefs = new Set<string>();
    const refPattern = /\{\{([^}]+)\}\}/g;

    const scan = (val: unknown) => {
        if (typeof val === 'string') {
            for (const m of val.matchAll(refPattern)) {
                const refNodeId = m[1].split('.')[0].split('[')[0];
                if (refNodeId && !forwardSet.has(refNodeId) && allNodeIds.has(refNodeId)) {
                    upstreamRefs.add(refNodeId);
                }
            }
        } else if (Array.isArray(val)) { val.forEach(scan); }
        else if (val && typeof val === 'object') { Object.values(val).forEach(scan); }
    };

    for (const nodeId of forwardSet) {
        const node = nodes.find(n => n.id === nodeId);
        if (node?.data) scan(node.data);
    }

    return { hasUpstreamRefs: upstreamRefs.size > 0, referencedUpstreamNodeIds: [...upstreamRefs] };
}

/**
 * Check if a previous node's output is required by the target node.
 * A previous node's output is required if the target's config references it.
 * State Manager nodes connected via 'state' handle are never required.
 */
export function isPreviousNodeOutputRequired(
    previousNode: Node,
    targetNode: Node,
    edges: Edge[]
): boolean {
    // State Manager nodes connected via 'state' handle don't need output
    if (previousNode.type === 'state-manager') {
        const stateEdge = edges.find(
            e => e.source === previousNode.id && e.target === targetNode.id && e.targetHandle === 'state'
        );
        if (stateEdge) return false;
    }

    // Check if the target node's config actually references this previous node
    const config = targetNode.data || {};
    return configReferencesNode(config, previousNode.id);
}

/**
 * Prepares the subset graph needed to execute a single node.
 *
 * This function:
 * 1. Finds the target node
 * 2. Identifies all previous nodes (nodes with edges pointing to target)
 * 3. Validates that referenced previous nodes have output data
 * 4. Builds the subset graph with previous nodes having mockedOutput set
 *
 * @param nodeId - The ID of the node to execute
 * @param nodes - All nodes in the workflow
 * @param edges - All edges in the workflow
 * @param outputOverrides - Per-node output overrides from carousel selections (takes priority over node.data)
 * @returns The prepared subset graph or an error
 */
export function prepareNodeExecution(
    nodeId: string,
    nodes: Node[],
    edges: Edge[],
    outputOverrides?: Record<string, { output: unknown }>,
): PrepareNodeExecutionResult {
    const targetNode = nodes.find(n => n.id === nodeId);
    if (!targetNode) {
        return { success: false, error: 'Node not found' };
    }

    // Find previous nodes (nodes that have edges pointing to this node)
    const incomingEdges = edges.filter(e => e.target === nodeId);

    // For iteration nodes, filter out "loop-back" edges from body nodes
    // A loop-back edge is from a node that is ALSO a target of the iteration node
    // (i.e., body nodes that loop back for aggregation metadata, not real dependencies)
    const isIterationNode = targetNode.type === 'iteration';
    const outgoingTargets = isIterationNode
        ? new Set(edges.filter(e => e.source === nodeId).map(e => e.target))
        : new Set<string>();

    const filteredIncomingEdges = incomingEdges.filter(e => !outgoingTargets.has(e.source));
    const previousNodeIds = filteredIncomingEdges.map(e => e.source);
    const previousNodes = previousNodeIds
        .map(id => nodes.find(n => n.id === id))
        .filter((n): n is Node => n !== undefined);

    // Only require output from previous nodes whose data is actually referenced in config
    const missingOutputNodes = previousNodes.filter(n => {
        const output = outputOverrides?.[n.id]?.output ?? n.data?.mockedOutput ?? n.data?.output;
        if (output !== undefined && output !== null) return false; // Has output, fine
        // No output — only a problem if the target node references this node
        return isPreviousNodeOutputRequired(n, targetNode, edges);
    });

    if (missingOutputNodes.length > 0) {
        const missingIds = missingOutputNodes.map(n => n.id).join(', ');
        return { success: false, error: `Missing output from previous nodes: ${missingIds}` };
    }

    // Build subset graph: previous nodes with mocked outputs + target node
    const subsetNodes: WorkflowNode[] = [
        // Previous nodes with their outputs set as mockedOutput
        ...previousNodes.map(n => {
            const saveConfig = buildSaveConfig(n);
            const { mockedOutput: _mo, ...staticConfig } = saveConfig;
            let effectiveOutput = outputOverrides?.[n.id]?.output ?? n.data?.mockedOutput ?? n.data?.output;
            // State Manager nodes without output use default state from config or empty object
            if (n.type === 'state-manager' && effectiveOutput === undefined) {
                effectiveOutput = { state: (n.data?.config as any)?.state ?? {} };
            }
            const filteredConfig = filterConfigForExecution(n.type, staticConfig);
            return {
                id: n.id,
                type: n.type,
                position: n.position,
                config: { ...filteredConfig, ...(effectiveOutput !== undefined ? { mockedOutput: effectiveOutput } : {}) }
            };
        }),
        // Target node with its normal config (no mockedOutput so it executes for real)
        (() => {
            const saveConfig = buildSaveConfig(targetNode);
            const { mockedOutput: _mo, ...rawConfig } = saveConfig;
            const config = filterConfigForExecution(targetNode.type, rawConfig);
            return {
                id: targetNode.id,
                type: targetNode.type,
                position: targetNode.position,
                config
            };
        })()
    ];

    // Only edges connecting previous nodes to target node (excluding loop-back edges)
    const subsetEdges: WorkflowEdge[] = filteredIncomingEdges.map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle
    }));

    console.log('[workflowNodeExecution] Prepared single node execution:', nodeId, 'with', previousNodes.length, 'previous nodes');

    return { success: true, nodes: subsetNodes, edges: subsetEdges };
}
