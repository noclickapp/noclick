// Handles AI workflow edits when FlowCanvas is not mounted (headless mode).
// Fetches graph from DB, sends edit request to backend, processes streaming events,
// and saves the result back to DB — all while dispatching DOM events so the chat UI updates.

import { socketReceiver } from '~/lib/socket-receiver';
import {
    sendEventAsync,
    WorkflowGetRequest,
    WorkflowUpdateRequest,
} from '~/lib/socket-sender';
import type {
    WorkflowGetResponse,
    WorkflowBuilderEditRequest,
} from '~/types/socket-events.generated';
import { setIsAiEditing } from '~/components/workflow/WorkflowContext';
import { getBuilderContext, updateBuilderContext } from '~/lib/builder-context';
import {
    subscribeToBuilderResponse,
    BUILDER_EDIT_TIMEOUT_MS,
} from '~/lib/builderHydration';
import { trackChatSendStarted } from '~/lib/telemetry-chat';

class HeadlessBuilder {
    private _cleanupListener: (() => void) | null = null;
    private _activeGenerationId: string | null = null;

    // Shadow graph — plain arrays updated as events stream in
    private _nodes: any[] = [];
    private _edges: any[] = [];

    /** "Is a run in flight?" tracked locally — no cross-hook registry needed
     *  now that snapshot-based recovery is gone. The terminal socket event
     *  (or cancel) clears _activeGenerationId. */
    isActive(): boolean {
        return this._activeGenerationId !== null;
    }

    cancel(): void {
        if (!this.isActive()) return;
        this._cleanup();
        document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
            detail: { type: 'error', error: 'Cancelled by user' },
        }));
    }

    /**
     * Start an edit without a workflow open. Sends an empty graph so the brain
     * can use <list_workflows> to find existing ones or build from scratch.
     */
    async startEditWithoutWorkflow(
        prompt: string,
        opts?: { conversationId?: string },
    ): Promise<void> {
        if (this.isActive()) {
            console.warn('[HeadlessBuilder] Edit already in progress');
            return;
        }

        const socket = socketReceiver.getSocket('API');
        if (!socket) {
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: 'Socket not connected' },
            }));
            return;
        }

        setIsAiEditing(true);
        this._nodes = [];
        this._edges = [];

        const generationId = `headless_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        this._activeGenerationId = generationId;

        document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
            detail: { type: 'started', prompt, generationId },
        }));

        // Set up socket response listener (no workflowId — handled via open_workflow events)
        const unsubscribe = subscribeToBuilderResponse(generationId, {
            onEvent: (eventData) => this._handleEvent(eventData, '', generationId),
        });
        this._cleanupListener = unsubscribe;

        const ctx = getBuilderContext();
        try {
            const requestId = crypto.randomUUID();
            const request: Partial<WorkflowBuilderEditRequest> = {
                event_name: 'workflow:builder:edit',
                request_id: requestId,
                current_graph: { nodes: [], edges: [] },
                edit_prompt: prompt,
                generation_id: generationId,
                conversation_id: opts?.conversationId || undefined,
                user_context: {
                    inner_tab: ctx.innerTab,
                    selected_node_id: null,
                    has_workflow: false,
                },
            };
            trackChatSendStarted({
                requestId,
                model: null,
                contentLength: prompt.length,
                imageCount: 0,
                hasWorkflowContext: false,
                conversationId: opts?.conversationId || null,
            });
            await sendEventAsync(request as any, undefined, BUILDER_EDIT_TIMEOUT_MS, requestId);
            // No post-await fallback here. The final socket.io response can
            // arrive BEFORE the live `generation_complete` relay event, which
            // would make a fallback hydrate dump the snapshot via text_replace
            // and kill the character-by-character streaming visual. Recovery
            // for dropped events is covered by the relay-reconnect and
            // socket.io-reconnect listeners in builderHydration; both trigger
            // hydrateFromSnapshot when their transport flaps.
        } catch (err) {
            console.error('[HeadlessBuilder] Failed to send edit request:', err);
            this._cleanup();
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: 'Failed to start edit' },
            }));
        }
    }

    async startEdit(
        workflowId: string,
        prompt: string,
        opts?: { selectedNodeId?: string; conversationId?: string; scope?: { type: 'node'; nodeId: string } },
    ): Promise<void> {
        if (this.isActive()) {
            console.warn('[HeadlessBuilder] Edit already in progress');
            return;
        }

        const socket = socketReceiver.getSocket('API');
        if (!socket) {
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: 'Socket not connected' },
            }));
            return;
        }

        setIsAiEditing(true);

        // 1. Fetch current graph from DB
        let graphNodes: any[] = [];
        let graphEdges: any[] = [];
        try {
            const resp = await sendEventAsync(
                WorkflowGetRequest.create({ workflow_id: workflowId }),
            ) as WorkflowGetResponse;

            const wd = resp.workflow?.workflow_data as any;
            if (wd) {
                graphNodes = (wd.nodes || []).map((n: any) => ({
                    id: n.id,
                    type: n.type,
                    label: n.config?.label || '',
                    goal: n.config?.goal || '',
                    operation: n.config?.operation,
                    config: n.config || {},
                    error: null,
                    position: n.position || { x: 0, y: 0 },
                    ...(n.width != null ? { width: n.width } : {}),
                    ...(n.height != null ? { height: n.height } : {}),
                }));
                graphEdges = (wd.edges || []).map((e: any) => ({
                    id: e.id,
                    sourceId: e.source,
                    targetId: e.target,
                    ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
                    ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
                }));
            }
        } catch (err) {
            console.error('[HeadlessBuilder] Failed to fetch workflow:', err);
            this._cleanup();
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: 'Failed to fetch workflow' },
            }));
            return;
        }

        this._nodes = graphNodes;
        this._edges = graphEdges;

        // 2. Generate unique ID and dispatch started event
        const generationId = `headless_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        this._activeGenerationId = generationId;

        document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
            detail: { type: 'started', prompt, generationId },
        }));

        // 3. Set up socket response listener
        const unsubscribe = subscribeToBuilderResponse(generationId, {
            onEvent: (eventData) => this._handleEvent(eventData, workflowId, generationId),
        });
        this._cleanupListener = unsubscribe;

        // 4. Send edit request with user context
        const currentGraph = { nodes: graphNodes, edges: graphEdges };
        const ctx = getBuilderContext();
        try {
            const requestId = crypto.randomUUID();
            const request: Partial<WorkflowBuilderEditRequest> = {
                event_name: 'workflow:builder:edit',
                request_id: requestId,
                current_graph: currentGraph,
                edit_prompt: prompt,
                selected_node_id: opts?.selectedNodeId || undefined,
                generation_id: generationId,
                conversation_id: opts?.conversationId || undefined,
                user_context: {
                    workflow_id: workflowId,
                    workflow_name: ctx.workflowName,
                    inner_tab: ctx.innerTab,
                    selected_node_id: ctx.selectedInterfaceBlockId || ctx.selectedNodeId,
                    has_workflow: !!ctx.workflowId,
                },
                ...(opts?.scope?.type === 'node' ? { edit_scope: 'node' as const } : {}),
            };
            trackChatSendStarted({
                requestId,
                model: null,
                contentLength: prompt.length,
                imageCount: 0,
                hasWorkflowContext: true,
                conversationId: opts?.conversationId || null,
            });
            await sendEventAsync(request as any, undefined, BUILDER_EDIT_TIMEOUT_MS, requestId);
            // No post-await fallback — see startEditWithoutWorkflow for the
            // socket.io-vs-relay race rationale.
        } catch (err) {
            console.error('[HeadlessBuilder] Failed to send edit request:', err);
            this._cleanup();
            document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                detail: { type: 'error', error: 'Failed to start edit' },
            }));
        }
    }

    private _dispatchStatus(status: string): void {
        document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
            detail: { type: 'status', status },
        }));
    }

    /** Map backend event types to user-facing status text */
    private _statusForEvent(eventData: any): string | null {
        const t = eventData.event_type;
        const label = eventData.node?.label || eventData.label;
        switch (t) {
            case 'status': return eventData.status || null; // Backend-generated status
            case 'node_added': return label ? `Adding ${label}` : 'Adding node';
            case 'node_removed': return 'Removing node';
            case 'node_updated': return label ? `Updating ${label}` : 'Updating node';
            case 'edge_added': return 'Connecting nodes';
            case 'edge_removed': return 'Disconnecting nodes';
            case 'node_processing_start': return label ? `Configuring ${label}` : 'Configuring node';
            case 'node_operation_selected': return eventData.operation ? `Selected operation: ${eventData.operation}` : 'Selecting operation';
            case 'node_config_filling': return eventData.field ? `Setting ${eventData.field}` : 'Filling config';
            case 'open_workflow': return 'Opening workflow';
            case 'generation_complete': return 'Finishing up';
            default: return null;
        }
    }

    private async _handleEvent(eventData: any, workflowId: string, generationId: string): Promise<void> {
        const eventType = eventData.event_type;
        console.log('[HeadlessBuilder] Event:', eventType, eventData);

        // Dispatch status update for any recognized event
        const status = this._statusForEvent(eventData);
        if (status) this._dispatchStatus(status);

        switch (eventType) {
            case 'node_added': {
                const node = eventData.node;
                if (node && !this._nodes.some(n => n.id === node.id)) {
                    this._nodes.push({
                        id: node.id,
                        type: node.type,
                        label: node.label,
                        goal: node.goal,
                        operation: node.operation,
                        config: node.config || {},
                        position: node.position || { x: 0, y: 0 },
                    });
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'node_added', nodeType: node.type, label: node.label, nodeId: node.id },
                    }));
                }
                break;
            }

            case 'node_removed': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    const removed = this._nodes.find(n => n.id === nodeId);
                    this._nodes = this._nodes.filter(n => n.id !== nodeId);
                    this._edges = this._edges.filter(e => e.sourceId !== nodeId && e.targetId !== nodeId);
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'node_removed', nodeType: removed?.type, label: removed?.label, nodeId },
                    }));
                }
                break;
            }

            case 'edge_added': {
                const edge = eventData.edge;
                if (edge && !this._edges.some(e => e.id === edge.id)) {
                    this._edges.push({
                        id: edge.id,
                        sourceId: edge.sourceId,
                        targetId: edge.targetId,
                        ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
                        ...(edge.targetHandle ? { targetHandle: edge.targetHandle } : {}),
                    });
                    const sourceNode = this._nodes.find(n => n.id === edge.sourceId);
                    const targetNode = this._nodes.find(n => n.id === edge.targetId);
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'edge_added',
                            edgeId: edge.id,
                            sourceNodeId: edge.sourceId,
                            sourceNodeLabel: sourceNode?.label || edge.sourceId,
                            sourceNodeType: sourceNode?.type,
                            targetNodeId: edge.targetId,
                            targetNodeLabel: targetNode?.label || edge.targetId,
                            targetNodeType: targetNode?.type,
                        },
                    }));
                }
                break;
            }

            case 'edge_removed': {
                const edgeId = eventData.edgeId;
                if (edgeId) {
                    const removed = this._edges.find(e => e.id === edgeId);
                    const sourceNode = removed ? this._nodes.find(n => n.id === removed.sourceId) : null;
                    const targetNode = removed ? this._nodes.find(n => n.id === removed.targetId) : null;
                    this._edges = this._edges.filter(e => e.id !== edgeId);
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'edge_removed',
                            edgeId,
                            sourceNodeId: removed?.sourceId,
                            sourceNodeLabel: sourceNode?.label || removed?.sourceId || 'Unknown',
                            sourceNodeType: sourceNode?.type,
                            targetNodeId: removed?.targetId,
                            targetNodeLabel: targetNode?.label || removed?.targetId || 'Unknown',
                            targetNodeType: targetNode?.type,
                        },
                    }));
                }
                break;
            }

            case 'node_updated': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    const node = this._nodes.find(n => n.id === nodeId);
                    if (node) {
                        if (eventData.operation) node.operation = eventData.operation;
                        if (eventData.goal) node.goal = eventData.goal;
                        if (eventData.config) node.config = { ...node.config, ...eventData.config };
                    }
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_updated',
                            nodeType: node?.type,
                            label: node?.label || nodeId,
                            nodeId,
                            operation: eventData.operation,
                            config: eventData.config,
                        },
                    }));
                }
                break;
            }

            case 'node_processing_start':
            case 'node_operation_selected':
            case 'node_config_filling': {
                const nodeId = eventData.nodeId;
                if (nodeId) {
                    const node = this._nodes.find(n => n.id === nodeId);
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: {
                            type: 'node_processing',
                            nodeType: node?.type,
                            label: node?.label || nodeId,
                            nodeId,
                            operation: eventData.operation,
                            config: eventData.field ? { [eventData.field]: eventData.value } : undefined,
                        },
                    }));
                }
                break;
            }

            case 'input_request': {
                document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
                    detail: {
                        inputs: eventData.inputs,
                        title: 'Input needed',
                        // Forward the backend-issued ask_id (builder.py emits it in the
                        // input_request payload). The other 4 producers all carry it;
                        // this live path used to drop it, which silently disabled the
                        // bridge's dismiss/re-surface dedup AND the builder_input_bridge_shown
                        // event (both keyed on askId) for headless-builder asks.
                        askId: eventData.ask_id,
                        generationId,
                        // Scope so the bridge can self-close on nav-away
                        workflowId,
                    },
                }));
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'status', status: 'Waiting for your input' },
                }));
                break;
            }

            case 'text_chunk': {
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'text_chunk', text: eventData.text },
                }));
                break;
            }

            case 'open_workflow': {
                const targetWorkflowId = eventData.workflow_id;
                if (targetWorkflowId) {
                    console.log('[HeadlessBuilder] Opening workflow:', targetWorkflowId);
                    updateBuilderContext({ workflowId: targetWorkflowId });
                    document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                        detail: { type: 'open_workflow', workflowId: targetWorkflowId },
                    }));
                    window.dispatchEvent(new CustomEvent('noclick:navigate-to-node', {
                        detail: { workflowId: targetWorkflowId, nodeId: '' },
                    }));
                }
                break;
            }

            case 'run_test': {
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
                document.dispatchEvent(new CustomEvent('noclick:workflow-settings-updated', {
                    detail: { workflowId: eventData.workflow_id || workflowId },
                }));
                break;
            }

            case 'generation_complete': {
                // Save final graph back to DB (skip if no workflow — e.g. pure list/open flow)
                // Node state updates are handled in real-time by useMCPBuilderEvents
                // via mcp:builder_event socket events emitted by the backend handler.
                if (workflowId) {
                    await this._saveWorkflow(workflowId);
                }
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'complete' },
                }));
                this._cleanup();
                break;
            }

            case 'error': {
                document.dispatchEvent(new CustomEvent('noclick:workflow:edit:event', {
                    detail: { type: 'error', error: eventData.error || 'Unknown error' },
                }));
                this._cleanup();
                break;
            }
        }
    }

    private async _saveWorkflow(workflowId: string): Promise<void> {
        try {
            const workflowData = {
                nodes: this._nodes.map(n => ({
                    id: n.id,
                    type: n.type,
                    position: n.position || { x: 0, y: 0 },
                    config: {
                        label: n.label,
                        goal: n.goal,
                        operation: n.operation,
                        ...n.config,
                    },
                    ...(n.width != null ? { width: n.width } : {}),
                    ...(n.height != null ? { height: n.height } : {}),
                })),
                edges: this._edges.map(e => ({
                    id: e.id,
                    source: e.sourceId,
                    target: e.targetId,
                    ...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
                    ...(e.targetHandle ? { targetHandle: e.targetHandle } : {}),
                })),
            };

            await sendEventAsync(
                WorkflowUpdateRequest.create({
                    workflow_id: workflowId,
                    workflow_data: workflowData,
                }),
            );
            console.log('[HeadlessBuilder] Saved workflow successfully');
        } catch (err) {
            console.error('[HeadlessBuilder] Failed to save workflow:', err);
        }
    }

    private _cleanup(): void {
        this._cleanupListener?.();
        this._cleanupListener = null;
        // Clear whichever gen the registry currently has — the call is a
        this._activeGenerationId = null;
        this._nodes = [];
        this._edges = [];
        setIsAiEditing(false);
    }
}

export const headlessBuilder = new HeadlessBuilder();
