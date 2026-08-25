/**
 * Hook for handling MCP workflow operations with bidirectional communication.
 *
 * Architecture:
 * - Workflow mutations (add/remove nodes, edges, config) are handled by the
 *   backend's update_workflow XML tool and useMCPBuilderEvents for real-time sync
 * - Frontend-required operations (get_selected, get_state, run) use request/response pattern
 * - update_interface dual-delivery keeps interface grid state in sync
 */

import { useCallback, useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import { Node, Edge } from '@xyflow/react';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEvent } from '~/lib/socket-sender';
import type { InterfaceGridState, WorkflowInterfaceHandle } from '~/components/interface/WorkflowInterface';
import { sdkDebugStore } from '~/lib/sdk-debug-store';

function isInterfaceGridState(value: unknown): value is InterfaceGridState {
    if (!value || typeof value !== 'object') return false;
    const state = value as { layout?: unknown; tabOrder?: unknown };
    return (
        Array.isArray(state.layout) &&
        (state.tabOrder === undefined ||
            (Array.isArray(state.tabOrder) && state.tabOrder.every((tab) => typeof tab === 'string')))
    );
}

// Track last user interaction (module-level so it persists across re-renders)
let _lastInteractionAt = Date.now();
if (typeof document !== 'undefined') {
    document.addEventListener('pointerdown', () => { _lastInteractionAt = Date.now(); }, true);
    document.addEventListener('keydown', () => { _lastInteractionAt = Date.now(); }, true);
}

// Types for MCP request/response (these will be in generated types after regeneration)
interface WorkflowMCPRequest {
    request_id: string;
    request_type: string;
    params: Record<string, any>;
}

interface WorkflowMCPResponse {
    event_name: 'workflow:mcp:response';
    request_id: string;
    data: any;
    error?: string | null;
}

interface UseWorkflowMCPHandlerProps {
    nodes: Node[];
    edges: Edge[];
    selectedNode: Node | null;
    workflowId?: string;
    workflowName?: string;
    isWorkflowRunning: boolean;
    setNodes: (setter: (prevNodes: Node[]) => Node[]) => void;
    setEdges: (setter: (prevEdges: Edge[]) => Edge[]) => void;
    captureState: (nodes: Node[], edges: Edge[]) => void;
    onRunWorkflow?: () => void;
    onRunSingleNode?: (nodeId: string) => { success: boolean; error?: string };
    onNavigateToWorkflow?: (workflowId: string) => void;
    interfaceGridStateRef?: RefObject<InterfaceGridState | null>;
    workflowInterfaceRef?: RefObject<WorkflowInterfaceHandle | null>;
}

// Store pending output requests that are waiting for a node to complete
interface PendingOutputRequest {
    request_id: string;
    node_id: string;
    timeout: number;
    timeoutId: NodeJS.Timeout;
}

/**
 * Hook that handles MCP requests from the backend for workflow operations.
 *
 * The backend sends `workflow:mcp:request` events, and this hook responds
 * with `workflow:mcp:response` events containing the requested data.
 */
export function useWorkflowMCPHandler({
    nodes,
    edges,
    selectedNode,
    workflowId,
    workflowName,
    isWorkflowRunning,
    setNodes,
    setEdges,
    captureState,
    onRunWorkflow,
    onRunSingleNode,
    onNavigateToWorkflow,
    interfaceGridStateRef,
    workflowInterfaceRef,
}: UseWorkflowMCPHandlerProps) {
    // Track pending output requests waiting for node completion
    const pendingOutputRequestsRef = useRef<Map<string, PendingOutputRequest>>(new Map());

    // Helper to send response back to backend
    const sendResponse = useCallback((requestId: string, data: any, error?: string | null) => {
        const response: WorkflowMCPResponse = {
            event_name: 'workflow:mcp:response',
            request_id: requestId,
            data,
            error: error || null,
        };
        sendEvent(response as any);
        // Also dispatch for event relay path (cross-container request-response)
        window.dispatchEvent(new CustomEvent('relay:mcp_response', {
            detail: { request_id: requestId, data, error: error || null },
        }));
    }, []);

    // Handle getting workflow state
    const handleGetState = useCallback((requestId: string) => {
        const data: Record<string, any> = {
            workflowId,
            workflowName,
            nodes: nodes.map(n => ({
                id: n.id,
                type: n.type,
                position: n.position,
                data: n.data,
            })),
            edges: edges.map(e => ({
                id: e.id,
                source: e.source,
                target: e.target,
                sourceHandle: e.sourceHandle,
            })),
            selectedNodeId: selectedNode?.id || null,
            isRunning: isWorkflowRunning,
            interface: interfaceGridStateRef?.current ?? null,
            isTabVisible: document.visibilityState === 'visible',
            lastInteractionAt: _lastInteractionAt,
        };
        sendResponse(requestId, data);
    }, [nodes, edges, selectedNode, workflowId, workflowName, isWorkflowRunning, interfaceGridStateRef, sendResponse]);

    // Handle getting selected node
    const handleGetSelected = useCallback((requestId: string) => {
        if (!selectedNode) {
            sendResponse(requestId, null);
            return;
        }
        sendResponse(requestId, {
            id: selectedNode.id,
            type: selectedNode.type,
            data: selectedNode.data,
            position: selectedNode.position,
            workflow_id: workflowId,
        });
    }, [selectedNode, workflowId, sendResponse]);

    // Handle getting node output
    const handleGetOutput = useCallback((requestId: string, params: { node_id: string; timeout?: number }) => {
        const { node_id, timeout = 60 } = params;
        const node = nodes.find(n => n.id === node_id);

        if (!node) {
            sendResponse(requestId, null, `Node ${node_id} not found`);
            return;
        }

        // Check if node has output already
        const output = node.data?.output;
        if (output !== undefined && output !== null) {
            sendResponse(requestId, output);
            return;
        }

        // Check node execution status
        const status = node.data?.status;

        // If node is not running and has no output, it hasn't been executed
        if (status !== 'running' && status !== 'pending') {
            sendResponse(requestId, null, `Node ${node_id} has no output (status: ${status || 'idle'})`);
            return;
        }

        // Node is running - set up a pending request to wait for completion
        const timeoutId = setTimeout(() => {
            const pending = pendingOutputRequestsRef.current.get(requestId);
            if (pending) {
                pendingOutputRequestsRef.current.delete(requestId);
                sendResponse(requestId, null, `Timeout waiting for node ${node_id} output`);
            }
        }, timeout * 1000);

        pendingOutputRequestsRef.current.set(requestId, {
            request_id: requestId,
            node_id,
            timeout,
            timeoutId,
        });
    }, [nodes, sendResponse]);

    // Handle getting node input
    const handleGetInput = useCallback((requestId: string, params: { node_id: string }) => {
        const { node_id } = params;
        const node = nodes.find(n => n.id === node_id);

        if (!node) {
            sendResponse(requestId, {}, `Node ${node_id} not found`);
            return;
        }

        // Find all edges targeting this node
        const inEdges = edges.filter(e => e.target === node_id);

        // Collect outputs from all source nodes
        const inputs: Record<string, any> = {};
        inEdges.forEach(edge => {
            const sourceNode = nodes.find(n => n.id === edge.source);
            if (sourceNode?.data?.output !== undefined) {
                inputs[edge.source] = sourceNode.data.output;
            }
        });

        sendResponse(requestId, inputs);
    }, [nodes, edges, sendResponse]);

    // Handle running the workflow
    const handleRunWorkflow = useCallback((requestId: string) => {
        if (!workflowId) {
            sendResponse(requestId, { success: false }, 'No workflow open');
            return;
        }

        if (onRunWorkflow) {
            onRunWorkflow();
        }

        // Return immediately - workflow execution is async
        sendResponse(requestId, {
            workflow_id: workflowId,
            started: true,
        });
    }, [workflowId, onRunWorkflow, sendResponse]);

    // Handle opening a workflow
    const handleOpenWorkflow = useCallback((requestId: string, params: { workflow_id: string }) => {
        const { workflow_id } = params;

        if (onNavigateToWorkflow) {
            onNavigateToWorkflow(workflow_id);
            sendResponse(requestId, { success: true });
        } else {
            sendResponse(requestId, { success: false }, 'Navigation not available');
        }
    }, [onNavigateToWorkflow, sendResponse]);

    // Handle running a single node
    const handleRunNode = useCallback((requestId: string, params: { node_id: string }) => {
        const { node_id } = params;

        if (!workflowId) {
            sendResponse(requestId, { success: false }, 'No workflow open');
            return;
        }

        if (!onRunSingleNode) {
            sendResponse(requestId, { success: false }, 'Single node execution not available');
            return;
        }

        const result = onRunSingleNode(node_id);
        if (result.success) {
            sendResponse(requestId, { success: true, node_id });
        } else {
            sendResponse(requestId, { success: false }, result.error || 'Failed to run node');
        }
    }, [workflowId, onRunSingleNode, sendResponse]);

    // Main request handler
    const handleMCPRequest = useCallback((request: WorkflowMCPRequest) => {
        const { request_id, request_type, params } = request;

        console.log('[WorkflowMCP] Received request:', request_type, params);

        // If the request targets a specific workflow, ignore if we don't have it open
        const targetWorkflow = (params as any)?._workflow_id;
        if (targetWorkflow && targetWorkflow !== workflowId) {
            return; // Silent ignore — let the correct frontend respond
        }

        // Reject requests if workflowId is a temp ID (workflow still being created)
        if (workflowId?.startsWith('temp-')) {
            sendResponse(request_id, null, 'Workflow is still being created. Please wait.');
            return;
        }

        try {
            switch (request_type) {
                case 'get_state':
                    handleGetState(request_id);
                    break;
                case 'get_selected':
                    handleGetSelected(request_id);
                    break;
                case 'get_output':
                    handleGetOutput(request_id, params as { node_id: string; timeout?: number });
                    break;
                case 'get_input':
                    handleGetInput(request_id, params as { node_id: string });
                    break;
                case 'run_workflow':
                    handleRunWorkflow(request_id);
                    break;
                // open_workflow is handled by useMCPNavigation at dashboard level
                case 'run_node':
                    handleRunNode(request_id, params as { node_id: string });
                    break;
                case 'get_sdk_logs': {
                    const filter = (params as any)?.filter || 'errors';
                    const limit = (params as any)?.limit || 20;
                    let entries = sdkDebugStore.getEntries();
                    if (filter === 'errors') entries = entries.filter(e => e.status === 'error');
                    else if (filter === 'pending') entries = entries.filter(e => e.status === 'pending');
                    sendResponse(request_id, entries.slice(-limit).map(e => ({
                        method: e.method, status: e.status, error: e.error,
                        caller: e.nodeId, timestamp: e.timestamp,
                        duration: e.duration, params: e.params,
                        ...(e.result !== undefined ? { result: e.result } : {}),
                    })));
                    break;
                }
                default:
                    sendResponse(request_id, null, `Unknown request type: ${request_type}`);
            }
        } catch (e) {
            const errorMessage = e instanceof Error ? e.message : String(e);
            console.error('[WorkflowMCP] Error handling request:', errorMessage);
            sendResponse(request_id, null, errorMessage);
        }
    }, [
        workflowId,
        handleGetState,
        handleGetSelected,
        handleGetOutput,
        handleGetInput,
        handleRunWorkflow,
        handleOpenWorkflow,
        handleRunNode,
        sendResponse,
    ]);

    // Subscribe to MCP request events
    useEffect(() => {
        // Type assertion needed until types are regenerated
        const unsubscribe = onSocketEvent(
            'workflow:mcp:request' as any,
            handleMCPRequest as any
        );
        return unsubscribe;
    }, [handleMCPRequest]);

    // Check pending output requests when nodes change
    useEffect(() => {
        pendingOutputRequestsRef.current.forEach((pending, requestId) => {
            const node = nodes.find(n => n.id === pending.node_id);

            if (!node) {
                // Node was removed
                clearTimeout(pending.timeoutId);
                pendingOutputRequestsRef.current.delete(requestId);
                sendResponse(requestId, null, `Node ${pending.node_id} was removed`);
                return;
            }

            // Check if node now has output
            const output = node.data?.output;
            const status = node.data?.status;

            if (output !== undefined && output !== null) {
                clearTimeout(pending.timeoutId);
                pendingOutputRequestsRef.current.delete(requestId);
                sendResponse(requestId, output);
            } else if (status === 'completed' || status === 'error') {
                // Node finished but with no output or error
                clearTimeout(pending.timeoutId);
                pendingOutputRequestsRef.current.delete(requestId);
                if (status === 'error') {
                    sendResponse(requestId, null, `Node ${pending.node_id} failed with error`);
                } else {
                    sendResponse(requestId, null);
                }
            }
        });
    }, [nodes, sendResponse]);

    // =========================================================================
    // Dual-Delivery Event Listeners
    // Only update_interface still uses this pattern - all other mutations
    // are handled by update_workflow XML tool + useMCPBuilderEvents
    // =========================================================================

    // Handle update_interface dual-delivery - sync interface layout from MCP
    useEffect(() => {
        const unsubscribe = onSocketEvent(
            'mcp:workflow:update_interface:response',
            (response) => {
                if (
                    response.workflow_id !== workflowId ||
                    !response.success ||
                    !isInterfaceGridState(response.interface_state)
                ) return;

                console.log('[WorkflowMCP] Dual-delivery: update_interface', response);

                if (interfaceGridStateRef) {
                    (interfaceGridStateRef as React.MutableRefObject<InterfaceGridState | null>).current = response.interface_state;
                }
                workflowInterfaceRef?.current?.setFullState(response.interface_state);
            }
        );
        return unsubscribe;
    }, [workflowId, interfaceGridStateRef, workflowInterfaceRef]);

    // Cleanup pending requests on unmount
    useEffect(() => {
        return () => {
            pendingOutputRequestsRef.current.forEach(pending => {
                clearTimeout(pending.timeoutId);
            });
            pendingOutputRequestsRef.current.clear();
        };
    }, []);
}
