/**
 * useCanvasWorkflowEdit - Hook for AI-powered workflow editing in canvas view.
 *
 * This hook handles sending edit requests to the backend and processing
 * streaming events to update the canvas nodes/edges in real-time.
 * It's a simplified version of useWorkflowGeneration focused on editing
 * existing workflows in the FlowCanvas.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { useSnapshot } from 'valtio';
import type { Node, Edge } from '@xyflow/react';
import { toast } from 'sonner';
import { socketReceiver } from '~/lib/socket-receiver';
import { sendEventAsync } from '~/lib/socket-sender';
import type { WorkflowBuilderEditRequest } from '~/types/socket-events.generated';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import { activeConversationStore } from '~/lib/activeConversationStore';
import {
    subscribeToBuilderResponse,
    BUILDER_EDIT_TIMEOUT_MS,
} from '~/lib/builderHydration';
import { createStyledEdge } from '~/utils/workflowLayout';
// Node dimensions from the serialized icon singleton (dashboard loader), not the
// registry — this hook is reachable from the always-mounted chat builder, so
// importing the registry here would pull its ~4.7MB component graph eagerly.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { workflowDebugStore } from '~/lib/workflow-debug-store';
import { setNodeEditInfo, updateNodeEditInfo, clearAllNodeEditInfo, getCurrentWorkflowName, type NodeEditInfo } from '~/components/workflow/WorkflowContext';
import type { RecordedEvent } from '~/lib/recordedEvent';
import { trackChatSendStarted } from '~/lib/telemetry-chat';
import type { AiEditInfo } from '~/lib/collaboration';
import { applyNodeUpdate, createWorkflowNode, rawConfigToPayload } from '~/lib/applyNodeUpdate';
import { getBuilderContext } from '~/lib/builder-context';
import { getAppliedTheme } from '~/lib/theme';

/**
 * Strip the post-animation `style.transition` from every node, preserving all
 * other node state. Used as the updater passed to `onNodesChange` when a
 * generation ends — so it maps over the LIVE store rather than a snapshot.
 *
 * This is deliberately a pure `nodes => nodes` transform: the previous version
 * built a new array from the hook's render-lagging `nodesRef` and installed it
 * wholesale, which reverted every store write that didn't come through this
 * hook. Builder credential events arrive via activeGenStore, so `set_credentials`
 * was undone ~400ms after the turn ended and the builder's next whole-blob
 * persist wrote the credential-less graph to the DB (2026-08-02).
 */
export function stripNodeTransitions(nodes: Node[]): Node[] {
    return nodes.map(node => {
        if (node.style?.transition) {
            const { transition, ...restStyle } = node.style;
            return { ...node, style: restStyle };
        }
        return node;
    });
}

export type CanvasEditPhase = 'idle' | 'editing' | 'complete' | 'error';

export interface CanvasEditState {
    /** Current editing phase */
    phase: CanvasEditPhase;
    /** Whether an edit is in progress */
    isEditing: boolean;
    /** Error message if editing failed */
    error: string | null;
    /** IDs of nodes being modified */
    affectedNodeIds: Set<string>;
}

export interface CanvasEditSnapshot {
    nodes: Node[];
    edges: Edge[];
    timestamp: number;
}

export interface UseCanvasWorkflowEditOptions {
    /** Workflow ID for tracking */
    workflowId?: string;
    /** Current nodes in the canvas */
    currentNodes: Node[];
    /** Current edges in the canvas */
    currentEdges: Edge[];
    /** Callback when nodes need to be updated */
    onNodesChange: (updater: (nodes: Node[]) => Node[]) => void;
    /** Callback when edges need to be updated */
    onEdgesChange: (updater: (edges: Edge[]) => Edge[]) => void;
    /** Callback when editing completes */
    onEditComplete?: () => void;
    /** Callback when an error occurs */
    onError?: (error: string) => void;
    /** Broadcast AI editing start to collaborators */
    broadcastAiEditingStart?: (nodeIds: string[]) => void;
    /** Broadcast AI editing update to collaborators */
    broadcastAiEditingUpdate?: (nodeId: string, info: AiEditInfo) => void;
    /** Broadcast AI editing end to collaborators */
    broadcastAiEditingEnd?: () => void;
    /** Broadcast node add to collaborators */
    broadcastNodeAdd?: (node: Node) => void;
    /** Broadcast node remove to collaborators */
    broadcastNodeRemove?: (nodeId: string) => void;
    /** Broadcast edge add to collaborators */
    broadcastEdgeAdd?: (edge: Edge) => void;
    /** Broadcast edge remove to collaborators */
    broadcastEdgeRemove?: (edgeId: string) => void;
    /** Broadcast node position update to collaborators (used after layout) */
    broadcastNodeDrag?: (nodeId: string, position: { x: number; y: number }) => void;
}

export type AutofillMode = 'full' | 'operation' | 'fields' | 'single_field';

export interface AutofillStatus {
    /** Which node is being autofilled (if any) */
    nodeId: string | null;
    /** Which mode the autofill is running in */
    mode: AutofillMode | null;
    /** The specific field being filled (only set when mode === 'single_field') */
    targetField: string | null;
}

export interface UseCanvasWorkflowEditReturn {
    /** Current editing state */
    state: CanvasEditState;
    /** Active autofill (lets the UI spin only the targeted control) */
    autofillStatus: AutofillStatus;
    /** Start an edit with a prompt */
    startEdit: (prompt: string, selectedNodeId?: string | null, conversationId?: string, n8nWorkflow?: Record<string, unknown> | null, scope?: { type: 'node'; nodeId: string }) => Promise<void>;
    /** Reattach to a paused builder run so its streaming events land here when the user submits the ask response. */
    resumeFromPending: (generationId: string, pendingAsk: { ask_id: string; inputs: InputRequest[]; title?: string }) => void;
    /** Run AI autofill on a single node (operation, all fields, or one field). */
    startAutofill: (nodeId: string, mode: AutofillMode, targetField?: string) => Promise<void>;
    /** Cancel an ongoing edit (if possible) */
    cancelEdit: () => void;
    /** Whether undo is available */
    canGoBack: boolean;
    /** Whether redo is available */
    canGoForward: boolean;
    /** Undo last edit */
    goBack: () => void;
    /** Redo last undone edit */
    goForward: () => void;
}

/**
 * Hook for AI-powered workflow editing in the canvas view.
 */
export function useCanvasWorkflowEdit({
    workflowId,
    currentNodes,
    currentEdges,
    onNodesChange,
    onEdgesChange,
    onEditComplete,
    onError,
    broadcastAiEditingStart,
    broadcastAiEditingUpdate,
    broadcastAiEditingEnd,
    broadcastNodeAdd,
    broadcastNodeRemove,
    broadcastEdgeAdd,
    broadcastEdgeRemove,
    broadcastNodeDrag,
}: UseCanvasWorkflowEditOptions): UseCanvasWorkflowEditReturn {
    // Use socketReceiver directly to get socket instance

    // Editing state
    const [phase, setPhase] = useState<CanvasEditPhase>('idle');
    const [error, setError] = useState<string | null>(null);
    const [affectedNodeIds, setAffectedNodeIds] = useState<Set<string>>(new Set());
    const [autofillStatus, setAutofillStatus] = useState<AutofillStatus>({ nodeId: null, mode: null, targetField: null });

    // History for undo/redo
    const [historyPast, setHistoryPast] = useState<CanvasEditSnapshot[]>([]);
    const [historyFuture, setHistoryFuture] = useState<CanvasEditSnapshot[]>([]);

    // Refs for current state (needed in socket handlers)
    const nodesRef = useRef<Node[]>([]);
    const edgesRef = useRef<Edge[]>([]);
    const generationIdRef = useRef<string | null>(null);
    const responseHandlerRef = useRef<((response: any) => void) | null>(null);
    // The conversation the sidebar chat is currently showing for THIS workflow,
    // published by useSidebarConversation (the single source of truth). We only
    // auto-resume asks that belong to this conversation, so a pending ask from
    // Conv A doesn't pop a drawer while the user is in Conv B. checkPendingAsk
    // must reconcile against this exact id — it used to read a separate, stale
    // global slot, which made it clear the freshly-opened ask drawer on restore
    // (visible flash). See activeConversationStore.
    const activeConversationId = useSnapshot(activeConversationStore).byWorkflow[workflowId ?? ''] ?? '';

    // Event recording for replay/debug
    const [recordedEvents, setRecordedEvents] = useState<RecordedEvent[]>([]);
    const [isRecording, setIsRecording] = useState(false);
    const recordingStartRef = useRef<number | null>(null);

    const cleanupSocketListener = useCallback(() => {
        if (responseHandlerRef.current) {
            (responseHandlerRef.current as any)();  // Call the unsubscribe function
            responseHandlerRef.current = null;
        }
    }, []);

    // Keep refs in sync with current nodes/edges from props
    useEffect(() => {
        nodesRef.current = currentNodes;
        edgesRef.current = currentEdges;
    }, [currentNodes, currentEdges]);

    // Keep debug store nodes in sync during editing
    useEffect(() => {
        if (phase === 'editing' || phase === 'complete') {
            workflowDebugStore.update({
                nodes: currentNodes.map((n, i) => ({
                    id: n.id,
                    type: n.type || 'agent',
                    label: String(n.data?.label ?? ''),
                    content: String(n.data?.label ?? ''),
                    level: 0,
                    index: i,
                    parentIds: [],
                    status: 'complete' as const,
                })),
            });
        }
    }, [currentNodes, phase]);

    // Legacy sync function (kept for compatibility)
    const syncRefs = useCallback((nodes: Node[], edges: Edge[]) => {
        nodesRef.current = nodes;
        edgesRef.current = edges;
    }, []);

    // Create snapshot of current state
    const createSnapshot = useCallback((): CanvasEditSnapshot => ({
        nodes: [...nodesRef.current],
        edges: [...edgesRef.current],
        timestamp: Date.now(),
    }), []);

    // Save current state to history before making changes
    const saveToHistory = useCallback(() => {
        const snapshot = createSnapshot();
        if (snapshot.nodes.length > 0 || snapshot.edges.length > 0) {
            setHistoryPast(prev => [...prev, snapshot]);
            setHistoryFuture([]); // Clear redo stack on new edit
        }
    }, [createSnapshot]);

    // Restore from snapshot
    const restoreSnapshot = useCallback((snapshot: CanvasEditSnapshot) => {
        onNodesChange(() => snapshot.nodes);
        onEdgesChange(() => snapshot.edges);
        syncRefs(snapshot.nodes, snapshot.edges);
    }, [onNodesChange, onEdgesChange, syncRefs]);

    // Go back in history (undo)
    const goBack = useCallback(() => {
        if (historyPast.length === 0 || phase === 'editing') return;

        const currentSnapshot = createSnapshot();
        const previousSnapshot = historyPast[historyPast.length - 1];

        setHistoryPast(prev => prev.slice(0, -1));
        setHistoryFuture(prev => [currentSnapshot, ...prev]);
        restoreSnapshot(previousSnapshot);
    }, [historyPast, phase, createSnapshot, restoreSnapshot]);

    // Go forward in history (redo)
    const goForward = useCallback(() => {
        if (historyFuture.length === 0 || phase === 'editing') return;

        const currentSnapshot = createSnapshot();
        const nextSnapshot = historyFuture[0];

        setHistoryFuture(prev => prev.slice(1));
        setHistoryPast(prev => [...prev, currentSnapshot]);
        restoreSnapshot(nextSnapshot);
    }, [historyFuture, phase, createSnapshot, restoreSnapshot]);

    // Handle streaming events from backend
    const handleEditEvent = useCallback((eventData: any) => {
        const eventType = eventData.event_type;

        // Debug: log all received events
        console.log('[useCanvasWorkflowEdit] Received event:', eventType, eventData);

        switch (eventType) {
            case 'node_added': {
                const nodeData = eventData.node;
                if (nodeData) {
                    if (!nodeData.id) {
                        // BE emitted a node_added without an id. Bail —
                        // adding an undefined-id node corrupts the graph
                        // (filters that key on `n.id.startsWith(...)`
                        // throw, and the node has no addressable
                        // identity for subsequent updates).
                        console.error('[useCanvasWorkflowEdit] node_added missing id:', nodeData);
                        break;
                    }
                    // Use position from node data if provided (e.g., from n8n conversion)
                    // Otherwise use temporary position that will be laid out
                    const hasPosition = nodeData.position && typeof nodeData.position.x === 'number';
                    const position = hasPosition
                        ? { x: nodeData.position.x, y: nodeData.position.y }
                        : { x: 0, y: 0 };

                    const isStickyNote = nodeData.type === 'stickyNote';

                    // Create new node using createWorkflowNode for consistent data model
                    const newNode: Node = createWorkflowNode(
                        nodeData.id,
                        nodeData.type,
                        position,
                        {
                            ...(nodeData.config || {}),
                            label: nodeData.label,
                            goal: nodeData.goal,
                            operation: nodeData.operation,
                            ...(nodeData.content !== undefined ? { content: nodeData.content } : {}),
                            ...(nodeData.color !== undefined ? { color: nodeData.color } : {}),
                        },
                        { _hasPresetPosition: hasPosition },
                    );

                    // Resizable nodes need explicit dimensions
                    if (isStickyNote && (nodeData.width || nodeData.height)) {
                        newNode.style = {
                            width: nodeData.width || 200,
                            height: nodeData.height || 200,
                        };
                        newNode.width = nodeData.width || 200;
                        newNode.height = nodeData.height || 200;
                    } else if (nodeData.type?.startsWith('interface-')) {
                        const nodeDef = getNodeIconMeta(nodeData.type);
                        const w = nodeData.width || nodeDef?.dimensions.width || 800;
                        const h = nodeData.height || nodeDef?.dimensions.height || 550;
                        newNode.style = { width: w, height: h };
                    }

                    // IMPORTANT: Update nodesRef SYNCHRONOUSLY to prevent race conditions
                    // when multiple node_added events arrive in quick succession.
                    // Each event must see the nodes added by previous events.
                    const existingNodes = nodesRef.current;

                    // Skip if node already exists (duplicate event)
                    if (existingNodes.some(n => n.id === newNode.id)) {
                        console.log(`[useCanvasWorkflowEdit] Skipping duplicate node: ${newNode.id}`);
                        break;
                    }

                    // Add transition style and new node
                    const updatedNodes = [...existingNodes, newNode].map(node => ({
                        ...node,
                        style: {
                            ...node.style,
                            transition: 'transform 0.3s ease-out',
                        },
                    }));
                    // Deduplicate nodes to prevent React key errors
                    const uniqueNodes = updatedNodes.filter((node, index, self) =>
                        index === self.findIndex(n => n.id === node.id)
                    );

                    // Update ref synchronously BEFORE any async operations
                    nodesRef.current = uniqueNodes;
                    onNodesChange(() => uniqueNodes);

                    // Layout is computed on the backend and arrives as a
                    // single `layout_applied` event after this batch of
                    // node/edge events — see the handler below. We only
                    // broadcast the added node here so collaborators see it
                    // appear at the backend-provided position.
                    broadcastNodeAdd?.(newNode);

                    setAffectedNodeIds(prev => new Set([...prev, nodeData.id]));
                    // Update node edit info for canvas animation
                    const addedEditInfo: AiEditInfo = {
                        status: 'processing',
                        action: 'added',
                        operation: nodeData.operation,
                        config: nodeData.config,
                    };
                    setNodeEditInfo(nodeData.id, addedEditInfo);
                    broadcastAiEditingUpdate?.(nodeData.id, addedEditInfo);
                    // Dispatch event for NoClick to show visual message
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'node_added', nodeType: nodeData.type, label: nodeData.label, nodeId: nodeData.id }
                    }));
                }
                break;
            }

            case 'node_removed': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    // Get node info before removing for the message
                    const removedNode = nodesRef.current.find(n => n.id === nodeId);
                    const nodeLabel = removedNode?.data?.label || nodeId;
                    const nodeType = removedNode?.type;
                    // Update node edit info for canvas animation (show removal state briefly)
                    const removedEditInfo: AiEditInfo = {
                        status: 'complete',
                        action: 'removed',
                    };
                    setNodeEditInfo(nodeId, removedEditInfo);
                    broadcastAiEditingUpdate?.(nodeId, removedEditInfo);
                    onNodesChange(prev => {
                        const updated = prev.filter(n => n.id !== nodeId);
                        nodesRef.current = updated;
                        return updated;
                    });
                    // Broadcast node removal to collaborators
                    broadcastNodeRemove?.(nodeId);
                    // Also remove connected edges
                    onEdgesChange(prev => {
                        const updated = prev.filter(e => e.source !== nodeId && e.target !== nodeId);
                        edgesRef.current = updated;
                        return updated;
                    });

                    // Backend emits `layout_applied` for this mutation batch;
                    // frontend doesn't run autolayout locally.

                    // Dispatch event for NoClick to show visual message
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'node_removed', nodeType, label: nodeLabel, nodeId }
                    }));
                }
                break;
            }

            case 'edge_added': {
                const edgeData = eventData.edge;
                if (edgeData) {
                    // Get node info for the message
                    const sourceNode = nodesRef.current.find(n => n.id === edgeData.sourceId);
                    const targetNode = nodesRef.current.find(n => n.id === edgeData.targetId);

                    const sourceLabel = sourceNode?.data?.label || edgeData.sourceId;
                    const targetLabel = targetNode?.data?.label || edgeData.targetId;
                    // Node type can be in node.type or node.data.nodeType or node.data.type depending on how node was created
                    const sourceType = sourceNode?.type || sourceNode?.data?.nodeType || sourceNode?.data?.type;
                    const targetType = targetNode?.type || targetNode?.data?.nodeType || targetNode?.data?.type;

                    // Skip if edge already exists (duplicate event)
                    if (edgesRef.current.some(e => e.id === edgeData.id)) {
                        console.log(`[useCanvasWorkflowEdit] Skipping duplicate edge: ${edgeData.id}`);
                        break;
                    }

                    // Use shared utility for consistent edge styling
                    const newEdge = createStyledEdge({
                        id: edgeData.id,
                        source: edgeData.sourceId,
                        target: edgeData.targetId,
                        sourceHandle: edgeData.sourceHandle,
                        targetHandle: edgeData.targetHandle,
                    });

                    // Add edge SYNCHRONOUSLY to prevent race conditions
                    const updatedEdges = [...edgesRef.current, newEdge];
                    // Deduplicate edges to prevent React key errors
                    const uniqueEdges = updatedEdges.filter((edge, index, self) =>
                        index === self.findIndex(e => e.id === edge.id)
                    );
                    edgesRef.current = uniqueEdges;
                    onEdgesChange(() => uniqueEdges);

                    // Broadcast edge add to collaborators. Backend emits a
                    // `layout_applied` event after this batch that will
                    // reposition any nodes shifted by the edge; no frontend
                    // autolayout runs here.
                    broadcastEdgeAdd?.(newEdge);

                    // Dispatch event for NoClick to show visual message
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'edge_added',
                            edgeId: edgeData.id,
                            sourceNodeId: edgeData.sourceId,
                            sourceNodeLabel: sourceLabel,
                            sourceNodeType: sourceType,
                            targetNodeId: edgeData.targetId,
                            targetNodeLabel: targetLabel,
                            targetNodeType: targetType,
                        }
                    }));
                }
                break;
            }

            case 'edge_removed': {
                const edgeId = eventData.edgeId;
                if (edgeId) {
                    // Get edge info before removing for the message
                    const removedEdge = edgesRef.current.find(e => e.id === edgeId);
                    const sourceNode = removedEdge ? nodesRef.current.find(n => n.id === removedEdge.source) : null;
                    const targetNode = removedEdge ? nodesRef.current.find(n => n.id === removedEdge.target) : null;
                    const sourceLabel = sourceNode?.data?.label || removedEdge?.source || 'Unknown';
                    const targetLabel = targetNode?.data?.label || removedEdge?.target || 'Unknown';
                    // Node type can be in node.type or node.data.nodeType depending on how node was created
                    const sourceType = sourceNode?.type || sourceNode?.data?.nodeType;
                    const targetType = targetNode?.type || targetNode?.data?.nodeType;

                    onEdgesChange(prev => {
                        const updated = prev.filter(e => e.id !== edgeId);
                        edgesRef.current = updated;
                        return updated;
                    });

                    // Broadcast edge removal to collaborators. Backend emits
                    // `layout_applied` for this mutation batch; no frontend
                    // autolayout runs here.
                    broadcastEdgeRemove?.(edgeId);

                    // Dispatch event for NoClick to show visual message
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'edge_removed',
                            edgeId,
                            sourceNodeId: removedEdge?.source,
                            sourceNodeLabel: sourceLabel,
                            sourceNodeType: sourceType,
                            targetNodeId: removedEdge?.target,
                            targetNodeLabel: targetLabel,
                            targetNodeType: targetType,
                        }
                    }));
                }
                break;
            }

            case 'layout_applied': {
                // Backend computed the full graph layout after a batch of
                // mutations. Apply positions (and sticky dimensions) with a
                // transform transition so moves animate smoothly. Matches
                // useMCPBuilderEvents's handling of the same event.
                const positions = eventData.positions as Record<string, { x: number; y: number }> | undefined;
                const stickyUpdates = eventData.sticky_updates as Record<string, { width: number; height: number }> | undefined;
                if (!positions) break;

                onNodesChange(prev => {
                    const next = prev.map(n => {
                        const pos = positions[n.id];
                        const sticky = stickyUpdates?.[n.id];
                        if (!pos && !sticky) return n;
                        const updated: Node = {
                            ...n,
                            ...(pos ? { position: pos } : {}),
                            style: { ...n.style, transition: 'transform 0.5s ease-out' },
                        };
                        if (sticky) {
                            updated.style = { ...updated.style, width: sticky.width, height: sticky.height };
                            updated.width = sticky.width;
                            updated.height = sticky.height;
                        }
                        return updated;
                    });
                    nodesRef.current = next;
                    return next;
                });
                // Broadcast post-layout positions so collaborators see the
                // same final placement.
                Object.entries(positions).forEach(([nodeId, pos]) => {
                    broadcastNodeDrag?.(nodeId, pos);
                });
                break;
            }

            case 'node_updated': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    // Get node info for the message
                    const updatedNode = nodesRef.current.find(n => n.id === nodeId);
                    const nodeLabel = updatedNode?.data?.label || nodeId;
                    const nodeType = updatedNode?.type;

                    console.log('[useCanvasWorkflowEdit] node_updated event:', {
                        nodeId,
                        operation: eventData.operation,
                        config: eventData.config,
                        goal: eventData.goal,
                        userFields: eventData.userFields,
                    });

                    // node_updated arrives in two shapes: the agentic builder's
                    // _build_node_update_data (metadata already split to top-level
                    // event fields) and the node drafting builder's raw event
                    // (credentialIds mixed into config). rawConfigToPayload routes
                    // the config blob so credentialIds lands at data.credentialIds
                    // — where NodeCredentials and execution-config serialization
                    // read it — instead of being buried at data.config.credentialIds.
                    const cfgPayload = rawConfigToPayload(eventData.config || {});
                    onNodesChange(prev => {
                        const updated = prev.map(n => {
                            if (n.id !== nodeId) return n;
                            return applyNodeUpdate(n, {
                                config: cfgPayload.config,
                                operation: eventData.operation,
                                operationReason: eventData.operationReason,
                                userFields: eventData.userFields,
                                goal: eventData.goal,
                                credentialIds: eventData.credentialIds ?? cfgPayload.credentialIds,
                            });
                        });
                        nodesRef.current = updated;
                        return updated;
                    });
                    setAffectedNodeIds(prev => new Set([...prev, nodeId]));
                    // Update node edit info for canvas animation (mark as complete with final data)
                    const updatedEditInfo: AiEditInfo = {
                        status: 'complete',
                        action: 'updated',
                        operation: eventData.operation,
                        config: eventData.config,
                    };
                    updateNodeEditInfo(nodeId, updatedEditInfo);
                    broadcastAiEditingUpdate?.(nodeId, updatedEditInfo);
                    // Dispatch event for NoClick to show visual message (include operation/config for expanded view)
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_updated',
                            nodeType,
                            label: nodeLabel,
                            nodeId,
                            operation: eventData.operation,
                            config: eventData.config,
                        }
                    }));
                }
                break;
            }

            case 'node_processing_start': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    setAffectedNodeIds(prev => new Set([...prev, nodeId]));
                    // Get node info for the message
                    const processingNode = nodesRef.current.find(n => n.id === nodeId);
                    const nodeLabel = processingNode?.data?.label || nodeId;
                    const nodeType = processingNode?.type;
                    // Initialize node edit info for canvas animation
                    const processingEditInfo: AiEditInfo = {
                        status: 'processing',
                        action: 'updated',
                    };
                    setNodeEditInfo(nodeId, processingEditInfo);
                    broadcastAiEditingUpdate?.(nodeId, processingEditInfo);
                    // Dispatch event for NoClick to show visual message
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_processing',
                            nodeType,
                            label: nodeLabel,
                            nodeId,
                        }
                    }));
                }
                break;
            }

            case 'node_operation_selected': {
                // Intermediate event from node drafter - operation was selected
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    const node = nodesRef.current.find(n => n.id === nodeId);
                    const nodeLabel = node?.data?.label || nodeId;
                    const nodeType = node?.type;
                    // Update node edit info with operation
                    const operationSelectedInfo: Partial<AiEditInfo> = {
                        operation: eventData.operation,
                    };
                    updateNodeEditInfo(nodeId, operationSelectedInfo as NodeEditInfo);
                    // Broadcast with status to ensure valid AiEditInfo
                    broadcastAiEditingUpdate?.(nodeId, {
                        status: 'processing',
                        action: 'updated',
                        operation: eventData.operation,
                    });
                    // Dispatch event with operation info
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_processing',
                            nodeType,
                            label: nodeLabel,
                            nodeId,
                            operation: eventData.operation,
                        }
                    }));
                }
                break;
            }

            case 'node_config_filling': {
                // Intermediate event from node drafter - config field being filled
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    const node = nodesRef.current.find(n => n.id === nodeId);
                    const nodeLabel = node?.data?.label || nodeId;
                    const nodeType = node?.type;
                    // Update node edit info with config field
                    const configFillingInfo: Partial<AiEditInfo> = {
                        config: { [eventData.field]: eventData.value },
                    };
                    updateNodeEditInfo(nodeId, configFillingInfo as NodeEditInfo);
                    // Broadcast with status to ensure valid AiEditInfo
                    broadcastAiEditingUpdate?.(nodeId, {
                        status: 'processing',
                        action: 'updated',
                        config: { [eventData.field]: eventData.value },
                    });
                    // Dispatch event with partial config
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_processing',
                            nodeType,
                            label: nodeLabel,
                            nodeId,
                            config: { [eventData.field]: eventData.value },
                        }
                    }));
                }
                break;
            }

            case 'input_request': {
                // Builder is pausing for user input — show the input drawer.
                // Scope the drawer to this workflow so the bridge can
                // self-close when the user navigates away.
                document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
                    detail: {
                        inputs: eventData.inputs,
                        title: 'Input needed',
                        conversationId: activeConversationId,
                        generationId: generationIdRef.current,
                        askId: eventData.ask_id,
                        workflowId,
                    },
                }));
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'status', status: 'Waiting for your input' }
                }));
                break;
            }

            case 'text_chunk': {
                // Forward brain conversational text to NoClick sidebar (no canvas changes needed)
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'text_chunk', text: eventData.text }
                }));
                break;
            }

            case 'status': {
                // Forward status updates to NoClick for step tracking shimmer
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'status', status: eventData.status }
                }));
                break;
            }

            case 'open_workflow': {
                // Backend requested to open a different workflow
                const targetWorkflowId = eventData.workflow_id;
                if (targetWorkflowId) {
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'open_workflow', workflowId: targetWorkflowId }
                    }));
                    // Navigate to the workflow
                    window.dispatchEvent(new CustomEvent('noclick:navigate-to-node', {
                        detail: { workflowId: targetWorkflowId, nodeId: '' },
                    }));
                }
                break;
            }

            case 'run_test': {
                // Builder fired <run_test/>: FlowCanvas switches to the
                // interface tab and arms the Test Run screen's auto-start.
                document.dispatchEvent(new CustomEvent('noclick:run-test', {
                    detail: {
                        workflowId: eventData.workflow_id || workflowId,
                        trigger: eventData.trigger,
                        run: eventData.run,
                    },
                }));
                break;
            }

            case 'settings_updated': {
                // Builder wrote workflows.settings (variables / test runs) —
                // an open canvas must re-read or its next debounced settings
                // write clobbers what was just authored.
                document.dispatchEvent(new CustomEvent('noclick:workflow-settings-updated', {
                    detail: { workflowId: eventData.workflow_id || workflowId },
                }));
                break;
            }

            case 'generation_complete': {
                setPhase('complete');
                cleanupSocketListener();
                // Broadcast AI editing end to collaborators
                broadcastAiEditingEnd?.();

                // Layout is already applied incrementally after each node/edge change
                // No need for final layout snap

                // Clean up transition styles after animation completes (300ms transition + 100ms buffer)
                // This prevents undo from animating nodes back slowly.
                //
                // Maps over `prev` (the LIVE store), never over nodesRef: this
                // is a cosmetic style strip, and a wholesale replace from the
                // render-lagging ref silently reverted every store write that
                // didn't come through this hook — builder credential events
                // land via activeGenStore, so a stale ref can undo
                // `<set_credentials>` and the next whole-blob persist can write
                // a credential-less graph to the database.
                setTimeout(() => onNodesChange(stripNodeTransitions), 400);

                // Dispatch completion event for NoClick. Forward the
                // `cancelled` flag so the chat bubble can render a "Stopped"
                // pill instead of the success summary when the user clicked
                // the stop button mid-stream.
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'complete', cancelled: !!(eventData as any).cancelled }
                }));
                setTimeout(() => {
                    setPhase('idle');
                    setAffectedNodeIds(new Set());
                    // Clear all node edit info after animation completes
                    clearAllNodeEditInfo();
                }, 1000);
                onEditComplete?.();
                break;
            }

            case 'error': {
                const errorMsg = eventData.error || 'Unknown error';
                setError(errorMsg);
                setPhase('error');
                cleanupSocketListener();
                // Broadcast AI editing end to collaborators
                broadcastAiEditingEnd?.();
                // Clean up transition styles — over `prev`, not nodesRef (see
                // the generation_complete handler: a wholesale replace here
                // reverts store writes made outside this hook).
                onNodesChange(stripNodeTransitions);
                // Clear all node edit info on error
                clearAllNodeEditInfo();
                // Dispatch error event for NoClick
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'error', error: errorMsg }
                }));
                onError?.(errorMsg);
                break;
            }
        }
    }, [onNodesChange, onEdgesChange, onEditComplete, onError, cleanupSocketListener, broadcastAiEditingUpdate, broadcastAiEditingEnd, broadcastNodeAdd, broadcastNodeRemove, broadcastEdgeAdd, broadcastEdgeRemove, broadcastNodeDrag]);

    // Start an edit
    const startEdit = useCallback(async (prompt: string, selectedNodeId?: string | null, conversationId?: string, n8nWorkflow?: Record<string, unknown> | null, scope?: { type: 'node'; nodeId: string }) => {
        const socket = socketReceiver.getSocket('API');
        if (!socket) {
            setError('Socket not connected');
            setPhase('error');
            return;
        }

        // Save current state to history before editing
        saveToHistory();

        // Clear previous state
        setPhase('editing');
        setError(null);
        setAffectedNodeIds(new Set());

        // Broadcast AI editing start to collaborators (empty nodeIds initially, will be updated as nodes are affected)
        broadcastAiEditingStart?.([]);

        // Generate a unique ID for this edit session.
        const generationId = `edit_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        generationIdRef.current = generationId;

        // Dispatch event for NoClick to show loading state
        document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
            detail: { type: 'started', prompt, generationId }
        }));

        // Start recording events - include initial state for edit replay
        const initialStateEvent: RecordedEvent = {
            timestamp: 0,
            eventType: 'edit_initial_state',
            eventData: {
                nodes: nodesRef.current.map((n, i) => ({
                    id: n.id,
                    type: n.type || 'agent',
                    label: String(n.data?.label ?? ''),
                    description: n.data?.goal || '',
                    content: String(n.data?.label ?? ''),
                    parentIds: [],
                    level: 0,
                    index: i,
                    status: 'complete' as const,
                    operation: n.data?.operation,
                    config: n.data?.config,
                })),
                edges: edgesRef.current.map(e => ({
                    id: e.id,
                    sourceId: e.source,
                    targetId: e.target,
                    sourceHandle: e.sourceHandle,
                    targetHandle: e.targetHandle,
                    status: 'complete' as const,
                })),
            },
        };
        setRecordedEvents([initialStateEvent]);
        recordingStartRef.current = Date.now();
        setIsRecording(true);
        console.log('[useCanvasWorkflowEdit] Started recording with initial state');

        // Update debug store so workflow diagnostics can show LLM calls for this edit
        workflowDebugStore.update({
            generationId,
            nodes: nodesRef.current.map((n, i) => ({
                id: n.id,
                type: n.type || 'agent',
                label: String(n.data?.label ?? ''),
                content: String(n.data?.label ?? ''),
                level: 0,
                index: i,
                parentIds: [],
                status: 'complete' as const,
            })),
            selectedNodeId: selectedNodeId || null,
            recordedEvents: [initialStateEvent],
            isRecording: true,
        });

        // Convert current nodes/edges to the format expected by the backend
        const currentGraph = {
            workflow_id: workflowId,
            nodes: nodesRef.current.map(n => ({
                id: n.id,
                type: n.type,
                label: String(n.data?.label ?? ''),
                goal: n.data?.goal || '',
                operation: n.data?.operation,
                config: n.data?.config,
                error: n.data?.error || (n.data?.output as any)?.error || null,
                position: n.position,
                ...(n.width != null ? { width: n.width } : {}),
                ...(n.height != null ? { height: n.height } : {}),
            })),
            edges: edgesRef.current.map(e => ({
                id: e.id,
                sourceId: e.source,
                targetId: e.target,
                ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
                // targetHandle="bottom" is the load-bearing tool-provider signal the
                // backend reads (autolayout + provider detection) — it must survive the
                // round-trip or providers get laid out as upstream dataflow.
                ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
            })),
        };

        // Cleanup any previous listener before setting up new one
        cleanupSocketListener();

        // Set up response listener for streaming events. The shared primitive
        // owns the request_id filter, top-level error path, and data peeling;
        // we just need to dispatch + record per event_type.
        const unsubscribe = subscribeToBuilderResponse(generationId, {
            onError: (err) => handleEditEvent({ event_type: 'error', error: err }),
            onEvent: (eventData) => {
                const eventType = eventData.event_type;
                console.log('[useCanvasWorkflowEdit] Received event:', eventType, eventData);
                if (recordingStartRef.current !== null) {
                    const timestamp = Date.now() - recordingStartRef.current;
                    setRecordedEvents(prev => {
                        const newEvents = [...prev, { timestamp, eventType, eventData }];
                        workflowDebugStore.update({ recordedEvents: newEvents });
                        return newEvents;
                    });
                }
                handleEditEvent(eventData);
                if (eventType === 'generation_complete') {
                    setIsRecording(false);
                    workflowDebugStore.update({ isRecording: false });
                }
            },
        });
        responseHandlerRef.current = unsubscribe as any;

        try {
            // Measure the ReactFlow canvas in logical coords so the backend can
            // shape the initial grid layout of unconnected nodes to the actual
            // visible area (sidebar width, screen size, zoom all taken into account).
            const rfEl = document.querySelector('.react-flow') as HTMLElement | null;
            const rfRect = rfEl?.getBoundingClientRect();
            const vpTransform = (document.querySelector('.react-flow__viewport') as HTMLElement | null)
                ?.getAttribute('style')?.match(/scale\(([\d.]+)\)/);
            const zoom = vpTransform ? Number(vpTransform[1]) : 1;
            const viewportWidth = rfRect && zoom ? rfRect.width / zoom : undefined;
            const viewportHeight = rfRect && zoom ? rfRect.height / zoom : undefined;

            // Pre-generate the request_id so we can stamp it on the
            // telemetry "send started" event before the wire send. The same
            // id flows through every active_gen:* frame back from the
            // backend, giving us exact end-to-end latency correlation.
            const requestId = crypto.randomUUID();
            // Send edit request
            const request: Partial<WorkflowBuilderEditRequest> = {
                event_name: 'workflow:builder:edit',
                request_id: requestId,
                current_graph: currentGraph,
                edit_prompt: prompt,
                selected_node_id: selectedNodeId || undefined,
                generation_id: generationId,
                conversation_id: conversationId || undefined,
                user_context: { has_workflow: true, inner_tab: getBuilderContext().innerTab || 'canvas', workflow_id: workflowId, workflow_name: getCurrentWorkflowName(), theme: getAppliedTheme() },
                viewport_width: viewportWidth,
                viewport_height: viewportHeight,
                ...(n8nWorkflow ? { n8n_workflow: n8nWorkflow } : {}),
                ...(scope?.type === 'node' ? { edit_scope: 'node' as const } : {}),
            };

            trackChatSendStarted({
                requestId,
                model: null,
                contentLength: prompt.length,
                imageCount: 0,
                hasWorkflowContext: true,
                conversationId: conversationId || null,
            });
            console.log('[useCanvasWorkflowEdit] Sending edit request:', { generationId, prompt });
            await sendEventAsync(request as any, undefined, BUILDER_EDIT_TIMEOUT_MS, requestId);
        } catch (err) {
            console.error('[useCanvasWorkflowEdit] Error starting edit:', err);
            const errorMsg = err instanceof Error ? err.message : 'Failed to start edit';
            setError(errorMsg);
            setPhase('error');
            setIsRecording(false);
            workflowDebugStore.update({ isRecording: false });
            cleanupSocketListener();
            // Notify NoClick so the chat UI exits streaming state
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: errorMsg }
            }));
        }
    }, [saveToHistory, handleEditEvent, cleanupSocketListener]);

    // Re-attach to a paused conversation. The user has clicked through to
    // a workflow whose latest conversation has pending_ask on the trailing
    // assistant. Mint a fresh generation_id, install the streaming event
    // subscription so when the user submits the drawer, the backend-side
    // resume streams node_added / generation_complete back here. Also
    // re-open the BuilderInputDrawer with the persisted ask.
    //
    // The new gen_id is sent along on input_response so the BE tags its
    // events with it, routing them to the listener we just installed.
    const resumeFromPending = useCallback((
        conversationId: string,
        pendingAsk: { ask_id: string; inputs: InputRequest[]; title?: string },
    ) => {
        const socket = socketReceiver.getSocket('API');
        if (!socket) {
            setError('Socket not connected');
            setPhase('error');
            return;
        }
        setPhase('editing');
        setError(null);
        setAffectedNodeIds(new Set());
        const generationId = `edit_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        generationIdRef.current = generationId;

        cleanupSocketListener();
        const unsubscribe = subscribeToBuilderResponse(generationId, {
            onError: (err) => handleEditEvent({ event_type: 'error', error: err }),
            onEvent: (eventData) => {
                handleEditEvent(eventData);
                if (eventData.event_type === 'generation_complete') {
                    setIsRecording(false);
                    workflowDebugStore.update({ isRecording: false });
                }
            },
        });
        responseHandlerRef.current = unsubscribe as any;

        // Re-open the input drawer with the persisted ask so the user can answer.
        document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
            detail: {
                inputs: pendingAsk.inputs,
                title: pendingAsk.title || 'Input needed',
                conversationId,
                generationId,
                askId: pendingAsk.ask_id,
                workflowId,
            },
        }));
    }, [cleanupSocketListener, handleEditEvent, workflowId]);

    // Auto-resume on mount / conversation switch: if the active conversation
    // has a builder run paused on <ask/> for this workflow, re-open the
    // drawer + subscribe to streaming. If NO match, clear any stale drawer
    // that may have been left open from a previous conversation. Server-side
    // state (submit/dismiss clears pending_ask) is the authoritative source,
    // so we don't need a client-side seen-set — list_pending reflects reality.
    // Stash resumeFromPending in a ref so the auto-resume effect doesn't have
    // to list it as a dep. resumeFromPending depends on handleEditEvent, which
    // depends on ~12 other callbacks — many of those (broadcasts, onNodesChange)
    // are recreated every render. Including resumeFromPending in the effect's
    // deps caused the effect to re-run on every render → workflow:builder:list_pending
    // fired ~50/sec, hammering the backend with redundant queries.
    const resumeFromPendingRef = useRef(resumeFromPending);
    resumeFromPendingRef.current = resumeFromPending;

    // Latest active conversation, readable inside async callbacks without
    // making them a dependency (which would thrash the list_pending query —
    // see the 50/sec footgun the deps note below guards against).
    const activeConversationIdRef = useRef(activeConversationId);
    activeConversationIdRef.current = activeConversationId;

    // Reconcile the paused-ask drawer with server truth: list this workflow's
    // pending runs and re-open the drawer for the active conversation's ask, or
    // clear a stale one. Bails if the conversation changed while the query was
    // in flight (replaces the old per-effect `cancelled` guard). Shared by the
    // mount effect and the reconnect handler (B9). Deps are [workflowId] only —
    // everything else is read via refs — so the callback identity is stable
    // across renders and doesn't re-fire list_pending ~50/sec.
    const checkPendingAsk = useCallback(async () => {
        const wfId = workflowId;
        const convId = activeConversationIdRef.current;
        if (!wfId || !convId) return;
        try {
            const resp = await sendEventAsync<{ runs: Array<{
                conversation_id: string | null;
                pending_ask: { ask_id: string; inputs: InputRequest[]; title?: string } | null;
            }> }>({
                event_name: 'workflow:builder:list_pending',
                workflow_id: wfId,
            } as any);
            if (activeConversationIdRef.current !== convId) return;
            const match = (resp?.runs || [])
                .filter((r) => r.pending_ask)
                .find((r) => r.conversation_id === convId);
            if (match) {
                resumeFromPendingRef.current(convId, match.pending_ask!);
            } else {
                // No pending ask for this conversation — close any stale drawer
                // left open from a prior conversation.
                document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
            }
        } catch (err) {
            console.warn('[useCanvasWorkflowEdit] auto-resume list_pending failed:', err);
        }
    }, [workflowId]);

    useEffect(() => {
        if (!workflowId || !activeConversationId) return;
        void checkPendingAsk();
    }, [workflowId, activeConversationId, checkPendingAsk]);

    // A socket reconnect mid-run can drop the transient ask/terminal frames
    // (paused gens aren't in the connect snapshot), so re-reconcile from the
    // server on reconnect instead of waiting for a manual refresh (B9).
    useEffect(() => {
        const onReconnect = () => { void checkPendingAsk(); };
        document.addEventListener('noclick:socket:reconnected', onReconnect);
        return () => document.removeEventListener('noclick:socket:reconnected', onReconnect);
    }, [checkPendingAsk]);

    // Restored-conversation asks surfaced by BuilderInputBridge come without a
    // generationId; route them through resumeFromPending (the gen owner) so the
    // resume's stream is subscribed under a freshly-minted gen — otherwise the
    // answer's frames are orphaned and the run looks stuck after submit (B10).
    useEffect(() => {
        const onResumePending = (e: Event) => {
            const detail = (e as CustomEvent).detail || {};
            const ask = detail.pendingAsk;
            if (detail.conversationId && ask?.ask_id && Array.isArray(ask?.inputs)) {
                resumeFromPendingRef.current(detail.conversationId, ask);
            }
        };
        document.addEventListener('noclick:builder:resume-pending', onResumePending);
        return () => document.removeEventListener('noclick:builder:resume-pending', onResumePending);
    }, []);

    // Run AI autofill on a single node. Reuses the same response handler as
    // startEdit so node_processing_start / node_config_filling / node_updated
    // events stream into the canvas exactly like a builder edit.
    const startAutofill = useCallback(async (
        nodeId: string,
        mode: AutofillMode,
        targetField?: string,
    ) => {
        const socket = socketReceiver.getSocket('API');
        if (!socket) {
            setError('Socket not connected');
            setPhase('error');
            return;
        }

        saveToHistory();
        setPhase('editing');
        setError(null);
        setAffectedNodeIds(new Set([nodeId]));
        setAutofillStatus({ nodeId, mode, targetField: targetField ?? null });
        broadcastAiEditingStart?.([nodeId]);

        const generationId = `autofill_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        generationIdRef.current = generationId;

        // Start recording so ncdash sees this autofill alongside regular edits.
        const initialStateEvent: RecordedEvent = {
            timestamp: 0,
            eventType: 'edit_initial_state',
            eventData: {
                nodes: nodesRef.current.map((n, i) => ({
                    id: n.id,
                    type: n.type || 'agent',
                    label: String(n.data?.label ?? ''),
                    description: n.data?.goal || '',
                    content: String(n.data?.label ?? ''),
                    parentIds: [],
                    level: 0,
                    index: i,
                    status: 'complete' as const,
                    operation: n.data?.operation,
                    config: n.data?.config,
                })),
                edges: edgesRef.current.map(e => ({
                    id: e.id,
                    sourceId: e.source,
                    targetId: e.target,
                    sourceHandle: e.sourceHandle,
                    targetHandle: e.targetHandle,
                    status: 'complete' as const,
                })),
                autofill: { nodeId, mode, targetField: targetField ?? null },
            },
        };
        setRecordedEvents([initialStateEvent]);
        recordingStartRef.current = Date.now();
        setIsRecording(true);
        workflowDebugStore.update({
            generationId,
            nodes: nodesRef.current.map((n, i) => ({
                id: n.id,
                type: n.type || 'agent',
                label: String(n.data?.label ?? ''),
                content: String(n.data?.label ?? ''),
                level: 0,
                index: i,
                parentIds: [],
                status: 'complete' as const,
            })),
            selectedNodeId: nodeId,
            recordedEvents: [initialStateEvent],
            isRecording: true,
        });

        const currentGraph = {
            nodes: nodesRef.current.map(n => ({
                id: n.id,
                type: n.type,
                label: String(n.data?.label ?? ''),
                goal: n.data?.goal || '',
                operation: n.data?.operation,
                config: n.data?.config,
                error: n.data?.error || (n.data?.output as any)?.error || null,
                position: n.position,
                ...(n.width != null ? { width: n.width } : {}),
                ...(n.height != null ? { height: n.height } : {}),
            })),
            edges: edgesRef.current.map(e => ({
                id: e.id,
                sourceId: e.source,
                targetId: e.target,
                ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
                // targetHandle="bottom" is the load-bearing tool-provider signal the
                // backend reads (autolayout + provider detection) — it must survive the
                // round-trip or providers get laid out as upstream dataflow.
                ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
            })),
        };

        cleanupSocketListener();
        const unsubscribe = subscribeToBuilderResponse(generationId, {
            onError: (err) => {
                toast.error(err);
                handleEditEvent({ event_type: 'error', error: err });
            },
            onEvent: (eventData) => {
                // Surface in-stream error events as a toast — autofill has no
                // chat bubble to land error text in, so this is the user's
                // only signal that the AI couldn't fill the field.
                if (eventData?.event_type === 'error') {
                    toast.error(eventData.error || 'Autofill failed');
                }
                // Mirror startEdit's recording so ncdash captures the stream.
                if (recordingStartRef.current !== null) {
                    const timestamp = Date.now() - recordingStartRef.current;
                    const eventType = eventData.event_type;
                    setRecordedEvents(prev => {
                        const newEvents = [...prev, { timestamp, eventType, eventData }];
                        workflowDebugStore.update({ recordedEvents: newEvents });
                        return newEvents;
                    });
                    if (eventType === 'generation_complete') {
                        setIsRecording(false);
                        workflowDebugStore.update({ isRecording: false });
                    }
                }
                handleEditEvent(eventData);
            },
        });
        responseHandlerRef.current = unsubscribe as any;

        try {
            const requestId = crypto.randomUUID();
            const request = {
                event_name: 'workflow:builder:autofill' as const,
                request_id: requestId,
                current_graph: currentGraph,
                node_id: nodeId,
                mode,
                target_field: targetField,
                generation_id: generationId,
            };
            await sendEventAsync(request as any, undefined, BUILDER_EDIT_TIMEOUT_MS, requestId);
        } catch (err) {
            console.error('[useCanvasWorkflowEdit] Autofill failed:', err);
            const errorMsg = err instanceof Error ? err.message : 'Autofill failed';
            setError(errorMsg);
            setPhase('error');
            cleanupSocketListener();
        } finally {
            setAutofillStatus({ nodeId: null, mode: null, targetField: null });
        }
    }, [saveToHistory, handleEditEvent, cleanupSocketListener, broadcastAiEditingStart]);

    // Cancel an ongoing edit
    const cancelEdit = useCallback(() => {
        if (phase === 'editing') {
            setPhase('idle');
            setAffectedNodeIds(new Set());
            setIsRecording(false);
            workflowDebugStore.update({ isRecording: false });
            cleanupSocketListener();
            clearAllNodeEditInfo();
            // Could send a cancel event to backend if needed
        }
    }, [phase, cleanupSocketListener]);

    // Self-healing reset: any signal that says "no gen is running
    // anymore" must drop phase to idle and clear the affected-node
    // animation. The canvas's `phase` machine relies on a
    // `generation_complete` frame from the per-gen response stream,
    // but the BE doesn't always emit one — paused-on-ask flows in
    // particular routinely leave the original gen without a
    // session_end. Without that frame, phase stays `editing` and
    // every node sits in the AI-editing glow forever.
    //
    // Signals listened to:
    // - noclick:builder:stop: FlowCanvasEmptyState stop button
    // - noclick:active-gens:pause-all: chat-box stop bridge
    //   (handleWorkflowEditStop dispatches into every duplicate
    //   activeGenStore module instance)
    // - active_gen:terminal: socket event from BE when a gen ends
    //   (the canonical gen-end signal — covers natural completion
    //   AND the BE-side resume completion that the response stream
    //   doesn't always deliver)
    useEffect(() => {
        const reset = () => {
            setPhase('idle');
            setAffectedNodeIds(new Set());
            setIsRecording(false);
            workflowDebugStore.update({ isRecording: false });
            cleanupSocketListener();
            clearAllNodeEditInfo();
        };
        document.addEventListener('noclick:builder:stop', reset);
        document.addEventListener('noclick:active-gens:pause-all', reset);
        const unsubTerminal = socketReceiver.on('active_gen:terminal' as never, reset as never);
        return () => {
            document.removeEventListener('noclick:builder:stop', reset);
            document.removeEventListener('noclick:active-gens:pause-all', reset);
            unsubTerminal();
        };
    }, [cleanupSocketListener]);

    // Computed values
    const canGoBack = historyPast.length > 0 && phase !== 'editing';
    const canGoForward = historyFuture.length > 0 && phase !== 'editing';

    return {
        state: {
            phase,
            isEditing: phase === 'editing',
            error,
            affectedNodeIds,
        },
        autofillStatus,
        startEdit,
        resumeFromPending,
        startAutofill,
        cancelEdit,
        canGoBack,
        canGoForward,
        goBack,
        goForward,
    };
}

export default useCanvasWorkflowEdit;
