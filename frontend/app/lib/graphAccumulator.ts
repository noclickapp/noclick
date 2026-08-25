/**
 * Pure graph accumulator logic for workflow generation events.
 *
 * This module provides React-free graph accumulation that can be:
 * 1. Used by the useWorkflowGeneration hook (via pure functions)
 * 2. Called from Python tests via the CLI wrapper (scripts/graph-accumulator-cli.ts)
 *
 * This ensures a single source of truth for event processing logic, preventing
 * drift between frontend and backend test implementations.
 */

// ============================================================================
// Types (re-exported for convenience, source of truth is workflowGeneratorMock.ts)
// ============================================================================

/** Represents a node being generated in the workflow */
export interface AccumulatedNode {
    id: string;
    type: string;
    label: string;
    description?: string;
    level: number;
    index: number;
    parentIds: string[];
    status: 'adding' | 'editing' | 'complete' | 'needs_input' | 'error';
    content: string;
    icon?: string;
    color?: string;
    operation?: string;
    operationReason?: string;
    config?: Record<string, unknown>;
    userFields?: string[];
    error?: string;
    position?: { x: number; y: number };
}

/** Represents an edge connecting two nodes */
export interface AccumulatedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    sourceHandle?: string;
    targetHandle?: string;
    status: 'animating' | 'complete';
}

/** Represents an input request */
export interface AccumulatedInput {
    id: string;
    nodeId: string;
    type: 'credential' | 'selection' | 'text' | 'config';
    label: string;
    description: string;
    options?: { id: string; label: string; icon?: string }[];
    /** Multi-select selection ask (from <ask multiple="true">) */
    multiple?: boolean;
    credentialType?: string;
    acceptedCredentialTypes?: string[];
    required: boolean;
    value?: string;
    nodeType?: string;
    fieldKey?: string;
    fieldSchema?: Record<string, unknown>;
    dependsOn?: string;
    requiredCredentialTypes?: string[];
    /** Snapshot of the node's credentialIds at request emission */
    credentialIds?: Record<string, string>;
    /** Node config snapshot for config-sensitive credential forms (agent harness/sub-model) */
    nodeConfig?: Record<string, any>;
}

/** State managed by the accumulator */
export interface AccumulatorState {
    nodes: AccumulatedNode[];
    edges: AccumulatedEdge[];
    inputs: AccumulatedInput[];
    workflowName: string;
    workflowSummary: string;
}

// ============================================================================
// Pure transformation functions
// These are used by both the React hook and the GraphAccumulator class
// ============================================================================

/**
 * Handle node_start event - add a new node
 */
export function handleNodeStart(
    nodes: AccumulatedNode[],
    node: AccumulatedNode
): AccumulatedNode[] {
    // Prevent duplicate nodes
    if (nodes.some(n => n.id === node.id)) {
        return nodes;
    }
    return [...nodes, node];
}

/**
 * Handle node_typing event - update node content while typing
 */
export function handleNodeTyping(
    nodes: AccumulatedNode[],
    nodeId: string,
    content: string
): AccumulatedNode[] {
    return nodes.map(n =>
        n.id === nodeId
            ? { ...n, status: 'editing' as const, content }
            : n
    );
}

/**
 * Handle node_complete event - mark node as complete
 */
export function handleNodeComplete(
    nodes: AccumulatedNode[],
    nodeId: string
): AccumulatedNode[] {
    return nodes.map(n =>
        n.id === nodeId
            ? { ...n, status: 'complete' as const }
            : n
    );
}

/**
 * Handle edge_add event - add a new edge and update target node's parentIds/level
 * Returns both updated nodes and edges
 */
export function handleEdgeAdd(
    nodes: AccumulatedNode[],
    edges: AccumulatedEdge[],
    edge: AccumulatedEdge
): { nodes: AccumulatedNode[]; edges: AccumulatedEdge[] } {
    // Prevent duplicate edges
    if (edges.some(e => e.id === edge.id)) {
        return { nodes, edges };
    }

    const newEdges = [...edges, edge];

    // Update target node's parentIds and recalculate level based on source
    const sourceNode = nodes.find(n => n.id === edge.sourceId);
    if (!sourceNode) {
        return { nodes, edges: newEdges };
    }

    const newNodes = nodes.map(n => {
        if (n.id === edge.targetId) {
            const newParentIds = n.parentIds.includes(edge.sourceId)
                ? n.parentIds
                : [...n.parentIds, edge.sourceId];
            const newLevel = Math.max(n.level, sourceNode.level + 1);
            return { ...n, parentIds: newParentIds, level: newLevel };
        }
        return n;
    });

    return { nodes: newNodes, edges: newEdges };
}

/**
 * Handle edge_complete event - mark edge as complete
 */
export function handleEdgeComplete(
    edges: AccumulatedEdge[],
    edgeId: string
): AccumulatedEdge[] {
    return edges.map(e =>
        e.id === edgeId
            ? { ...e, status: 'complete' as const }
            : e
    );
}

/**
 * Handle input_request event - add or update input request
 */
export function handleInputRequest(
    inputs: AccumulatedInput[],
    request: AccumulatedInput
): AccumulatedInput[] {
    // When a config input arrives (from node drafter), remove ALL text inputs for the same node
    if (request.type === 'config') {
        const filtered = inputs.filter(existing =>
            !(existing.nodeId === request.nodeId && existing.type === 'text')
        );
        return [...filtered, request];
    }
    return [...inputs, request];
}

/**
 * Handle node_added event (edit mode) - add enriched node as complete
 */
export function handleNodeAdded(
    nodes: AccumulatedNode[],
    edges: AccumulatedEdge[],
    node: AccumulatedNode
): { nodes: AccumulatedNode[]; edges: AccumulatedEdge[] } {
    // Prevent duplicate nodes
    if (nodes.some(n => n.id === node.id)) {
        return { nodes, edges };
    }
    const newNode = { ...node, status: 'complete' as const };
    return { nodes: [...nodes, newNode], edges };
}

/**
 * Handle node_removed event - remove node and connected edges
 */
export function handleNodeRemoved(
    nodes: AccumulatedNode[],
    edges: AccumulatedEdge[],
    nodeId: string
): { nodes: AccumulatedNode[]; edges: AccumulatedEdge[] } {
    const newNodes = nodes.filter(n => n.id !== nodeId);
    const newEdges = edges.filter(e => e.sourceId !== nodeId && e.targetId !== nodeId);
    return { nodes: newNodes, edges: newEdges };
}

/**
 * Handle edge_added event (edit mode) - add complete edge
 */
export function handleEdgeAdded(
    nodes: AccumulatedNode[],
    edges: AccumulatedEdge[],
    edge: AccumulatedEdge
): { nodes: AccumulatedNode[]; edges: AccumulatedEdge[] } {
    // Prevent duplicate edges
    if (edges.some(e => e.id === edge.id)) {
        return { nodes, edges };
    }

    const newEdge = { ...edge, status: 'complete' as const };
    const newEdges = [...edges, newEdge];

    // Update target node's parentIds and level
    const sourceNode = nodes.find(n => n.id === edge.sourceId);
    if (!sourceNode) {
        return { nodes, edges: newEdges };
    }

    const newNodes = nodes.map(n => {
        if (n.id === edge.targetId) {
            const newParentIds = n.parentIds.includes(edge.sourceId)
                ? n.parentIds
                : [...n.parentIds, edge.sourceId];
            const newLevel = Math.max(n.level, sourceNode.level + 1);
            return { ...n, parentIds: newParentIds, level: newLevel };
        }
        return n;
    });

    return { nodes: newNodes, edges: newEdges };
}

/**
 * Handle edge_removed event - remove edge and update target node's parentIds
 */
export function handleEdgeRemoved(
    nodes: AccumulatedNode[],
    edges: AccumulatedEdge[],
    edgeId: string
): { nodes: AccumulatedNode[]; edges: AccumulatedEdge[] } {
    const edge = edges.find(e => e.id === edgeId);
    const newEdges = edges.filter(e => e.id !== edgeId);

    if (!edge) {
        return { nodes, edges: newEdges };
    }

    const newNodes = nodes.map(n =>
        n.id === edge.targetId
            ? { ...n, parentIds: n.parentIds.filter(pid => pid !== edge.sourceId) }
            : n
    );

    return { nodes: newNodes, edges: newEdges };
}

/**
 * Handle node_processing_start event - node entering node drafter
 */
export function handleNodeProcessingStart(
    nodes: AccumulatedNode[],
    nodeId: string
): AccumulatedNode[] {
    return nodes.map(n =>
        n.id === nodeId
            ? { ...n, status: 'editing' as const, content: 'Selecting operation...' }
            : n
    );
}

/**
 * Handle node_operation_selected event - node drafter complete
 */
export function handleNodeOperationSelected(
    nodes: AccumulatedNode[],
    nodeId: string,
    operation: string,
    operationReason?: string
): AccumulatedNode[] {
    return nodes.map(n =>
        n.id === nodeId
            ? {
                  ...n,
                  operation,
                  operationReason,
                  content: `${operation}\nFilling config...`,
                  status: 'editing' as const,
              }
            : n
    );
}

/**
 * Handle node_config_filling event - incremental config update
 */
export function handleNodeConfigFilling(
    nodes: AccumulatedNode[],
    nodeId: string,
    field: string,
    value: unknown
): AccumulatedNode[] {
    return nodes.map(n => {
        if (n.id !== nodeId) return n;
        const updatedConfig = {
            ...(n.config || {}),
            [field]: value,
        };
        return {
            ...n,
            config: updatedConfig,
            content: `${n.operation || 'Configuring...'}\n${Object.keys(updatedConfig).length} fields`,
            status: 'editing' as const,
        };
    });
}

/**
 * Handle node_updated event - update node with operation/config/error
 */
export function handleNodeUpdated(
    nodes: AccumulatedNode[],
    nodeId: string,
    updates: {
        operation?: string;
        operationReason?: string;
        config?: Record<string, unknown>;
        userFields?: string[];
        error?: string;
    }
): AccumulatedNode[] {
    return nodes.map(n =>
        n.id === nodeId
            ? {
                  ...n,
                  operation: updates.operation ?? n.operation,
                  operationReason: updates.operationReason ?? n.operationReason,
                  config: updates.config ?? n.config,
                  userFields: updates.userFields ?? n.userFields,
                  error: updates.error,
                  status: updates.error ? ('error' as const) : ('complete' as const),
              }
            : n
    );
}

// ============================================================================
// GraphAccumulator class - stateful wrapper for use in CLI and tests
// ============================================================================

/**
 * Stateful graph accumulator that processes a stream of events.
 * Used by the CLI for Python tests and can be used for debugging.
 */
export class GraphAccumulator {
    private nodes: AccumulatedNode[] = [];
    private edges: AccumulatedEdge[] = [];
    private inputs: AccumulatedInput[] = [];
    private workflowName = '';
    private workflowSummary = '';
    private errors: string[] = [];

    /**
     * Handle a raw event from the backend.
     * This mirrors the processSocketEvent logic in useWorkflowGeneration.ts
     */
    handleEvent(eventType: string, eventData: Record<string, unknown>): void {
        switch (eventType) {
            case 'node_start':
                if (eventData.node) {
                    const nodeData = eventData.node as Record<string, unknown>;
                    const level = typeof nodeData.level === 'number' ? nodeData.level : 0;
                    const node: AccumulatedNode = {
                        id: nodeData.id as string,
                        type: nodeData.type as string,
                        label: nodeData.label as string,
                        description: (nodeData.description as string) || '',
                        content: (nodeData.content as string) || (nodeData.label as string),
                        parentIds: (nodeData.parentIds as string[]) || [],
                        level,
                        index: (nodeData.index as number) || 0,
                        status: 'adding',
                    };
                    this.nodes = handleNodeStart(this.nodes, node);
                }
                break;

            case 'node_typing':
                this.nodes = handleNodeTyping(
                    this.nodes,
                    eventData.nodeId as string,
                    eventData.content as string
                );
                break;

            case 'node_complete':
                this.nodes = handleNodeComplete(this.nodes, eventData.nodeId as string);
                break;

            case 'edge_add':
                if (eventData.edge) {
                    const edgeData = eventData.edge as Record<string, unknown>;
                    const edge: AccumulatedEdge = {
                        id: edgeData.id as string,
                        sourceId: edgeData.sourceId as string,
                        targetId: edgeData.targetId as string,
                        sourceHandle: edgeData.sourceHandle as string | undefined,
                        targetHandle: edgeData.targetHandle as string | undefined,
                        status: 'animating',
                    };
                    const result = handleEdgeAdd(this.nodes, this.edges, edge);
                    this.nodes = result.nodes;
                    this.edges = result.edges;
                }
                break;

            case 'edge_complete':
                this.edges = handleEdgeComplete(this.edges, eventData.edgeId as string);
                break;

            case 'input_request':
                if (eventData.request) {
                    const reqData = eventData.request as Record<string, unknown>;
                    const request: AccumulatedInput = {
                        id: reqData.id as string,
                        nodeId: reqData.nodeId as string,
                        type: reqData.type as 'credential' | 'selection' | 'text' | 'config',
                        label: reqData.label as string,
                        description: reqData.description as string,
                        credentialType: reqData.credentialType as string | undefined,
                        acceptedCredentialTypes: reqData.acceptedCredentialTypes as string[] | undefined,
                        options: reqData.options as { id: string; label: string; icon?: string }[] | undefined,
                        multiple: reqData.multiple as boolean | undefined,
                        required: (reqData.required as boolean) ?? true,
                        nodeType: reqData.nodeType as string | undefined,
                        fieldKey: reqData.fieldKey as string | undefined,
                        fieldSchema: reqData.fieldSchema as Record<string, unknown> | undefined,
                        dependsOn: reqData.dependsOn as string | undefined,
                        requiredCredentialTypes: reqData.requiredCredentialTypes as string[] | undefined,
                        credentialIds: reqData.credentialIds as Record<string, string> | undefined,
                        nodeConfig: reqData.nodeConfig as Record<string, any> | undefined,
                    };
                    this.inputs = handleInputRequest(this.inputs, request);
                }
                break;

            case 'generation_complete':
                if (eventData.name) {
                    this.workflowName = eventData.name as string;
                }
                if (eventData.summary) {
                    this.workflowSummary = eventData.summary as string;
                }
                break;

            case 'node_processing_start':
                this.nodes = handleNodeProcessingStart(this.nodes, eventData.nodeId as string);
                break;

            case 'node_operation_selected':
                this.nodes = handleNodeOperationSelected(
                    this.nodes,
                    eventData.nodeId as string,
                    eventData.operation as string,
                    eventData.operationReason as string | undefined
                );
                break;

            case 'node_config_filling':
                this.nodes = handleNodeConfigFilling(
                    this.nodes,
                    eventData.nodeId as string,
                    eventData.field as string,
                    eventData.value
                );
                break;

            case 'node_updated':
                this.nodes = handleNodeUpdated(this.nodes, eventData.nodeId as string, {
                    operation: eventData.operation as string | undefined,
                    operationReason: eventData.operationReason as string | undefined,
                    config: eventData.config as Record<string, unknown> | undefined,
                    userFields: eventData.userFields as string[] | undefined,
                    error: eventData.error as string | undefined,
                });
                break;

            case 'node_added':
                if (eventData.node) {
                    const nodeData = eventData.node as Record<string, unknown>;
                    const node: AccumulatedNode = {
                        id: nodeData.id as string,
                        type: nodeData.type as string,
                        label: nodeData.label as string,
                        description: (nodeData.description as string) || '',
                        content: (nodeData.content as string) || (nodeData.label as string),
                        parentIds: (nodeData.parentIds as string[]) || [],
                        level: (nodeData.level as number) || 0,
                        index: (nodeData.index as number) || 0,
                        status: 'complete',
                    };
                    const result = handleNodeAdded(this.nodes, this.edges, node);
                    this.nodes = result.nodes;
                    this.edges = result.edges;
                }
                break;

            case 'node_removed':
                const nodeRemoveResult = handleNodeRemoved(
                    this.nodes,
                    this.edges,
                    eventData.nodeId as string
                );
                this.nodes = nodeRemoveResult.nodes;
                this.edges = nodeRemoveResult.edges;
                // Also remove inputs for removed node
                this.inputs = this.inputs.filter(i => i.nodeId !== eventData.nodeId);
                break;

            case 'edge_added':
                if (eventData.edge) {
                    const edgeData = eventData.edge as Record<string, unknown>;
                    const edge: AccumulatedEdge = {
                        id: edgeData.id as string,
                        sourceId: edgeData.sourceId as string,
                        targetId: edgeData.targetId as string,
                        sourceHandle: edgeData.sourceHandle as string | undefined,
                        targetHandle: edgeData.targetHandle as string | undefined,
                        status: 'complete',
                    };
                    const result = handleEdgeAdded(this.nodes, this.edges, edge);
                    this.nodes = result.nodes;
                    this.edges = result.edges;
                }
                break;

            case 'edge_removed':
                const edgeRemoveResult = handleEdgeRemoved(
                    this.nodes,
                    this.edges,
                    eventData.edgeId as string
                );
                this.nodes = edgeRemoveResult.nodes;
                this.edges = edgeRemoveResult.edges;
                break;

            case 'error':
                this.errors.push((eventData.error as string) || 'Unknown error');
                break;
        }
    }

    /**
     * Get current state
     */
    getState(): AccumulatorState {
        return {
            nodes: this.nodes,
            edges: this.edges,
            inputs: this.inputs,
            workflowName: this.workflowName,
            workflowSummary: this.workflowSummary,
        };
    }

    /**
     * Get nodes
     */
    getNodes(): AccumulatedNode[] {
        return this.nodes;
    }

    /**
     * Get edges
     */
    getEdges(): AccumulatedEdge[] {
        return this.edges;
    }

    /**
     * Get inputs
     */
    getInputs(): AccumulatedInput[] {
        return this.inputs;
    }

    /**
     * Get errors
     */
    getErrors(): string[] {
        return this.errors;
    }

    /**
     * Get final graph in ReactFlow-compatible format
     */
    getFinalGraph(): {
        type: string;
        version: string;
        nodes: Array<{
            id: string;
            type: string;
            position: { x: number; y: number };
            config: Record<string, unknown>;
        }>;
        edges: Array<{
            id: string;
            source: string;
            target: string;
            sourceHandle?: string;
            targetHandle?: string;
            type: string;
        }>;
        name: string;
        summary: string;
    } {
        return {
            type: 'noclick-workflow',
            version: '1.0',
            nodes: this.nodes.map(n => ({
                id: n.id,
                type: n.type,
                position: n.position || { x: 0, y: 0 },
                config: {
                    label: n.label,
                    goal: n.description,
                    operation: n.operation,
                    operationReason: n.operationReason,
                    userFields: n.userFields,
                    ...(n.config || {}),
                },
            })),
            edges: this.edges.map(e => ({
                id: e.id,
                source: e.sourceId,
                target: e.targetId,
                sourceHandle: e.sourceHandle,
                targetHandle: e.targetHandle,
                type: 'animated',
            })),
            name: this.workflowName,
            summary: this.workflowSummary,
        };
    }

    /**
     * Verify that edges from iteration nodes have correct sourceHandle values
     */
    verifyIterationEdges(): {
        iterationNodes: string[];
        edgesFromIteration: Array<{
            id: string;
            source: string;
            target: string;
            sourceHandle?: string;
        }>;
        missingHandles: Array<{
            id: string;
            source: string;
            target: string;
            sourceHandle?: string;
        }>;
        correctHandles: Array<{
            id: string;
            source: string;
            target: string;
            sourceHandle?: string;
        }>;
    } {
        const iterationNodes = this.nodes
            .filter(n => n.type === 'iteration')
            .map(n => n.id);

        const edgesFromIteration = this.edges
            .filter(e => iterationNodes.includes(e.sourceId))
            .map(e => ({
                id: e.id,
                source: e.sourceId,
                target: e.targetId,
                sourceHandle: e.sourceHandle,
            }));

        const missingHandles = edgesFromIteration.filter(
            e => !e.sourceHandle || !['loop', 'done'].includes(e.sourceHandle)
        );

        const correctHandles = edgesFromIteration.filter(
            e => e.sourceHandle && ['loop', 'done'].includes(e.sourceHandle)
        );

        return {
            iterationNodes,
            edgesFromIteration,
            missingHandles,
            correctHandles,
        };
    }
}
