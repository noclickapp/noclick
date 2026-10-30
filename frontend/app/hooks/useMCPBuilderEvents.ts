/**
 * Hook for handling MCP builder events from the new /mcp endpoint.
 *
 * Listens for 'mcp:builder_event' socket events emitted when external MCP clients
 * (Claude Code, Cursor) modify workflows. Applies ReactFlow state mutations with
 * animation states to provide real-time visual feedback on the canvas.
 */

import { useEffect, useCallback, useRef } from 'react';
import { Node, Edge } from '@xyflow/react';
import { updateNodeInList, rawConfigToPayload } from '~/lib/applyNodeUpdate';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEventAsync } from '~/lib/socket-sender';
import { markStepPartial, reloadFromServer, takeServerStep } from '~/lib/liveGraphStore';
import { GRAPH_EVENT_TYPES, serverEdgesAfter, serverNodesAfter } from '~/lib/serverGraphEvents';

// A step the room held part of back is read whole this many times (waiting longer each time); when it can't be,
// the canvas reads the whole workflow again instead, so it never saves its partial copy.
export const FETCH_WHOLE_TRIES = 3;
const FETCH_WHOLE_BACKOFF_MS = 2000;

interface MCPBuilderEvent {
    workflow_id: string;
    event_type: string;
    data: Record<string, any>;
}

interface UseMCPBuilderEventsParams {
    workflowId?: string;
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    setEdges: React.Dispatch<React.SetStateAction<Edge[]>>;
}

export function useMCPBuilderEvents({
    workflowId,
    setNodes,
    setEdges,
}: UseMCPBuilderEventsParams) {
    // Track animation timeouts to clear them on unmount
    const animationTimers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
    // Track last MCP event timestamp for auto-save suppression
    const lastMCPEventRef = useRef<number>(0);

    const clearAnimationState = useCallback((nodeId: string, delay = 500) => {
        const timer = setTimeout(() => {
            setNodes(curr => updateNodeInList(curr, nodeId, { extras: { mcpAnimationState: undefined } }));
            animationTimers.current.delete(timer);
        }, delay);
        animationTimers.current.add(timer);
    }, [setNodes]);

    // A step the graph service's room event held part of back (a secret, an outsize setting): read it whole
    // through the canvas's own authorized read. Until it has, the step can't be edited (its panel shows it
    // loading) and every save keeps it as stored; when it can't be read, the whole workflow is read again.
    const fetchWhole = useCallback(async (nodeId: string) => {
        if (!workflowId) return;
        markStepPartial(workflowId, nodeId);
        for (let attempt = 1; attempt <= FETCH_WHOLE_TRIES; attempt++) {
            try {
                const resp = (await sendEventAsync({
                    event_name: 'workflow:node:get_config',
                    workflow_id: workflowId,
                    node_id: nodeId,
                } as never)) as { config?: Record<string, unknown> } | null;
                const config = resp?.config;
                if (config) {
                    setNodes(curr => updateNodeInList(curr, nodeId, rawConfigToPayload(config)));
                    takeServerStep(workflowId, nodeId, config);
                    return;
                }
                break;
            } catch (e) {
                if (attempt === FETCH_WHOLE_TRIES) {
                    console.error('[useMCPBuilderEvents] reading a step whole failed; reading the workflow:', e);
                    break;
                }
                await new Promise(resolve => setTimeout(resolve, FETCH_WHOLE_BACKOFF_MS * attempt));
            }
        }
        await reloadFromServer(workflowId);
    }, [workflowId, setNodes]);

    const handleEvent = useCallback((event: MCPBuilderEvent) => {
        if (!workflowId || event.workflow_id !== workflowId) return;

        lastMCPEventRef.current = Date.now();
        const { event_type, data } = event;

        if (GRAPH_EVENT_TYPES.has(event_type)) {
            setNodes(curr => serverNodesAfter(curr, event_type, data, true));
            setEdges(curr => serverEdgesAfter(curr, event_type, data, true));
            if (event_type === 'node_updated' && data.nodeId) {
                clearAnimationState(data.nodeId);
                if (data.refetch) void fetchWhole(data.nodeId);
            }
            if (event_type === 'layout_applied' && data.positions && typeof data.positions === 'object') {
                // The move animates; its transition comes off once it's done.
                const moved = data.positions as Record<string, unknown>;
                const layoutTimer = setTimeout(() => {
                    setNodes(curr => curr.map(n => {
                        if (!moved[n.id]) return n;
                        const style = { ...n.style };
                        delete (style as Record<string, unknown>).transition;
                        return { ...n, style: Object.keys(style).length ? style : undefined };
                    }));
                }, 600);
                animationTimers.current.add(layoutTimer);
            }
            return;
        }

        switch (event_type) {
            case 'node_processing_start': {
                // Node transitions to 'editing' glow
                const { nodeId } = data;
                if (!nodeId) break;
                setNodes(curr => updateNodeInList(curr, nodeId, { extras: { mcpAnimationState: 'editing' } }));
                break;
            }

            case 'run_test': {
                // External MCP builder fired <run_test/> — same hand-off as
                // the agentic builder's ResponseEvent channel.
                document.dispatchEvent(new CustomEvent('noclick:run-test', {
                    detail: { workflowId, trigger: data.trigger, run: data.run },
                }));
                break;
            }

            case 'settings_updated': {
                document.dispatchEvent(new CustomEvent('noclick:workflow-settings-updated', {
                    detail: { workflowId },
                }));
                break;
            }
        }
    }, [workflowId, setNodes, setEdges, clearAnimationState, fetchWhole]);

    useEffect(() => {
        const unsubscribe = onSocketEvent(
            'mcp:builder_event' as any,
            handleEvent as any
        );
        return () => {
            unsubscribe();
            // Clear any pending animation timers
            animationTimers.current.forEach(clearTimeout);
            animationTimers.current.clear();
        };
    }, [handleEvent]);

    return { lastMCPEventRef };
}
