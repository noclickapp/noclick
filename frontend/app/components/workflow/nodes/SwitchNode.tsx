// Switch node for multi-way workflow branching based on value matching.
// Dynamically renders output handles based on configured switch cases.
// Node height grows as more cases are added.

import React, { memo, useMemo, useEffect, useRef } from 'react';
import {
    NodeProps,
    Handle,
    Position,
    useStore,
    useUpdateNodeInternals,
} from '@xyflow/react';
import { GitFork, GripVertical, Ban } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
import { useDraggable } from '@dnd-kit/core';
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

const BASE_HEIGHT = 90;
const PER_HANDLE_HEIGHT = 30;
const MIN_HANDLES = 2; // default + at least conceptual minimum

// ============================================================================
// Helpers
// ============================================================================

interface SwitchCase {
    value: string;
}

function getSwitchCases(data: any): SwitchCase[] {
    const cases = data?.config?.switch_cases;
    if (Array.isArray(cases)) return cases;
    return [];
}

interface SwitchOutputShape {
    status: 'success' | 'error' | 'skipped';
    operation: 'switch';
    output_handle: string;
    matched_case?: string | null;
    data?: JsonValue;
    isConditionalNode: true;
    switch_value?: JsonValue;
    available_cases?: string[];
    reason?: string;
}

function asSwitchOutput(output: JsonValue): SwitchOutputShape | null {
    if (output === null || typeof output !== 'object' || Array.isArray(output))
        return null;
    const obj = output as JsonObject;
    if (!('isConditionalNode' in obj) || obj.operation !== 'switch')
        return null;
    return output as unknown as SwitchOutputShape;
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
// Display Strategy
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    const switchOutput = asSwitchOutput(output);
    if (!switchOutput || switchOutput.status !== 'success') return [];

    const suggestions: ReferenceSuggestion[] = [];

    if (switchOutput.data !== undefined) {
        suggestions.push({
            reference: `${nodeId}.data`,
            label: 'data',
            nodeId,
            path: 'data',
            valueType: getValueType(switchOutput.data),
            value: switchOutput.data,
            depth: 0,
        });
    }

    suggestions.push({
        reference: `${nodeId}.output_handle`,
        label: 'output_handle',
        nodeId,
        path: 'output_handle',
        valueType: 'string',
        value: switchOutput.output_handle,
        depth: 0,
    });

    if (switchOutput.matched_case !== undefined) {
        suggestions.push({
            reference: `${nodeId}.matched_case`,
            label: 'matched_case',
            nodeId,
            path: 'matched_case',
            valueType: switchOutput.matched_case === null ? 'null' : 'string',
            value: switchOutput.matched_case,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const switchOutput = asSwitchOutput(output);
    if (!switchOutput)
        return { valid: false, error: 'No switch output available' };

    const validPaths = [
        'data',
        'output_handle',
        'matched_case',
        'status',
        'operation',
    ];
    if (validPaths.includes(path)) return { valid: true };
    if (path.startsWith('data.')) return { valid: true };

    return {
        valid: false,
        error: `Path "${path}" not available. Available: ${validPaths.join(', ')}`,
    };
}

// ============================================================================
// Output Panel
// ============================================================================

const SwitchVariableRow = ({
    nodeId,
    path,
    label,
    value,
    valueType,
    draggable = true,
}: {
    nodeId: string;
    path: string;
    label: string;
    value: JsonValue;
    valueType: string;
    draggable?: boolean;
}) => {
    const dragId = `switch-var-${nodeId}-${path}`;
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

    function formatValue(val: JsonValue): string {
        if (val === null) return 'null';
        if (typeof val === 'string')
            return val.length > 40 ? `"${val.slice(0, 40)}..."` : `"${val}"`;
        if (typeof val === 'boolean') return val ? 'true' : 'false';
        if (Array.isArray(val)) return `[${val.length} items]`;
        if (typeof val === 'object')
            return `{${Object.keys(val as JsonObject).length} keys}`;
        return String(val);
    }

    const typeColor =
        {
            string: 'text-emerald-600 dark:text-emerald-400 bg-emerald-400/10',
            number: 'text-blue-600 dark:text-blue-400 bg-blue-400/10',
            boolean: 'text-amber-600 dark:text-amber-400 bg-amber-400/10',
            object: 'text-purple-600 dark:text-purple-400 bg-purple-400/10',
            array: 'text-cyan-600 dark:text-cyan-400 bg-cyan-400/10',
            null: 'text-muted-foreground dark:text-zinc-500 bg-zinc-500/10',
        }[valueType] || 'text-muted-foreground bg-zinc-400/10';

    const typeLabel =
        {
            string: 'text',
            number: 'number',
            boolean: 'boolean',
            object: 'object',
            array: 'list',
            null: 'null',
        }[valueType] || valueType;

    return (
        <div
            ref={draggable ? setNodeRef : undefined}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-all ${
                draggable ? 'cursor-grab active:cursor-grabbing' : ''
            } ${
                isDragging
                    ? 'opacity-50 border-muted-foreground/50 dark:border-zinc-500/50 bg-zinc-500/10'
                    : 'border-border/50 dark:border-zinc-700/50 bg-muted/40 dark:bg-zinc-800/30 hover:border-border dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50'
            }`}
        >
            {draggable && (
                <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <code className="text-xs text-foreground font-medium">
                        {label}
                    </code>
                    <span
                        className={`text-[9px] px-1.5 py-0.5 rounded ${typeColor}`}
                    >
                        {typeLabel}
                    </span>
                </div>
                <div className="text-[10px] truncate font-mono mt-0.5 text-muted-foreground dark:text-zinc-500">
                    {formatValue(value)}
                </div>
            </div>
        </div>
    );
};

const SwitchOutputPanelContent = ({
    nodeId,
    output,
    draggable = true,
}: OutputPanelContentProps) => {
    const switchOutput = asSwitchOutput(output);

    if (!switchOutput) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No switch output available
            </div>
        );
    }

    if (switchOutput.status === 'error') {
        return (
            <div className="text-xs text-red-600 dark:text-red-400 py-2">
                Error during switch evaluation
            </div>
        );
    }

    if (switchOutput.status === 'skipped') {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                Skipped: {switchOutput.reason || 'Not on active branch'}
            </div>
        );
    }

    return (
        <div className="space-y-3">
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Branch Result
                </div>
                <div className="flex items-center gap-2 text-[10px]">
                    <span className="px-2 py-0.5 rounded font-medium bg-blue-500/20 text-blue-600 dark:text-blue-400">
                        {switchOutput.output_handle}
                    </span>
                    {switchOutput.matched_case && (
                        <span className="text-muted-foreground dark:text-zinc-500">
                            (matched: "{switchOutput.matched_case}")
                        </span>
                    )}
                </div>
            </div>

            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Available Variables
                </div>
                {switchOutput.data !== undefined && (
                    <SwitchVariableRow
                        nodeId={nodeId}
                        path="data"
                        label="data"
                        value={switchOutput.data}
                        valueType={getValueType(switchOutput.data)}
                        draggable={draggable}
                    />
                )}
                <SwitchVariableRow
                    nodeId={nodeId}
                    path="output_handle"
                    label="output_handle"
                    value={switchOutput.output_handle}
                    valueType="string"
                    draggable={draggable}
                />
                <SwitchVariableRow
                    nodeId={nodeId}
                    path="matched_case"
                    label="matched_case"
                    value={switchOutput.matched_case ?? null}
                    valueType={
                        switchOutput.matched_case === null ? 'null' : 'string'
                    }
                    draggable={draggable}
                />
            </div>
        </div>
    );
};

export const switchDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: SwitchOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const SwitchNodeComponent = ({ id, data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false;
    const hasMockedOutput = data?.mockedOutput != null;
    const isReadOnly = data?.isReadOnly === true;

    const isConnecting = useStore(
        (state) =>
            state.connection.inProgress && state.connection.fromNode?.id === id
    );

    const cases = useMemo(() => getSwitchCases(data), [data]);

    // Output handles: one per non-empty case, plus an always-present "default"
    // fallback handle (where unmatched values flow — mirrors the backend's
    // `output_handle = default_output or "default"`). Ensures a freshly dropped
    // switch has a wireable output. Skipped only if a case is literally named
    // "default" (that case handle already covers the fallback id).
    const handleEntries = useMemo(() => {
        const caseEntries = cases
            .filter((c) => c.value) // skip empty cases
            .map((c) => ({ id: c.value, label: c.value, isDefault: false }));
        if (caseEntries.some((e) => e.id === 'default')) return caseEntries;
        return [
            ...caseEntries,
            { id: 'default', label: 'default', isDefault: true },
        ];
    }, [cases]);

    const totalHandles = handleEntries.length;
    const nodeHeight = Math.max(
        BASE_HEIGHT,
        BASE_HEIGHT + (totalHandles - MIN_HANDLES) * PER_HANDLE_HEIGHT
    );

    // Force ReactFlow to recalculate handle positions and edge paths when handles change.
    // Runs on every render where handleKey changes (not initial mount).
    // Multiple updates at staggered delays ensure edges are correct after both
    // the node resize and any edge cleanup in FlowCanvas have settled.
    const updateNodeInternals = useUpdateNodeInternals();
    const handleKey = `${handleEntries.map((h) => h.id).join(',')}_${nodeHeight}`;
    const isInitialRender = useRef(true);
    useEffect(() => {
        if (isInitialRender.current) {
            isInitialRender.current = false;
            return;
        }
        // Fire multiple updates: one early for visual responsiveness,
        // one later to catch edge state changes from FlowCanvas cleanup
        const t1 = setTimeout(() => updateNodeInternals(id), 0);
        const t2 = setTimeout(() => updateNodeInternals(id), 100);
        return () => {
            clearTimeout(t1);
            clearTimeout(t2);
        };
    }, [handleKey, id, updateNodeInternals]);

    return (
        <div className="relative" style={{ width: 90, height: nodeHeight }}>
            {/* Input Handle */}
            <Handle
                type="target"
                position={Position.Left}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Output Handles - one per case plus the default fallback, evenly spaced using pixel positions */}
            {handleEntries.map((entry, index) => {
                const topPx =
                    totalHandles === 1
                        ? nodeHeight / 2
                        : nodeHeight * 0.15 +
                          (index / (totalHandles - 1)) * (nodeHeight * 0.7);

                return (
                    <React.Fragment key={entry.id}>
                        <Handle
                            id={entry.id}
                            type="source"
                            position={Position.Right}
                            className={`!w-4 !h-4 !border-2 transition-all opacity-70 hover:opacity-100 ${
                                entry.isDefault
                                    ? '!bg-zinc-400 dark:!bg-zinc-600 !border-dashed !border-zinc-300 dark:!border-zinc-400 hover:!bg-zinc-500'
                                    : '!bg-zinc-300 dark:!bg-zinc-400 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400'
                            }`}
                            style={{ top: topPx, zIndex: 10 }}
                            title={
                                entry.isDefault
                                    ? 'default (unmatched) branch'
                                    : `${entry.label} branch`
                            }
                        />
                        {!isConnecting && (
                            <div
                                className={`absolute text-[10px] pointer-events-none select-none px-1 py-px rounded bg-popover/95 whitespace-nowrap max-w-[60px] truncate ${
                                    entry.isDefault
                                        ? 'italic text-muted-foreground/70 dark:text-zinc-500'
                                        : 'font-medium text-muted-foreground'
                                }`}
                                style={{
                                    right: -68,
                                    top: topPx,
                                    transform: 'translateY(-50%)',
                                    zIndex: 5,
                                }}
                            >
                                {entry.label}
                            </div>
                        )}
                    </React.Fragment>
                );
            })}

            {/* Error Badge */}
            {isError && <NodeStatusBadge variant="error" />}

            {/* Config Status Badge */}
            {!isError && !isDisabled && !configValid && (
                <NodeStatusBadge variant="incomplete" />
            )}

            {/* Main Container */}
            <div
                className={`
                    group relative w-full h-full rounded-2xl overflow-hidden
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
                    // Mock-state dim suppressed in read-only surfaces — see AutomationNode.
                    opacity: hasMockedOutput && !isReadOnly ? 0.65 : 1,
                }}
            >
                <div
                    className={`absolute inset-0 opacity-0 dark:opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'dark:opacity-60' : 'dark:group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(59, 130, 246, 0.15), transparent 50%)',
                    }}
                />
                <div
                    className={`absolute inset-0 rounded-[14px] bg-gradient-to-br from-white/[0.08] via-transparent to-transparent pointer-events-none opacity-0 dark:opacity-100 ${shouldOptimize ? '' : 'dark:backdrop-blur-[2px]'}`}
                />
                <div
                    className={`absolute inset-0 bg-gradient-radial from-white/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-0 dark:opacity-100' : 'opacity-0 dark:group-hover:opacity-70'}`}
                />

                <div
                    className={`flex flex-col items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                    style={{
                        transform: hasMockedOutput ? 'scale(0.7)' : 'scale(1)',
                    }}
                >
                    <NodeSpinner isLoading={isRunning} spinnerRadius={28}>
                        <GitFork
                            className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-blue-600 dark:text-blue-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                            style={{
                                width: 48,
                                height: 48,
                                transform: 'rotate(90deg)',
                                filter: isDisabled
                                    ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                    : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                            }}
                        />
                    </NodeSpinner>
                    {hasMockedOutput && (
                        <div
                            className="text-[18px] font-bold tracking-widest text-foreground mt-0.5"
                            style={{
                                textShadow: '0 2px 6px rgba(0, 0, 0, 0.9)',
                            }}
                        >
                            MOCK
                        </div>
                    )}
                </div>

                {isDisabled && (
                    <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                        <Ban
                            className="text-muted-foreground dark:text-zinc-500 opacity-50"
                            style={{ width: 55, height: 55 }}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

export const SwitchNode: NodeDefinition = {
    type: 'switch',
    label: 'Switch',
    description: 'Multi-way branch',
    Icon: (props: any) => (
        <GitFork
            {...props}
            style={{ ...props.style, transform: 'rotate(90deg)' }}
        />
    ),
    iconColor: 'text-blue-600 dark:text-blue-400',
    dimensions: { width: 90, height: BASE_HEIGHT, iconSize: 48 },
    component: memo(SwitchNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput &&
            (prev.data?.config as any)?.switch_cases ===
                (next.data?.config as any)?.switch_cases
        );
    }),
    displayStrategy: switchDisplayStrategy,
    skipAutoMemo: true,
};
