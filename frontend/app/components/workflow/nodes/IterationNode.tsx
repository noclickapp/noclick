// Iteration node for looping over arrays in workflows.
// This is a control flow node that executes connected nodes once per item in an array.
// Has two output handles:
//   - "loop" (right-bottom): connects to body nodes that execute per-item
//   - "output" (right-top): connects to nodes that receive aggregated results after all iterations
//
// Transitive Loop Body Propagation:
//   ALL nodes downstream from the loop handle execute per iteration with access to loop variables.
//   Example: iteration (loop) → A → B → C
//   - Nodes A, B, and C all execute 3 times for 3 items
//   - No need to connect iteration node to every node in the chain
//   - Reduces edge clutter in complex workflows
//
// Includes display strategy for how iteration output appears in helper panels.

import React, { memo, useState, useRef, useEffect, useCallback } from 'react';
import { NodeProps, Handle, Position, useStore } from '@xyflow/react';
import { Repeat, GripVertical, Ban } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
import { useDraggable } from '@dnd-kit/core';
import {
    useReferenceHover,
    isPathHighlighted,
    shouldScrollToPath,
} from '../ReferenceHoverContext';
import { NodeSpinner } from './base/NodeSpinner';
import { perfState } from '~/lib/perf-state';
import type {
    NodeDefinition,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    JsonObject,
    ReferenceSuggestion,
} from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Iteration Output Type Helpers
// ============================================================================

interface IterationOutputShape {
    isIterationNode: true;
    item?: JsonValue;
    items?: JsonValue[];
    headers?: string[];
    index?: number;
    total?: number;
    row_number?: number;
    // Aggregated output fields (available after iteration completes)
    collected_results?: JsonValue[];
    completed?: boolean;
    results?: JsonValue[];
}

function asIterationOutput(output: JsonValue): IterationOutputShape {
    return output as unknown as IterationOutputShape;
}

function getValueType(value: JsonValue): ReferenceSuggestion['valueType'] {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'object';
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    return 'string';
}

// ============================================================================
// Display Strategy Implementation
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    // Guard against null/undefined or non-object output
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return [];
    }

    const suggestions: ReferenceSuggestion[] = [];
    const iterOutput = asIterationOutput(output);

    // Get item - use first item from items array if item not directly provided
    const item = iterOutput.item ?? iterOutput.items?.[0];

    // Get headers - derive from item keys if not explicitly provided
    const derivedHeaders =
        item && typeof item === 'object' && !Array.isArray(item)
            ? Object.keys(item as JsonObject)
            : undefined;
    const headers = iterOutput.headers || derivedHeaders;

    const index = iterOutput.index ?? 0;
    const total = iterOutput.total ?? iterOutput.items?.length ?? 0;
    const rowNumber = iterOutput.row_number ?? (iterOutput.headers ? 2 : 1);

    // Add item fields if item is an object with headers
    if (item && typeof item === 'object' && !Array.isArray(item) && headers) {
        const itemObj = item as JsonObject;
        for (const header of headers) {
            if (header in itemObj) {
                const value = itemObj[header];
                suggestions.push({
                    reference: `${nodeId}.item.${header}`,
                    label: `item.${header}`,
                    nodeId,
                    path: `item.${header}`,
                    valueType: getValueType(value),
                    value,
                    depth: 1,
                });
            }
        }
    } else if (item !== undefined && item !== null) {
        // Item is not an object, show as single variable
        suggestions.push({
            reference: `${nodeId}.item`,
            label: 'item',
            nodeId,
            path: 'item',
            valueType: getValueType(item),
            value: item,
            depth: 0,
        });
    }

    // Add utility variables
    suggestions.push({
        reference: `${nodeId}.index`,
        label: 'index',
        nodeId,
        path: 'index',
        valueType: 'number',
        value: index,
        depth: 0,
    });

    suggestions.push({
        reference: `${nodeId}.row_number`,
        label: 'row_number (for sheet addressing)',
        nodeId,
        path: 'row_number',
        valueType: 'number',
        value: rowNumber,
        depth: 0,
    });

    suggestions.push({
        reference: `${nodeId}.total`,
        label: 'total',
        nodeId,
        path: 'total',
        valueType: 'number',
        value: total,
        depth: 0,
    });

    // ========== OUTPUT VARIABLES (for post-iteration nodes) ==========
    const collectedResults = iterOutput.collected_results;
    const completed = iterOutput.completed;

    if (collectedResults !== undefined) {
        suggestions.push({
            reference: `${nodeId}.collected_results`,
            label: 'collected_results (aggregated outputs)',
            nodeId,
            path: 'collected_results',
            valueType: 'array',
            value: collectedResults,
            depth: 0,
        });
    }

    if (completed !== undefined) {
        suggestions.push({
            reference: `${nodeId}.completed`,
            label: 'completed',
            nodeId,
            path: 'completed',
            valueType: 'boolean',
            value: completed,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    // Guard against null/undefined or non-object output
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return { valid: false, error: 'No iteration output available' };
    }

    const iterOutput = asIterationOutput(output);

    // Get item - use first item from items array if item not directly provided
    const item = iterOutput.item ?? iterOutput.items?.[0];
    const derivedHeaders =
        item && typeof item === 'object' && !Array.isArray(item)
            ? Object.keys(item as JsonObject)
            : undefined;
    const validHeaders = iterOutput.headers || derivedHeaders || [];

    // Check for index, row_number, total, collected_results, and completed
    if (
        path === 'index' ||
        path === 'row_number' ||
        path === 'total' ||
        path === 'collected_results' ||
        path === 'completed'
    ) {
        return { valid: true };
    }

    // Check for item or item.fieldName
    if (path === 'item') {
        return item !== undefined
            ? { valid: true }
            : { valid: false, error: 'No item data available' };
    }

    if (path.startsWith('item.')) {
        const fieldName = path.slice(5); // Remove "item."
        if (item && typeof item === 'object' && !Array.isArray(item)) {
            const itemObj = item as JsonObject;
            if (fieldName in itemObj || validHeaders.includes(fieldName)) {
                return { valid: true };
            }
            return {
                valid: false,
                error: `Field "${fieldName}" not found in item. Available: ${validHeaders.join(', ')}`,
            };
        }
        return { valid: false, error: 'Item is not an object with fields' };
    }

    return {
        valid: false,
        error: `Unknown iteration variable "${path}". Use item.fieldName, index, row_number, or total`,
    };
}

// Display variable structure for internal use
interface DisplayVariable {
    path: string;
    label: string;
    value: JsonValue;
    type: string;
}

interface DisplayVariables {
    loop: DisplayVariable[]; // Variables for body nodes (per-item)
    output: DisplayVariable[]; // Variables for post-iteration nodes (aggregated)
}

function getDisplayVariables(output: JsonValue): DisplayVariables {
    const result: DisplayVariables = { loop: [], output: [] };

    // Guard against null/undefined or non-object output
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return result;
    }

    const iterOutput = asIterationOutput(output);

    // ========== LOOP VARIABLES (for body nodes) ==========
    // Get item - use first item from items array if item not directly provided
    const item = iterOutput.item ?? iterOutput.items?.[0];
    const derivedHeaders =
        item && typeof item === 'object' && !Array.isArray(item)
            ? Object.keys(item as JsonObject)
            : undefined;
    const headers = iterOutput.headers || derivedHeaders;

    const index = iterOutput.index ?? 0;
    const total = iterOutput.total ?? iterOutput.items?.length ?? 0;
    const rowNumber = iterOutput.row_number ?? (iterOutput.headers ? 2 : 1);

    // Add item fields if item is an object
    if (item && typeof item === 'object' && !Array.isArray(item) && headers) {
        const itemObj = item as JsonObject;
        for (const header of headers) {
            if (header in itemObj) {
                const value = itemObj[header];
                result.loop.push({
                    path: `item.${header}`,
                    label: header,
                    value: value,
                    type: value === null ? 'null' : typeof value,
                });
            }
        }
    } else if (item !== undefined && item !== null) {
        // Item is not an object with headers, show as single variable
        result.loop.push({
            path: 'item',
            label: 'item',
            value: item,
            type:
                item === null
                    ? 'null'
                    : Array.isArray(item)
                      ? 'array'
                      : typeof item,
        });
    }

    // Add utility variables for iteration control and sheet addressing
    result.loop.push({
        path: 'index',
        label: 'index',
        value: index,
        type: 'number',
    });
    result.loop.push({
        path: 'row_number',
        label: 'row_number',
        value: rowNumber,
        type: 'number',
    });
    result.loop.push({
        path: 'total',
        label: 'total',
        value: total,
        type: 'number',
    });

    // ========== OUTPUT VARIABLES (for post-iteration nodes) ==========
    // These are available after all iterations complete
    const collectedResults = iterOutput.collected_results;
    const completed = iterOutput.completed;

    if (collectedResults !== undefined) {
        result.output.push({
            path: 'collected_results',
            label: 'collected_results',
            value: collectedResults,
            type: 'array',
        });
    }

    result.output.push({
        path: 'total',
        label: 'total',
        value: total,
        type: 'number',
    });

    if (completed !== undefined) {
        result.output.push({
            path: 'completed',
            label: 'completed',
            value: completed,
            type: 'boolean',
        });
    }

    return result;
}

// ============================================================================
// Output Panel Content Component
// ============================================================================

// Single variable row — styled to match the Fields (suggested refs) cards so
// the iteration panel reads consistently with the rest of the I/O panel.
const IterationVariableRow = ({
    nodeId,
    path,
    label,
    value,
    draggable = true,
}: {
    nodeId: string;
    path: string;
    label: string;
    value: JsonValue;
    draggable?: boolean;
}) => {
    const formatValue = (val: JsonValue): string => {
        if (val === null) return 'null';
        if (typeof val === 'string')
            return val.length > 60 ? `${val.slice(0, 60)}…` : val;
        if (Array.isArray(val))
            return `[${val.length} item${val.length === 1 ? '' : 's'}]`;
        if (typeof val === 'object')
            return `{${Object.keys(val).length} fields}`;
        return String(val);
    };

    const dragId = `iteration-var-${nodeId}-${path}`;
    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: dragId,
        data: {
            type: 'json-field-reference',
            nodeId,
            path,
            value,
            displayValue: formatValue(value),
        },
        disabled: !draggable,
    });

    // Highlight + scroll-to when a matching {{nodeId.path}} reference is hovered
    // or clicked in a config field — same behavior as the JSON input tree.
    const refHover = useReferenceHover();
    const isHighlighted =
        !!refHover &&
        (isPathHighlighted(refHover.hoveredReference, nodeId, path) ||
            isPathHighlighted(refHover.scrollToReference, nodeId, path));
    const shouldScrollTo =
        !!refHover &&
        shouldScrollToPath(refHover.scrollToReference, nodeId, path);
    const rowRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
        if (shouldScrollTo && rowRef.current) {
            rowRef.current.scrollIntoView({
                behavior: 'smooth',
                block: 'center',
            });
        }
    }, [shouldScrollTo]);
    const combinedRef = useCallback(
        (node: HTMLDivElement | null) => {
            if (draggable) setNodeRef(node);
            rowRef.current = node;
        },
        [draggable, setNodeRef]
    );

    return (
        <div
            ref={combinedRef}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            style={{
                opacity: isDragging ? 0.5 : 1,
                cursor: draggable
                    ? isDragging
                        ? 'grabbing'
                        : 'grab'
                    : 'default',
            }}
            className={`group flex items-start gap-2 px-2 py-1.5 rounded-md border transition-all ${
                isHighlighted
                    ? 'bg-foreground/[0.10] border-foreground/30 ring-1 ring-inset ring-foreground/40'
                    : 'bg-foreground/[0.02] hover:bg-foreground/[0.05] border-border/40 dark:border-white/[0.04] hover:border-border dark:hover:border-white/[0.1]'
            }`}
        >
            {draggable && (
                <GripVertical className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-600 group-hover:text-muted-foreground mt-0.5 flex-shrink-0 transition-colors" />
            )}
            <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-foreground truncate">
                    {label}
                </div>
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 mt-0.5 line-clamp-2 font-mono">
                    {formatValue(value)}
                </div>
            </div>
        </div>
    );
};

// Small handle indicator component showing which node handle this tab corresponds to
const HandleIndicator = ({ position }: { position: 'top' | 'bottom' }) => (
    <div className="flex items-center gap-1 text-[9px] text-muted-foreground/70 dark:text-zinc-600">
        <svg width="24" height="16" viewBox="0 0 24 16" className="opacity-60">
            {/* Mini node representation */}
            <rect
                x="2"
                y="2"
                width="12"
                height="12"
                rx="2"
                fill="none"
                stroke="currentColor"
                strokeWidth="1"
            />
            {/* Handle dot */}
            <circle
                cx="16"
                cy={position === 'top' ? 5 : 11}
                r="2"
                fill="currentColor"
            />
            {/* Arrow pointing right */}
            <path
                d={`M18 ${position === 'top' ? 5 : 11} L22 ${position === 'top' ? 5 : 11}`}
                stroke="currentColor"
                strokeWidth="1"
            />
        </svg>
    </div>
);

// Custom panel content for iteration nodes - shows loop and output variables in tabs
const IterationOutputPanelContent = ({
    nodeId,
    output,
    draggable = true,
    sourceHandle,
    nodeData,
}: OutputPanelContentProps) => {
    // Determine initial tab based on source handle
    // 'done' handle → Output tab, 'loop' handle or undefined → Loop tab
    const getInitialTab = (): 'loop' | 'output' => {
        if (sourceHandle === 'done' || sourceHandle === 'output')
            return 'output';
        return 'loop';
    };
    const [activeTab, setActiveTab] = useState<'loop' | 'output'>(
        getInitialTab
    );
    // Before the loop has run there's no real output; fall back to the clipped
    // per-item previewOutput seeded by "Loop over each item" so users can still
    // drag {{id.item.*}} fields. A real run's output takes precedence.
    const effectiveOutput =
        output ?? (nodeData?.previewOutput as JsonValue | undefined) ?? null;
    const variables = getDisplayVariables(effectiveOutput);

    const hasLoopVars = variables.loop.length > 0;
    const hasOutputVars = variables.output.length > 0;

    // Check if iteration has completed (for auto-switching)
    const iterOutput =
        output && typeof output === 'object' && !Array.isArray(output)
            ? (output as { completed?: boolean })
            : null;
    const isCompleted = iterOutput?.completed === true;

    // Sync tab when sourceHandle changes (e.g., different connection selected)
    const prevSourceHandleRef = useRef(sourceHandle);
    useEffect(() => {
        if (sourceHandle !== prevSourceHandleRef.current) {
            setActiveTab(getInitialTab());
            prevSourceHandleRef.current = sourceHandle;
        }
    }, [sourceHandle]);

    // Auto-switch to output tab when iteration completes
    const prevCompletedRef = useRef(isCompleted);
    useEffect(() => {
        if (isCompleted && !prevCompletedRef.current) {
            setActiveTab('output');
        }
        prevCompletedRef.current = isCompleted;
    }, [isCompleted]);

    if (!hasLoopVars && !hasOutputVars) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No iteration variables available. Run the workflow to see
                variables.
            </div>
        );
    }

    const activeVariables =
        activeTab === 'loop' ? variables.loop : variables.output;

    return (
        <div className="space-y-2">
            {/* Compact tab bar */}
            <div className="flex items-center gap-1 p-0.5 bg-muted dark:bg-zinc-900/50 rounded-md">
                <button
                    onClick={() => setActiveTab('loop')}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 text-[11px] font-medium rounded transition-all ${
                        activeTab === 'loop'
                            ? 'bg-accent dark:bg-zinc-700/80 text-foreground'
                            : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-accent/50 dark:hover:bg-zinc-800/30'
                    }`}
                    title="Per-item variables — use with loop handle (↘ bottom-right)"
                >
                    <span
                        className={`text-[9px] ${activeTab === 'loop' ? 'text-muted-foreground' : 'text-muted-foreground/70 dark:text-zinc-600'}`}
                    >
                        ↘
                    </span>
                    <span>Loop</span>
                    <span
                        className={`min-w-[14px] text-center px-1 rounded text-[9px] ${
                            activeTab === 'loop'
                                ? 'bg-muted-foreground/30 dark:bg-zinc-600 text-foreground'
                                : 'bg-muted dark:bg-zinc-800/60 text-muted-foreground dark:text-zinc-500'
                        }`}
                    >
                        {variables.loop.length}
                    </span>
                </button>
                <button
                    onClick={() => setActiveTab('output')}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-2 py-1 text-[11px] font-medium rounded transition-all ${
                        activeTab === 'output'
                            ? 'bg-accent dark:bg-zinc-700/80 text-foreground'
                            : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-accent/50 dark:hover:bg-zinc-800/30'
                    }`}
                    title="Aggregated results — use with output handle (↗ top-right)"
                >
                    <span
                        className={`text-[9px] ${activeTab === 'output' ? 'text-muted-foreground' : 'text-muted-foreground/70 dark:text-zinc-600'}`}
                    >
                        ↗
                    </span>
                    <span>Output</span>
                    <span
                        className={`min-w-[14px] text-center px-1 rounded text-[9px] ${
                            activeTab === 'output'
                                ? 'bg-muted-foreground/30 dark:bg-zinc-600 text-foreground'
                                : 'bg-muted dark:bg-zinc-800/60 text-muted-foreground dark:text-zinc-500'
                        }`}
                    >
                        {variables.output.length}
                    </span>
                    {isCompleted && (
                        <span
                            className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0"
                            title="Iteration complete"
                        />
                    )}
                </button>
            </div>

            {/* Variables list */}
            {activeVariables.length > 0 ? (
                <div className="space-y-1">
                    {activeVariables.map((variable) => (
                        <IterationVariableRow
                            key={variable.path}
                            nodeId={nodeId}
                            path={variable.path}
                            label={variable.label}
                            value={variable.value}
                            draggable={draggable}
                        />
                    ))}
                </div>
            ) : (
                <div className="p-3 rounded-lg bg-muted/50 dark:bg-zinc-900/50 border border-border/50 dark:border-zinc-800/50">
                    <p className="text-xs text-muted-foreground dark:text-zinc-500 text-center">
                        {activeTab === 'output'
                            ? 'Run the workflow to see aggregated results'
                            : 'No loop variables available'}
                    </p>
                </div>
            )}
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

export const iterationDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    // Loop/Output tabs expose the real per-item ({{item.*}}, index, total) and
    // aggregated-result refs. Previously body nodes got these via the implicit
    // LOOP tab in IODataDisplay; that tab is gone, so wire the dedicated panel.
    OutputPanelContent: IterationOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

// Custom iteration node component with two output handles on the right:
// - "output" (right-top): nodes that receive aggregated results after all iterations
// - "loop" (right-bottom): body nodes that execute per-item, last body node loops back to input
// Determinate progress ring for iteration nodes.
// Shows a filling arc based on completed/total instead of an indeterminate spinner.
const progressRingStyles = `
@keyframes iter-ring-pulse {
    0%, 100% { stroke-width: 4.5; opacity: 0.85; }
    50% { stroke-width: 7; opacity: 1; }
}
`;

const ProgressRing = ({
    completed,
    total,
    radius = 28,
}: {
    completed: number;
    total: number;
    radius?: number;
}) => {
    const diameter = radius * 2;
    const fraction = total > 0 ? completed / total : 0;
    const circumference = 2 * Math.PI * 45; // r=45 in viewBox 0 0 100 100
    const dashOffset = circumference * (1 - fraction);

    return (
        <>
            <style>{progressRingStyles}</style>
            <svg
                className="absolute pointer-events-none"
                width={diameter}
                height={diameter}
                viewBox="0 0 100 100"
                style={{
                    left: '50%',
                    top: '50%',
                    transform: 'translate(-50%, -50%)',
                }}
            >
                {/* Background track */}
                <circle
                    cx="50"
                    cy="50"
                    r="45"
                    fill="none"
                    strokeWidth="4.5"
                    style={{ stroke: 'hsl(var(--foreground))' }}
                    opacity="0.12"
                />
                {/* Progress arc — pulses thickness to indicate activity */}
                <circle
                    cx="50"
                    cy="50"
                    r="45"
                    fill="none"
                    stroke="rgba(168, 85, 247, 0.85)"
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    strokeDashoffset={dashOffset}
                    style={{
                        transform: 'rotate(-90deg)',
                        transformOrigin: '50% 50%',
                        transition: 'stroke-dashoffset 0.3s ease-out',
                        animation: 'iter-ring-pulse 1.5s ease-in-out infinite',
                    }}
                />
            </svg>
        </>
    );
};

const IterationNodeComponent = ({ id, data, selected, type }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false;
    const hasMockedOutput = data?.mockedOutput != null;
    const isReadOnly = data?.isReadOnly === true;

    // Extract iteration progress from output.
    // Don't gate on isRunning — executionState can lag behind output events due to valtio batching.
    // Instead gate on !== 'idle': workflow:complete resets all nodes to 'idle', clearing stale progress.
    // During execution, the valtio race may leave state at 'completed' (not 'idle'), so the ring still shows.
    const output = data?.output as
        | { completed?: number; total?: number }
        | undefined;
    const completed = output?.completed;
    const total = output?.total;
    const hasProgress =
        executionState !== 'idle' &&
        typeof completed === 'number' &&
        typeof total === 'number' &&
        total > 0;
    const progressCompleted = typeof completed === 'number' ? completed : 0;
    const progressTotal = typeof total === 'number' ? total : 0;

    // Check if an edge is being dragged from this node - hide labels during drag
    const isConnecting = useStore(
        (state) =>
            state.connection.inProgress && state.connection.fromNode?.id === id
    );

    return (
        <div className="relative" style={{ width: 90, height: 90 }}>
            {/* Input Handle (left) - receives array to iterate AND loop-back from body */}
            <Handle
                type="target"
                position={Position.Left}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: 45, zIndex: 10 }}
            />

            {/* Output Handle (right-top) - connects to post-iteration nodes */}
            {/* At 30% of visual node height (90 * 0.3 = 27px) */}
            <Handle
                id="done"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: 27, zIndex: 10 }}
                title="Output - aggregated results after all iterations"
            />
            {/* Output handle label - hidden when dragging edge */}
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-foreground/80 pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -48,
                        top: 27,
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    output
                </div>
            )}

            {/* Loop Handle (right-bottom) - connects to body nodes */}
            {/* At 70% of visual node height (90 * 0.7 = 63px) */}
            <Handle
                id="loop"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: 63, zIndex: 10 }}
                title="Loop body - executes per item"
            />
            {/* Loop handle label - hidden when dragging edge */}
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-foreground/80 pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -38,
                        top: 63,
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    loop
                </div>
            )}

            {/* Error Badge */}
            {isError && <NodeStatusBadge variant="error" />}

            {/* Config Status Badge */}
            {!isError && !isDisabled && !configValid && (
                <NodeStatusBadge variant="incomplete" />
            )}

            {/* Main Container - fixed height, label sits below */}
            <div
                className={`
                    group relative w-full rounded-2xl overflow-hidden
                    flex flex-col items-center justify-center
                    ${isRunning || shouldOptimize ? 'transition-none' : 'transition-all duration-500 ease-out'}
                    bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]
                    ${
                        selected
                            ? 'border-2 border-primary dark:border-foreground shadow-2xl shadow-primary/20 dark:shadow-foreground/20 scale-105'
                            : isRunning
                              ? 'border-2 border-foreground/60 shadow-lg shadow-foreground/10'
                              : isError
                                ? 'border-2 border-red-500/60 shadow-lg shadow-red-500/20'
                                : !configValid
                                  ? 'border-2 border-amber-500/50 shadow-lg shadow-amber-500/15'
                                  : 'border border-border dark:border-zinc-700/40 shadow-lg hover:shadow-2xl hover:border-foreground/30 hover:shadow-foreground/10'
                    }
                `}
                style={{
                    height: 90,
                    // Mock-state dim suppressed in read-only surfaces — see AutomationNode.
                    opacity: hasMockedOutput && !isReadOnly ? 0.65 : 1,
                }}
            >
                {/* Background gradient */}
                <div
                    className={`absolute inset-0 opacity-0 dark:opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'dark:opacity-60' : 'dark:group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(168, 85, 247, 0.15), transparent 50%)',
                    }}
                />

                {/* Glass overlay */}
                <div
                    className={`absolute inset-0 rounded-[14px] bg-gradient-to-br from-white/[0.08] via-transparent to-transparent pointer-events-none opacity-0 dark:opacity-100 ${shouldOptimize ? '' : 'dark:backdrop-blur-[2px]'}`}
                />

                {/* Inner glow */}
                <div
                    className={`absolute inset-0 bg-gradient-radial from-white/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-0 dark:opacity-100' : 'opacity-0 dark:group-hover:opacity-70'}`}
                />

                {/* Shimmer effect */}
                <div className="absolute inset-0 rounded-2xl overflow-hidden pointer-events-none">
                    <div
                        className="absolute inset-0 opacity-0 group-hover:opacity-70 transition-opacity duration-500"
                        style={{
                            background:
                                'linear-gradient(110deg, transparent 0%, transparent 35%, rgba(255, 255, 255, 0.06) 45%, rgba(255, 255, 255, 0.09) 50%, rgba(255, 255, 255, 0.06) 55%, transparent 65%, transparent 100%)',
                            transform: 'translateX(-100%)',
                            animation:
                                'shimmer-sweep 2.5s ease-in-out infinite',
                            filter: 'blur(10px)',
                        }}
                    />
                </div>

                {/* Icon + progress/mock label */}
                <div
                    className={`flex flex-col items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                    style={{
                        transform: hasMockedOutput ? 'scale(0.7)' : 'scale(1)',
                    }}
                >
                    {/* Use determinate progress ring when we have progress data, otherwise indeterminate spinner */}
                    {hasProgress ? (
                        <div className="relative inline-flex items-center justify-center">
                            <div
                                className="relative z-10"
                                style={{ transform: 'scale(0.78)' }}
                            >
                                <Repeat
                                    className={`${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-purple-600 dark:text-purple-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                                    style={{
                                        width: 48,
                                        height: 48,
                                        filter: isDisabled
                                            ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                            : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                                    }}
                                />
                            </div>
                            <ProgressRing
                                completed={progressCompleted}
                                total={progressTotal}
                                radius={28}
                            />
                        </div>
                    ) : (
                        <NodeSpinner isLoading={isRunning} spinnerRadius={28}>
                            <Repeat
                                className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-purple-600 dark:text-purple-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                                style={{
                                    width: 48,
                                    height: 48,
                                    filter: isDisabled
                                        ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                        : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                                }}
                            />
                        </NodeSpinner>
                    )}
                    {hasMockedOutput && (
                        <div className="text-[18px] font-bold tracking-widest text-foreground mt-0.5 dark:[text-shadow:0_2px_6px_rgba(0,0,0,0.9)]">
                            MOCK
                        </div>
                    )}
                </div>

                {/* Disabled Overlay */}
                {isDisabled && (
                    <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                        <Ban
                            className="text-muted-foreground dark:text-zinc-500 opacity-50"
                            style={{ width: 55, height: 55 }}
                        />
                    </div>
                )}

                {/* Progress count — bottom-right inside the node */}
                {hasProgress && (
                    <div className="absolute bottom-1.5 right-2 z-20 pointer-events-none">
                        <span className="text-[10px] font-semibold tabular-nums text-purple-700 dark:text-purple-300 dark:[text-shadow:0_1px_4px_rgba(0,0,0,0.8)]">
                            {progressCompleted}/{progressTotal}
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
};

export const IterationNode: NodeDefinition = {
    type: 'iteration',
    label: 'Iteration',
    description: 'Loop over items',
    Icon: Repeat,
    iconColor: 'text-purple-600 dark:text-purple-400',
    dimensions: DIMENSIONS,
    component: memo(IterationNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput &&
            prev.data?.label === next.data?.label &&
            (prev.data?.output as any)?.completed ===
                (next.data?.output as any)?.completed &&
            (prev.data?.output as any)?.total ===
                (next.data?.output as any)?.total
        );
    }),
    displayStrategy: iterationDisplayStrategy,
    skipAutoMemo: true,
};
