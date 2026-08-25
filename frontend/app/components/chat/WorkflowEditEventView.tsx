/**
 * WorkflowEditEventView - Visual component for displaying workflow edit events in chat.
 * Shows consolidated node and edge cards that update dynamically.
 * Events are grouped by node/edge, so each shows as a single card with current status.
 */

import { memo, useMemo } from 'react';
import { Loader2, CheckCircle2, AlertCircle, Trash2, Zap, ArrowRight, Link2, Unlink2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';
import { WorkflowEditEvent } from './types';
// Node brand icons resolve from the serialized node-icon singleton (dashboard
// loader), not the registry — keeps this chat view off the registry's heavy graph.
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { navigateToNode, navigateToEdge } from '~/utils/workflowNavigation';

interface WorkflowEditEventViewProps {
    events: WorkflowEditEvent[];
    isComplete: boolean;
    workflowId?: string;
    messageIndex?: number;
}

// Get node definition from registry by type
function getNodeDefinition(nodeType: string | undefined) {
    if (!nodeType) return null;
    return getNodeIconMeta(nodeType) ?? null;
}

// Consolidated node state from events
interface NodeEditState {
    nodeId: string;
    nodeType?: string;
    nodeLabel?: string;
    action: 'added' | 'removed' | 'updated' | 'processing';
    status: 'pending' | 'in_progress' | 'completed';
    firstSeenTimestamp: number;
    insertionOrder: number;
    operation?: string;
    config?: Record<string, any>;
}

// Consolidated edge state from events
interface EdgeEditState {
    edgeId: string;
    sourceNodeId?: string;
    sourceLabel: string;
    sourceType?: string;
    targetNodeId?: string;
    targetLabel: string;
    targetType?: string;
    action: 'added' | 'removed';
    status: 'pending' | 'in_progress' | 'completed';
    timestamp: number;
    insertionOrder: number;
}

// Backend-persisted edit segments embed node/edge info under nested `event.node`
// and `event.edge` (from BuilderStreamEvent payloads) instead of the flat
// `nodeType`/`nodeLabel`/`edgeId`/etc. that live in-memory events use. Restored
// conversations otherwise render with generic Zap icons because the renderer
// only reads the flat fields. We also propagate `nodeType`/`nodeLabel` to
// downstream events for the same node id, since update/remove/processing events
// only carry `nodeId` even in the live shape.
export function normalizeEvents(events: WorkflowEditEvent[]): WorkflowEditEvent[] {
    const nodeInfo = new Map<string, { type?: string; label?: string }>();
    for (const raw of events) {
        const nested = (raw as any).node;
        const id = raw.nodeId ?? nested?.id;
        if (!id) continue;
        const existing = nodeInfo.get(id) ?? {};
        nodeInfo.set(id, {
            type: existing.type ?? raw.nodeType ?? nested?.type,
            label: existing.label ?? raw.nodeLabel ?? nested?.label,
        });
    }

    return events.map(raw => {
        const nestedNode = (raw as any).node;
        const nestedEdge = (raw as any).edge;
        const nodeId = raw.nodeId ?? nestedNode?.id;
        const ndInfo = nodeId ? nodeInfo.get(nodeId) : undefined;
        // Backend persists edges as `{sourceId, targetId}` (graph_state.EdgeState.to_dict);
        // the MCP bridge normalizes to `{source, target}`. Prefer the persisted shape.
        const sourceId = raw.sourceNodeId ?? nestedEdge?.sourceId ?? nestedEdge?.source;
        const targetId = raw.targetNodeId ?? nestedEdge?.targetId ?? nestedEdge?.target;
        const srcInfo = sourceId ? nodeInfo.get(sourceId) : undefined;
        const tgtInfo = targetId ? nodeInfo.get(targetId) : undefined;
        return {
            ...raw,
            nodeId,
            nodeType: raw.nodeType ?? nestedNode?.type ?? ndInfo?.type,
            nodeLabel: raw.nodeLabel ?? nestedNode?.label ?? ndInfo?.label,
            operation: raw.operation ?? nestedNode?.operation,
            config: raw.config ?? nestedNode?.config,
            edgeId: raw.edgeId ?? nestedEdge?.id,
            sourceNodeId: sourceId,
            targetNodeId: targetId,
            sourceNodeType: raw.sourceNodeType ?? srcInfo?.type,
            sourceNodeLabel: raw.sourceNodeLabel ?? srcInfo?.label,
            targetNodeType: raw.targetNodeType ?? tgtInfo?.type,
            targetNodeLabel: raw.targetNodeLabel ?? tgtInfo?.label,
        };
    });
}

// Process events into consolidated node and edge states
export function consolidateEvents(events: WorkflowEditEvent[]): { nodes: NodeEditState[]; edges: EdgeEditState[] } {
    const nodeStates = new Map<string, NodeEditState>();
    const edgeStates = new Map<string, EdgeEditState>();
    let nodeInsertionCounter = 0;
    let edgeInsertionCounter = 0;

    for (const event of normalizeEvents(events)) {
        // Handle edge events
        if (event.type === 'edge_added' || event.type === 'edge_removed') {
            if (event.edgeId) {
                const existing = edgeStates.get(event.edgeId);
                edgeStates.set(event.edgeId, {
                    edgeId: event.edgeId,
                    sourceNodeId: event.sourceNodeId || existing?.sourceNodeId,
                    sourceLabel: event.sourceNodeLabel || 'Node',
                    sourceType: event.sourceNodeType || existing?.sourceType,
                    targetNodeId: event.targetNodeId || existing?.targetNodeId,
                    targetLabel: event.targetNodeLabel || 'Node',
                    targetType: event.targetNodeType || existing?.targetType,
                    action: event.type === 'edge_added' ? 'added' : 'removed',
                    status: event.status,
                    timestamp: existing?.timestamp ?? event.timestamp,
                    insertionOrder: existing?.insertionOrder ?? edgeInsertionCounter++,
                });
            }
            continue;
        }

        // Skip non-node events
        if (!event.nodeId || event.type === 'started' || event.type === 'complete' || event.type === 'error' || event.type === 'text_chunk') {
            continue;
        }

        const action = event.type === 'node_added' ? 'added' :
                      event.type === 'node_removed' ? 'removed' :
                      event.type === 'node_updated' ? 'updated' : 'processing';

        const existing = nodeStates.get(event.nodeId);
        const mergedConfig = existing?.config ? { ...existing.config } : {};
        if (event.config) {
            Object.assign(mergedConfig, event.config);
        }

        const isNewNode = !existing;
        const insertionOrder = isNewNode ? nodeInsertionCounter++ : existing.insertionOrder;

        nodeStates.set(event.nodeId, {
            nodeId: event.nodeId,
            nodeType: event.nodeType || existing?.nodeType,
            nodeLabel: event.nodeLabel || existing?.nodeLabel,
            action,
            status: event.status,
            firstSeenTimestamp: existing?.firstSeenTimestamp ?? event.timestamp,
            insertionOrder,
            operation: event.operation || existing?.operation,
            config: Object.keys(mergedConfig).length > 0 ? mergedConfig : undefined,
        });
    }

    // Stable sort: by timestamp first, then insertion order
    const sortedNodes = Array.from(nodeStates.values()).sort((a, b) => {
        const timeDiff = a.firstSeenTimestamp - b.firstSeenTimestamp;
        if (timeDiff !== 0) return timeDiff;
        return a.insertionOrder - b.insertionOrder;
    });

    const sortedEdges = Array.from(edgeStates.values()).sort((a, b) => {
        const timeDiff = a.timestamp - b.timestamp;
        if (timeDiff !== 0) return timeDiff;
        return a.insertionOrder - b.insertionOrder;
    });

    return { nodes: sortedNodes, edges: sortedEdges };
}

// Simple node card with CSS transitions only
const NodeCard = memo(({ state, workflowId }: { state: NodeEditState; workflowId?: string }) => {
    const nodeDef = getNodeDefinition(state.nodeType);
    const iconHtml = nodeDef?.iconHtml;
    const iconColor = nodeDef?.iconColor || '';

    const isActive = state.status === 'in_progress';
    const isRemoved = state.action === 'removed';
    const isCompleted = state.status === 'completed' && !isRemoved;

    const hasExpandedContent = state.operation || (state.config && Object.keys(state.config).length > 0);
    const showExpanded = isActive && hasExpandedContent;

    const handleClick = () => {
        if (!isCompleted || !workflowId) return;
        navigateToNode(workflowId, state.nodeId);
    };

    return (
        <div
            onClick={handleClick}
            className={cn(
                "w-full max-w-[260px] rounded-xl border overflow-hidden transition-all duration-200",
                isRemoved
                    ? "border-red-500/30 bg-red-500/[0.06]"
                    : "border-border dark:border-white/[0.08] bg-foreground/[0.03]",
                isCompleted && workflowId && "cursor-pointer hover:bg-foreground/[0.06]"
            )}
        >
            {/* Main row */}
            <div className="flex">
                <div className={cn(
                    "w-12 shrink-0 flex items-center justify-center border-r",
                    isRemoved
                        ? "bg-red-500/[0.08] border-red-500/20"
                        : "bg-foreground/[0.03] border-border dark:border-white/[0.06]"
                )}>
                    {isRemoved ? (
                        <Trash2 className="w-6 h-6 text-red-600 dark:text-red-400" />
                    ) : iconHtml ? (
                        <SerializedIcon html={iconHtml} iconColor={iconColor} className="w-6 h-6" />
                    ) : (
                        <Zap className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
                    )}
                </div>

                <div className="flex-1 min-w-0 flex items-center gap-2 px-3 h-12">
                    <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium text-foreground truncate">
                            {state.nodeLabel || nodeDef?.label || 'Node'}
                        </div>
                        <div className={cn(
                            "text-[10px] uppercase tracking-wide",
                            isRemoved ? "text-red-600/60 dark:text-red-400/60" :
                            isActive ? "text-foreground/35" : "text-foreground/30"
                        )}>
                            {isActive ? (
                                state.action === 'added' ? 'Adding...' :
                                state.action === 'removed' ? 'Removing...' :
                                state.action === 'updated' ? 'Updating...' : 'Processing...'
                            ) : (
                                state.action === 'removed' ? 'Removed' :
                                state.action === 'added' ? 'Added' : 'Updated'
                            )}
                        </div>
                    </div>

                    {isActive ? (
                        <Loader2 className="w-3.5 h-3.5 text-foreground/40 animate-spin shrink-0" />
                    ) : (
                        <CheckCircle2 className={cn(
                            "w-3.5 h-3.5 shrink-0 transition-transform duration-200",
                            isRemoved ? "text-red-600/70 dark:text-red-400/70" : "text-emerald-500/80"
                        )} />
                    )}
                </div>
            </div>

            {/* Expandable section - pure CSS transition */}
            <div
                className={cn(
                    "overflow-hidden transition-all duration-200 ease-out",
                    showExpanded ? "max-h-40 opacity-100" : "max-h-0 opacity-0"
                )}
            >
                <div className="border-t border-border dark:border-white/[0.06] px-3 py-2 space-y-1.5">
                    {state.operation && (
                        <div className="flex items-center gap-1.5">
                            <span className="text-[10px] uppercase tracking-wider text-foreground/40">Action</span>
                            <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">{state.operation}</span>
                        </div>
                    )}
                    {state.config && Object.keys(state.config).length > 0 && (
                        <div className="space-y-0.5">
                            <span className="text-[10px] uppercase tracking-wider text-foreground/40">Config</span>
                            <div className="font-mono text-[10px] text-foreground/50 space-y-0.5">
                                {Object.entries(state.config).slice(0, 4).map(([key, value]) => (
                                    <div key={key} className="flex gap-1.5">
                                        <span className="text-foreground/30">{key}:</span>
                                        <span className="text-foreground/60 truncate">
                                            {value === null ? 'null' : typeof value === 'object' ? JSON.stringify(value) : String(value)}
                                        </span>
                                    </div>
                                ))}
                                {Object.keys(state.config).length > 4 && (
                                    <span className="text-foreground/30">+{Object.keys(state.config).length - 4} more</span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

NodeCard.displayName = 'NodeCard';

// Compact edge card - subtle styling, clickable to zoom to edge
const EdgeCard = memo(({ state, workflowId }: { state: EdgeEditState; workflowId?: string }) => {
    const isRemoved = state.action === 'removed';
    const isCompleted = state.status === 'completed';
    const isClickable = isCompleted && workflowId && !isRemoved;

    // Get node icons (serialized markup; fall back to a generic Zap glyph)
    const sourceDef = getNodeDefinition(state.sourceType);
    const targetDef = getNodeDefinition(state.targetType);
    const sourceIconHtml = sourceDef?.iconHtml;
    const targetIconHtml = targetDef?.iconHtml;

    const handleClick = () => {
        if (!isClickable || !workflowId) return;
        navigateToEdge(workflowId, state.edgeId, state.sourceNodeId, state.targetNodeId);
    };

    return (
        <div
            onClick={handleClick}
            className={cn(
                "w-full max-w-[260px] rounded-lg border px-3 py-1.5 flex items-center gap-2 transition-colors",
                isRemoved
                    ? "border-red-500/10 bg-red-500/[0.02]"
                    : "border-border/50 dark:border-white/[0.04] bg-transparent",
                isClickable && "cursor-pointer hover:bg-foreground/[0.03]"
            )}
        >
            {isRemoved ? (
                <Unlink2 className="w-3.5 h-3.5 text-red-600/60 dark:text-red-400/60 shrink-0" />
            ) : (
                <Link2 className="w-3.5 h-3.5 text-foreground/40 shrink-0" />
            )}
            <div className={cn(
                "flex items-center gap-1.5 text-[11px] min-w-0 flex-1",
                isRemoved ? "text-red-600/60 dark:text-red-400/60" : "text-foreground/50"
            )}>
                {/* Source node with icon */}
                <div className="flex items-center gap-1 min-w-0">
                    {sourceIconHtml ? (
                        <SerializedIcon html={sourceIconHtml} iconColor={sourceDef?.iconColor || ''} className="w-3 h-3 shrink-0 opacity-60" />
                    ) : (
                        <Zap className="w-3 h-3 shrink-0 opacity-60" />
                    )}
                    <span className="truncate max-w-[60px]">{state.sourceLabel}</span>
                </div>

                {/* Arrow - with strikethrough for disconnection */}
                <div className="relative shrink-0 mx-1">
                    <ArrowRight className={cn(
                        "w-5 h-5",
                        isRemoved ? "opacity-30" : "opacity-60"
                    )} />
                    {isRemoved && (
                        <div className="absolute inset-0 flex items-center justify-center">
                            <div className="w-6 h-[1.5px] bg-red-500/50 rotate-45" />
                        </div>
                    )}
                </div>

                {/* Target node with icon */}
                <div className="flex items-center gap-1 min-w-0">
                    {targetIconHtml ? (
                        <SerializedIcon html={targetIconHtml} iconColor={targetDef?.iconColor || ''} className="w-3 h-3 shrink-0 opacity-60" />
                    ) : (
                        <Zap className="w-3 h-3 shrink-0 opacity-60" />
                    )}
                    <span className="truncate max-w-[60px]">{state.targetLabel}</span>
                </div>
            </div>
        </div>
    );
});

EdgeCard.displayName = 'EdgeCard';

// Error display
const ErrorCard = memo(({ error }: { error: string }) => (
    <div
        className="w-full max-w-[260px] rounded-xl border border-red-500/20 bg-red-500/[0.04] overflow-hidden flex"
    >
        <div className="w-12 shrink-0 flex items-center justify-center bg-red-500/[0.04] border-r border-red-500/10">
            <AlertCircle className="w-6 h-6 text-red-600/70 dark:text-red-400/70" />
        </div>
        <div className="flex-1 min-w-0 flex items-center px-3 h-12">
            <span className="text-[13px] text-red-600/80 dark:text-red-400/80 truncate">{error}</span>
        </div>
    </div>
));

ErrorCard.displayName = 'ErrorCard';

// Completion placeholder when workflow edit finishes with no visual changes
const CompletionPlaceholder = memo(() => (
    <div className="flex items-center gap-2 py-2 text-muted-foreground dark:text-white/60">
        <CheckCircle2 className="w-4 h-4 text-emerald-500/80" />
        <span className="text-sm">Workflow updated</span>
    </div>
));

CompletionPlaceholder.displayName = 'CompletionPlaceholder';

// Main component
export const WorkflowEditEventView = memo(({ events, isComplete, workflowId }: WorkflowEditEventViewProps) => {
    const { nodes: nodeStates, edges: edgeStates } = useMemo(() => consolidateEvents(events), [events]);

    const errorEvent = useMemo(() => events.find(e => e.type === 'error'), [events]);

    const hasContent = nodeStates.length > 0 || edgeStates.length > 0;

    // Show loading state when editing starts but no events yet
    if (!hasContent && !isComplete && !errorEvent) {
        return (
            <div className="flex items-center gap-2 py-2">
                <ThinkingOrb state="weaving" aria-label="Editing workflow" />
                <span className="text-sm text-muted-foreground dark:text-white/60">Editing workflow...</span>
            </div>
        );
    }

    // Show error if present
    if (errorEvent?.error) {
        return <ErrorCard error={errorEvent.error} />;
    }

    // Show placeholder if complete but no visual content
    if (!hasContent && isComplete) {
        return <CompletionPlaceholder />;
    }

    // Nothing to show
    if (!hasContent) {
        return null;
    }

    return (
        <div className="flex flex-col gap-2 py-1">
            {nodeStates.map((state) => (
                <NodeCard key={state.nodeId} state={state} workflowId={workflowId} />
            ))}
            {edgeStates.map((state) => (
                <EdgeCard key={state.edgeId} state={state} workflowId={workflowId} />
            ))}
        </div>
    );
});

WorkflowEditEventView.displayName = 'WorkflowEditEventView';

export default WorkflowEditEventView;
