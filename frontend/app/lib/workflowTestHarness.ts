// Workflow Test Harness - Exposes debugging capabilities for workflow node output persistence.
// Call from terminal via: make exec cmd="await __workflowTest.compare()"
//
// This harness allows testing:
// - IndexedDB persistence
// - React state after refresh
// - Backend data comparison
// - Full refresh cycle testing

import { valtioCache } from '~/lib/indexeddb';
import { createWorkflowNode, normalizeNodeUpdatePayload, updateNodeInList } from '~/lib/applyNodeUpdate';
import type { Edge, Node } from '@xyflow/react';
import type { Dispatch, SetStateAction } from 'react';
import type { EventWithName } from '~/lib/socket-sender';

interface NodeOutputData {
    output?: unknown;
    outputTimestamp?: number;
    _outputStoredLocally?: boolean;
}

interface ComparisonResult {
    workflowId: string;
    sources: {
        indexedDB: Record<string, NodeOutputData>;
        reactState: Record<string, NodeOutputData>;
        backend: Record<string, NodeOutputData>;
    };
    nodeIds: string[];
    mismatches: Array<{
        nodeId: string;
        issue: string;
        details: {
            indexedDB?: unknown;
            reactState?: unknown;
            backend?: unknown;
        };
    }>;
    summary: string;
}

interface TraceEntry {
    timestamp: number;
    event: string;
    data?: unknown;
}

// Module state
let traceLog: TraceEntry[] = [];
let traceEnabled = false;

// Reference to FlowCanvas state (set by FlowCanvas component)
let flowCanvasStateRef: {
    workflowId: string | null;
    nodes: Node[];
    edges: Edge[];
    getNodeOutput: (nodeId: string) => NodeOutputData | undefined;
    setNodes?: Dispatch<SetStateAction<Node[]>>;
    setEdges?: Dispatch<SetStateAction<Edge[]>>;
    // Live ref to the activeExecutions Map (the source of truth behind the
    // Run/Stop button). A ref so the harness always reads current state.
    activeExecutionsRef?: { current: Map<string, unknown> };
} | null = null;

// Reference to socket sender
let socketSenderRef: {
    sendEventAsync: <E extends EventWithName>(event: E) => Promise<unknown>;
} | null = null;

function trace(event: string, data?: unknown) {
    if (traceEnabled) {
        const entry = { timestamp: Date.now(), event, data };
        traceLog.push(entry);
        console.log(`[WorkflowTest] ${event}`, data ?? '');
    }
}

const harness = {
    // === State Registration (called by components) ===

    registerFlowCanvas(state: typeof flowCanvasStateRef) {
        flowCanvasStateRef = state;
        trace('FlowCanvas registered', { workflowId: state?.workflowId });
    },

    registerSocketSender(sender: typeof socketSenderRef) {
        socketSenderRef = sender;
        trace('Socket sender registered');
    },

    unregisterFlowCanvas() {
        flowCanvasStateRef = null;
        trace('FlowCanvas unregistered');
    },

    // === State Inspection ===

    getWorkflowId(): string | null {
        return flowCanvasStateRef?.workflowId ?? null;
    },

    /** Execution IDs the UI currently treats as in-flight (drives the
     *  Run/Stop button). Used by execution-recovery tests. */
    getActiveExecutionIds(): string[] {
        const map = flowCanvasStateRef?.activeExecutionsRef?.current;
        return map ? [...map.keys()] : [];
    },

    async getIndexedDB(workflowId?: string): Promise<Record<string, NodeOutputData>> {
        const id = workflowId ?? flowCanvasStateRef?.workflowId;
        if (!id) return {};

        // Check ALL possible key formats:
        // 1. Old useWorkflowNodeOutputs format: workflow-outputs:{id}
        // 2. New useWorkflowNodeOutputs format: workflow-large-outputs:{id}
        // 3. useCachedValtioState format: /workflow/{id}:nodeOutputs
        const [oldFormat, newFormat, valtioFormat] = await Promise.all([
            valtioCache.get<Record<string, NodeOutputData>>(`workflow-outputs:${id}`),
            valtioCache.get<Record<string, NodeOutputData>>(`workflow-large-outputs:${id}`),
            valtioCache.get<Record<string, NodeOutputData>>(`/workflow/${id}:nodeOutputs`),
        ]);

        // Smart merge: per-node, prefer entries with actual output data
        const allNodeIds = new Set([
            ...Object.keys(valtioFormat ?? {}),
            ...Object.keys(oldFormat ?? {}),
            ...Object.keys(newFormat ?? {}),
        ]);

        const result: Record<string, NodeOutputData> = {};
        for (const nodeId of allNodeIds) {
            const valtio = (valtioFormat ?? {})[nodeId];
            const old = (oldFormat ?? {})[nodeId];
            const newer = (newFormat ?? {})[nodeId];

            // Prefer the source that has actual output, prioritizing newer formats
            if (newer?.output !== undefined) {
                result[nodeId] = newer;
            } else if (old?.output !== undefined) {
                result[nodeId] = old;
            } else if (valtio?.output !== undefined) {
                result[nodeId] = valtio;
            } else {
                // No output in any source, merge metadata
                result[nodeId] = { ...valtio, ...old, ...newer };
            }
        }
        return result;
    },

    // Get IndexedDB data broken down by key format (for debugging)
    async getIndexedDBByFormat(workflowId?: string): Promise<{
        oldFormat: Record<string, NodeOutputData> | null;
        newFormat: Record<string, NodeOutputData> | null;
        valtioFormat: Record<string, NodeOutputData> | null;
    }> {
        const id = workflowId ?? flowCanvasStateRef?.workflowId;
        if (!id) return { oldFormat: null, newFormat: null, valtioFormat: null };

        const [oldFormat, newFormat, valtioFormat] = await Promise.all([
            valtioCache.get<Record<string, NodeOutputData>>(`workflow-outputs:${id}`),
            valtioCache.get<Record<string, NodeOutputData>>(`workflow-large-outputs:${id}`),
            valtioCache.get<Record<string, NodeOutputData>>(`/workflow/${id}:nodeOutputs`),
        ]);

        return { oldFormat, newFormat, valtioFormat };
    },

    getReactState(): Record<string, NodeOutputData> {
        if (!flowCanvasStateRef?.nodes) return {};

        const result: Record<string, NodeOutputData> = {};
        for (const node of flowCanvasStateRef.nodes) {
            if (node.data?.output !== undefined) {
                result[node.id] = {
                    output: node.data.output,
                    outputTimestamp: node.data.outputTimestamp as number | undefined,
                };
            }
        }
        return result;
    },

    // Get all node data (including config) for debugging
    getNodes(): Node[] {
        return flowCanvasStateRef?.nodes ?? [];
    },

    // Get all edges (for upstream/downstream resolution, e.g. the SDK bridge's
    // useInputs scoping). Reads the live FlowCanvas edges ref.
    getEdges(): Edge[] {
        return flowCanvasStateRef?.edges ?? [];
    },

    // Get a specific node's data by ID
    getNodeById(nodeId: string): Node | null {
        if (!flowCanvasStateRef?.nodes) return null;
        const node = flowCanvasStateRef.nodes.find(n => n.id === nodeId);
        if (!node) return null;
        return node;
    },

    // Add a node by ID + type + config. Used by integration tests that need to
    // exercise a specific block type without driving the canvas drag-drop UI.
    addNode(
        nodeId: string,
        type: string,
        config: Record<string, unknown> = {},
        position: { x: number; y: number } = { x: 200, y: 200 },
    ): boolean {
        if (!flowCanvasStateRef?.setNodes) {
            console.warn('[WorkflowTest] setNodes not registered');
            return false;
        }
        trace('Adding node', { nodeId, type });
        const node = createWorkflowNode(nodeId, type, position, config);
        flowCanvasStateRef.setNodes((nodes) => [
            ...nodes.filter(n => n.id !== nodeId),
            node,
        ]);
        return true;
    },

    // Delete a node by ID (also removes connected edges)
    deleteNode(nodeId: string): boolean {
        if (!flowCanvasStateRef?.setNodes || !flowCanvasStateRef?.setEdges) {
            console.warn('[WorkflowTest] setNodes/setEdges not registered');
            return false;
        }
        trace('Deleting node', { nodeId });
        flowCanvasStateRef.setNodes((nodes) => nodes.filter(n => n.id !== nodeId));
        flowCanvasStateRef.setEdges((edges) => edges.filter(e => e.source !== nodeId && e.target !== nodeId));
        return true;
    },

    // Add an edge between two nodes
    addEdge(edge: { source: string; target: string; sourceHandle?: string; targetHandle?: string }): boolean {
        if (!flowCanvasStateRef?.setEdges) {
            console.warn('[WorkflowTest] setEdges not registered');
            return false;
        }
        // Refuse dangling edges: an edge referencing a nonexistent node id
        // poisons saved state — the backend formerly read it as a false
        // "cycle" (ghost source never completes, target never unblocks).
        const nodeIds = new Set((flowCanvasStateRef.nodes ?? []).map((n) => n.id));
        if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
            console.warn(`[WorkflowTest] addEdge refused: unknown node in ${edge.source} -> ${edge.target}`);
            return false;
        }
        const edgeId = `${edge.source}-${edge.target}`;
        trace('Adding edge', { edgeId, ...edge });
        flowCanvasStateRef.setEdges((edges) => [
            ...edges.filter(e => e.id !== edgeId), // Remove if exists
            {
                id: edgeId,
                source: edge.source,
                target: edge.target,
                sourceHandle: edge.sourceHandle,
                targetHandle: edge.targetHandle,
                type: 'animated',
            },
        ]);
        return true;
    },

    // Update a node's data by ID (merges via applyNodeUpdate)
    updateNodeData(nodeId: string, dataUpdates: Record<string, unknown>): boolean {
        if (!flowCanvasStateRef?.setNodes) {
            console.warn('[WorkflowTest] setNodes not registered');
            return false;
        }
        trace('Updating node data', { nodeId, updates: Object.keys(dataUpdates) });
        const update = normalizeNodeUpdatePayload(dataUpdates as Record<string, any>);
        flowCanvasStateRef.setNodes((nodes) => updateNodeInList(nodes, nodeId, update));
        return true;
    },

    // Run a node with its dependencies (runs predecessors first)
    async runNodeWithDeps(nodeId: string, workflowId?: string): Promise<{ success: boolean; output?: unknown; error?: string }> {
        const id = workflowId ?? flowCanvasStateRef?.workflowId;
        if (!id || !socketSenderRef) {
            return { success: false, error: 'No workflow or socket sender' };
        }
        trace('Running node with dependencies', { nodeId, workflowId: id });

        try {
            // Use workflow:execute with node_ids to run just this node and its dependencies
            const response = await socketSenderRef.sendEventAsync({
                event_name: 'workflow:execute',
                workflow_id: id,
                node_ids: [nodeId],
            }) as { success?: boolean; error?: string };

            if (response?.error) {
                return { success: false, error: response.error };
            }

            // Wait a bit for outputs to propagate
            await new Promise(resolve => setTimeout(resolve, 500));

            // Get the node output from React state
            const output = flowCanvasStateRef?.getNodeOutput?.(nodeId);
            return { success: true, output: output?.output };
        } catch (e) {
            return { success: false, error: String(e) };
        }
    },

    async getBackend(workflowId?: string): Promise<Record<string, NodeOutputData>> {
        const id = workflowId ?? flowCanvasStateRef?.workflowId;
        if (!id || !socketSenderRef) return {};

        try {
            // Node outputs live solely in the CAS now — fetch the latest per node
            // via the CAS-backed get_node_outputs channel (no longer embedded in
            // the workflow:get graph JSONB).
            const response = await socketSenderRef.sendEventAsync({
                event_name: 'workflow:get_node_outputs',
                workflow_id: id,
            }) as { outputs?: Record<string, unknown> };

            const outputs = response?.outputs ?? {};
            const result: Record<string, NodeOutputData> = {};
            for (const [nodeId, output] of Object.entries(outputs)) {
                result[nodeId] = { output, outputTimestamp: Date.now() };
            }
            return result;
        } catch (error) {
            console.error('[WorkflowTest] Failed to get backend data:', error);
            return {};
        }
    },

    // === Comparison ===

    async compare(workflowId?: string): Promise<ComparisonResult> {
        const id = workflowId ?? flowCanvasStateRef?.workflowId ?? 'unknown';
        trace('Comparing sources', { workflowId: id });

        const [indexedDB, backend] = await Promise.all([
            this.getIndexedDB(workflowId),
            this.getBackend(workflowId),
        ]);
        const reactState = this.getReactState();

        // Collect all node IDs
        const nodeIds = [...new Set([
            ...Object.keys(indexedDB),
            ...Object.keys(reactState),
            ...Object.keys(backend),
        ])].sort();

        // Find mismatches
        const mismatches: ComparisonResult['mismatches'] = [];

        for (const nodeId of nodeIds) {
            const idb = indexedDB[nodeId];
            const react = reactState[nodeId];
            const back = backend[nodeId];

            // Check if node has output in any source
            const hasIdb = idb?.output !== undefined;
            const hasReact = react?.output !== undefined;
            const hasBack = back?.output !== undefined || back?._outputStoredLocally;

            if (hasBack && back?._outputStoredLocally && !hasIdb) {
                mismatches.push({
                    nodeId,
                    issue: 'Large output marked in backend but missing from IndexedDB',
                    details: { backend: back, indexedDB: idb },
                });
            } else if (hasBack && !hasReact) {
                mismatches.push({
                    nodeId,
                    issue: 'Output in backend but not in React state',
                    details: { backend: back, reactState: react },
                });
            } else if (hasIdb && !hasReact) {
                mismatches.push({
                    nodeId,
                    issue: 'Output in IndexedDB but not in React state',
                    details: { indexedDB: idb, reactState: react },
                });
            } else if (hasReact && !hasBack && !hasIdb) {
                mismatches.push({
                    nodeId,
                    issue: 'Output in React state but not persisted anywhere',
                    details: { reactState: react, backend: back, indexedDB: idb },
                });
            }
        }

        const summary = mismatches.length === 0
            ? `✅ All ${nodeIds.length} nodes match across sources`
            : `❌ ${mismatches.length} mismatches found across ${nodeIds.length} nodes`;

        return {
            workflowId: id,
            sources: { indexedDB, reactState, backend },
            nodeIds,
            mismatches,
            summary,
        };
    },

    // === Actions ===

    refresh() {
        trace('Refreshing page');
        window.location.reload();
    },

    async simulateRefreshCycle(workflowId?: string): Promise<{
        before: ComparisonResult;
        message: string;
    }> {
        const before = await this.compare(workflowId);
        trace('Before refresh', before);

        return {
            before,
            message: 'Call __workflowTest.refresh() to reload, then __workflowTest.compare() to check after',
        };
    },

    // === Tracing ===

    enableTrace() {
        traceEnabled = true;
        traceLog = [];
        console.log('[WorkflowTest] Tracing enabled');
    },

    disableTrace() {
        traceEnabled = false;
        console.log('[WorkflowTest] Tracing disabled');
    },

    getTrace(): TraceEntry[] {
        return [...traceLog];
    },

    clearTrace() {
        traceLog = [];
    },

    // === Utilities ===

    async dumpAll(workflowId?: string) {
        const comparison = await this.compare(workflowId);
        console.log('=== Workflow Test Harness Dump ===');
        console.log('Workflow ID:', comparison.workflowId);
        console.log('\n--- IndexedDB ---');
        console.log(JSON.stringify(comparison.sources.indexedDB, null, 2));
        console.log('\n--- React State ---');
        console.log(JSON.stringify(comparison.sources.reactState, null, 2));
        console.log('\n--- Backend ---');
        console.log(JSON.stringify(comparison.sources.backend, null, 2));
        console.log('\n--- Summary ---');
        console.log(comparison.summary);
        if (comparison.mismatches.length > 0) {
            console.log('\n--- Mismatches ---');
            for (const m of comparison.mismatches) {
                console.log(`  ${m.nodeId}: ${m.issue}`);
            }
        }
        return comparison;
    },

    // Send a socket event (for testing MCP commands, workflow execution, etc.)
    async sendEvent(event: EventWithName): Promise<unknown> {
        if (!socketSenderRef) {
            return { success: false, error: 'No socket sender registered' };
        }
        trace('Sending event', event);
        return socketSenderRef.sendEventAsync(event);
    },

    // Debug info
    debug() {
        return {
            hasFlowCanvasState: !!flowCanvasStateRef,
            hasSocketSender: !!socketSenderRef,
            workflowId: flowCanvasStateRef?.workflowId ?? null,
            nodeCount: flowCanvasStateRef?.nodes?.length ?? 0,
            traceEnabled,
            traceLogLength: traceLog.length,
        };
    },

    help() {
        return `
Workflow Test Harness Commands:

State Inspection:
  __workflowTest.getWorkflowId()          - Get current workflow ID
  __workflowTest.getIndexedDB()           - Get IndexedDB outputs
  __workflowTest.getReactState()          - Get React component outputs
  __workflowTest.getBackend()             - Get backend persisted outputs

Comparison:
  __workflowTest.compare()                - Compare all three sources
  __workflowTest.dumpAll()                - Dump all data with formatting

Actions:
  __workflowTest.refresh()                - Reload the page
  __workflowTest.simulateRefreshCycle()   - Check before refresh

Tracing:
  __workflowTest.enableTrace()            - Start tracing
  __workflowTest.disableTrace()           - Stop tracing
  __workflowTest.getTrace()               - Get trace log
  __workflowTest.clearTrace()             - Clear trace log
`.trim();
    },
};

// Register on window
export function register() {
    if (typeof window !== 'undefined') {
        (window as any).__workflowTest = harness;
        console.log('[WorkflowTest] Harness registered. Type __workflowTest.help() for commands.');
    }
}

// Export for component registration
export const workflowTestHarness = harness;
