/**
 * Hook for handling MCP builder events from the new /mcp endpoint.
 *
 * Listens for 'mcp:builder_event' socket events emitted when external MCP clients
 * (Claude Code, Cursor) modify workflows. Applies ReactFlow state mutations with
 * animation states to provide real-time visual feedback on the canvas.
 */

import { useEffect, useCallback, useRef } from 'react';
import { Node, Edge } from '@xyflow/react';
import { applyNodeUpdate, createWorkflowNode, updateNodeInList, rawConfigToPayload } from '~/lib/applyNodeUpdate';
import { onSocketEvent } from '~/lib/socket-receiver';
// Node dimensions come from the serialized icon singleton (dashboard loader), not
// the registry — this hook runs always-mounted via useMCPNavigation, so importing
// the registry here would pull its ~4.7MB component graph into the dashboard bundle.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';

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

    const handleEvent = useCallback((event: MCPBuilderEvent) => {
        if (!workflowId || event.workflow_id !== workflowId) return;

        lastMCPEventRef.current = Date.now();
        const { event_type, data } = event;

        switch (event_type) {
            case 'node_start': {
                // Node appears with 'adding' animation
                const nodeData = data.node;
                if (!nodeData) break;
                if (!nodeData.id) {
                    console.error('[useMCPBuilderEvents] node_start missing id:', nodeData);
                    break;
                }
                const newNode = createWorkflowNode(
                    nodeData.id,
                    nodeData.type,
                    nodeData.position || { x: 250, y: 150 },
                    {
                        ...(nodeData.label ? { label: nodeData.label } : {}),
                        ...(nodeData.operation ? { operation: nodeData.operation } : {}),
                        ...(nodeData.goal ? { goal: nodeData.goal } : {}),
                        ...(nodeData.content !== undefined ? { content: nodeData.content } : {}),
                        ...(nodeData.color !== undefined ? { color: nodeData.color } : {}),
                    },
                    { mcpAnimationState: 'adding' },
                );
                // Set initial dimensions for resizable nodes (sticky notes + interface blocks)
                if (nodeData.type === 'stickyNote' && (nodeData.width || nodeData.height)) {
                    newNode.style = {
                        width: nodeData.width || 200,
                        height: nodeData.height || 200,
                    };
                    newNode.width = nodeData.width || 200;
                    newNode.height = nodeData.height || 200;
                } else if (nodeData.type?.startsWith('interface-')) {
                    const nodeDef = getNodeIconMeta(nodeData.type);
                    newNode.style = {
                        width: nodeDef?.dimensions.width || 350,
                        height: nodeDef?.dimensions.height || 200,
                    };
                }
                setNodes(curr => {
                    if (curr.some(n => n.id === nodeData.id)) return curr;
                    return [...curr, newNode];
                });
                break;
            }

            case 'node_processing_start': {
                // Node transitions to 'editing' glow
                const { nodeId } = data;
                if (!nodeId) break;
                setNodes(curr => updateNodeInList(curr, nodeId, { extras: { mcpAnimationState: 'editing' } }));
                break;
            }

            case 'node_updated': {
                // Node settles to 'complete', config updates applied.
                // `config` is the backend flat blob — config fields plus
                // metadata (credentialIds, label, operation) mixed at the top
                // level. rawConfigToPayload routes each key to the correct
                // place in the node data model; passing it raw as `config`
                // would bury credentialIds at data.config.credentialIds where
                // NodeCredentials can't see it.
                const { nodeId, config, type, position } = data;
                if (!nodeId) break;
                const payload = rawConfigToPayload(config || {});
                setNodes(curr => {
                    const exists = curr.some(n => n.id === nodeId);
                    if (!exists && type) {
                        // Node wasn't added by node_start yet — create it via applyNodeUpdate
                        // on a fresh empty node to get proper operation sync
                        const blank = createWorkflowNode(nodeId, type, position || { x: 250, y: 150 }, {});
                        return [...curr, applyNodeUpdate(blank, {
                            ...payload,
                            extras: { mcpAnimationState: 'complete' },
                        })];
                    }
                    return curr.map(n => {
                        if (n.id !== nodeId) return n;
                        return applyNodeUpdate(n, {
                            ...payload,
                            extras: { mcpAnimationState: 'complete' },
                        });
                    });
                });
                clearAnimationState(nodeId);
                break;
            }

            case 'node_removed': {
                const { nodeId, removedEdgeIds } = data;
                if (!nodeId) break;
                setNodes(curr => curr.filter(n => n.id !== nodeId));
                if (removedEdgeIds?.length) {
                    setEdges(curr => curr.filter(e => !removedEdgeIds.includes(e.id)));
                }
                break;
            }

            case 'edge_added': {
                const edgeData = data.edge;
                if (!edgeData) break;
                setEdges(curr => {
                    if (curr.some(e => e.id === edgeData.id)) return curr;
                    return [...curr, {
                        id: edgeData.id,
                        source: edgeData.source,
                        target: edgeData.target,
                        ...(edgeData.sourceHandle ? { sourceHandle: edgeData.sourceHandle } : {}),
                        ...(edgeData.targetHandle ? { targetHandle: edgeData.targetHandle } : {}),
                        type: 'animated',
                        animated: true,
                        style: { stroke: 'hsl(var(--foreground))', strokeWidth: 3, opacity: 0.8, strokeDasharray: '5 5' },
                        data: { isAnimating: false },
                    }];
                });
                break;
            }

            case 'edge_removed': {
                const { edgeId } = data;
                if (!edgeId) break;
                setEdges(curr => curr.filter(e => e.id !== edgeId));
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

            case 'layout_applied': {
                const { positions, sticky_updates } = data;
                if (!positions || typeof positions !== 'object') break;
                // Animate nodes to their autolayout positions (includes sticky notes)
                setNodes(curr => curr.map(n => {
                    const pos = positions[n.id];
                    if (!pos) return n;
                    const stickyDims = sticky_updates?.[n.id];
                    return {
                        ...n,
                        position: pos,
                        ...(stickyDims ? {
                            width: stickyDims.width,
                            height: stickyDims.height,
                            style: { ...n.style, width: stickyDims.width, height: stickyDims.height, transition: 'transform 0.5s ease' },
                        } : {
                            style: { ...n.style, transition: 'transform 0.5s ease' },
                        }),
                    };
                }));
                // Remove transition style after animation completes
                const layoutTimer = setTimeout(() => {
                    setNodes(curr => curr.map(n => {
                        if (!positions[n.id]) return n;
                        const style = { ...n.style };
                        delete (style as Record<string, unknown>).transition;
                        return { ...n, style: Object.keys(style).length ? style : undefined };
                    }));
                }, 600);
                animationTimers.current.add(layoutTimer);
                break;
            }
        }
    }, [workflowId, setNodes, setEdges, clearAnimationState]);

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
