// Read-only ReactFlow workflow viewer for MCP Apps widgets.
// Imports the actual node types and edge renderers from the main codebase
// so the widget looks identical to the app.

import React, { useCallback, useEffect, useState } from 'react';
import {
    ReactFlow,
    ReactFlowProvider,
    useNodesState,
    useEdgesState,
    useReactFlow,
    applyNodeChanges,
    type NodeChange,
} from '@xyflow/react';
import type { Node, Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { buildReactFlowNodeTypes } from '~/components/workflow/nodes/nodeRegistry';
import AnimatedWorkflowEdge from '~/components/workflow/edges/AnimatedWorkflowEdge';
// Shared canvas grid + surface, so the widget can't drift from the app canvas.
import { CanvasBackground, CANVAS_SURFACE } from '~/components/workflow/canvasBackground';

// Build node types once at module level (same as main app)
const nodeTypes = buildReactFlowNodeTypes();
const edgeTypes = { animated: AnimatedWorkflowEdge };

interface WorkflowViewerProps {
    nodes: Node[];
    edges: Edge[];
    workflowName?: string;
    loading?: boolean;
    /** True when the MCP host has put the widget into fullscreen mode. */
    isHostFullscreen?: boolean;
    /** Called on toggle; returns true if host handled it, false → use CSS fallback. */
    onToggleFullscreen?: () => Promise<boolean>;
}

function LoadingState() {
    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                width: '100%',
                height: '100%',
                color: 'rgba(255,255,255,0.5)',
                fontSize: 14,
                gap: 12,
            }}
        >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ animation: 'spin 1s linear infinite' }}>
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" strokeDasharray="31.4 31.4" strokeLinecap="round" />
            </svg>
            <span>Loading workflow…</span>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}

export function WorkflowViewer({ nodes, edges, workflowName, loading, isHostFullscreen, onToggleFullscreen }: WorkflowViewerProps) {
    // cssExpanded is the fallback for hosts that don't support requestDisplayMode
    const [cssExpanded, setCssExpanded] = useState(false);
    const expanded = isHostFullscreen || cssExpanded;

    const handleToggle = useCallback(async () => {
        if (onToggleFullscreen) {
            const hostHandled = await onToggleFullscreen();
            // If host didn't apply the mode change, toggle our CSS fallback
            if (!hostHandled) {
                setCssExpanded(v => !v);
            }
        } else {
            setCssExpanded(v => !v);
        }
    }, [onToggleFullscreen]);

    // Collapse CSS fallback with Escape (host handles its own Escape for native fullscreen)
    useEffect(() => {
        if (!cssExpanded) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCssExpanded(false); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [cssExpanded]);

    if (loading && nodes.length === 0) {
        return <LoadingState />;
    }

    const containerStyle: React.CSSProperties = cssExpanded
        ? { position: 'fixed', inset: 0, width: '100vw', height: '100vh', zIndex: 9999, background: CANVAS_SURFACE }
        : { width: '100%', height: '100%', position: 'relative' };

    return (
        <div style={containerStyle}>
            {/* Workflow name overlay */}
            {workflowName && (
                <div
                    style={{
                        position: 'absolute',
                        top: 12,
                        left: 16,
                        zIndex: 10,
                        color: 'rgba(255,255,255,0.7)',
                        fontSize: 13,
                        fontWeight: 500,
                        letterSpacing: '0.02em',
                        textShadow: '0 1px 4px rgba(0,0,0,0.8)',
                        pointerEvents: 'none',
                    }}
                >
                    {workflowName}
                </div>
            )}
            {/* Expand / collapse button — top-right */}
            <button
                onClick={handleToggle}
                title={expanded ? 'Exit fullscreen' : 'Fullscreen'}
                style={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    zIndex: 10,
                    background: 'rgba(255,255,255,0.07)',
                    border: '1px solid rgba(255,255,255,0.12)',
                    borderRadius: 6,
                    padding: '5px 6px',
                    cursor: 'pointer',
                    color: 'rgba(255,255,255,0.55)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    lineHeight: 0,
                }}
            >
                {expanded ? (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="4 14 10 14 10 20" />
                        <polyline points="20 10 14 10 14 4" />
                        <line x1="10" y1="14" x2="3" y2="21" />
                        <line x1="21" y1="3" x2="14" y2="10" />
                    </svg>
                ) : (
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="15 3 21 3 21 9" />
                        <polyline points="9 21 3 21 3 15" />
                        <line x1="21" y1="3" x2="14" y2="10" />
                        <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                )}
            </button>
            <ReactFlowProvider>
                <WorkflowViewerInner nodes={nodes} edges={edges} expanded={expanded} />
            </ReactFlowProvider>
        </div>
    );
}

/** Inner component with controlled ReactFlow state for dragging support. */
function WorkflowViewerInner({ nodes, edges, expanded }: { nodes: Node[]; edges: Edge[]; expanded: boolean }) {
    const [rfNodes, setNodes, onNodesChange] = useNodesState(nodes);
    const [rfEdges, setEdges, onEdgesChange] = useEdgesState(edges);
    const { fitView } = useReactFlow();

    // Sync props → state when new data arrives from host
    useEffect(() => { setNodes(nodes); }, [nodes, setNodes]);
    useEffect(() => { setEdges(edges); }, [edges, setEdges]);

    // Re-fit the workflow to centre after the iframe resizes on expand/collapse.
    // The 200ms delay gives the host time to finish resizing the iframe first.
    useEffect(() => {
        const id = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 200);
        return () => clearTimeout(id);
    }, [expanded, fitView]);

    // Allow position, select, and dimensions changes (dimensions needed for edge recalculation)
    const handleNodesChange = useCallback((changes: NodeChange[]) => {
        const allowed = changes.filter(c =>
            c.type === 'position' || c.type === 'select' || c.type === 'dimensions'
        );
        if (allowed.length > 0) {
            setNodes(nds => applyNodeChanges(allowed, nds) as typeof nds);
        }
    }, [setNodes]);

    return (
        <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            nodesDraggable={true}
            nodesConnectable={false}
            elementsSelectable={true}
            panOnDrag={true}
            zoomOnScroll={true}
            zoomOnPinch={true}
            preventScrolling={false}
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
        >
            <CanvasBackground />
        </ReactFlow>
    );
}
