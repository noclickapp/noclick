// Conditional node for workflow branching based on conditions.
// This is a control flow node that routes execution to different branches.
// Has multiple output handles: "true"/"false" for if_else, or dynamic handles for switch.

import React, { memo } from 'react';
import { NodeProps, Handle, Position, useStore } from '@xyflow/react';
import { Signpost, GripVertical, Ban } from 'lucide-react';
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

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Conditional Output Type Helpers
// ============================================================================

interface ConditionalOutputShape {
    status: 'success' | 'error' | 'skipped';
    operation: 'if_else';
    output_handle: string;
    condition_result?: boolean;
    data?: JsonValue;
    isConditionalNode: true;
    evaluated_field?: string;
    evaluated_value?: JsonValue;
    reason?: string;
}

function asConditionalOutput(output: JsonValue): ConditionalOutputShape | null {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return null;
    }
    const obj = output as JsonObject;
    if (!('isConditionalNode' in obj)) {
        return null;
    }
    return output as unknown as ConditionalOutputShape;
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
    const conditionalOutput = asConditionalOutput(output);
    if (!conditionalOutput || conditionalOutput.status !== 'success') return [];

    const suggestions: ReferenceSuggestion[] = [];

    // Add the data passed through
    if (conditionalOutput.data !== undefined) {
        suggestions.push({
            reference: `${nodeId}.data`,
            label: 'data',
            nodeId,
            path: 'data',
            valueType: getValueType(conditionalOutput.data),
            value: conditionalOutput.data,
            depth: 0,
        });
    }

    // Add output handle info
    suggestions.push({
        reference: `${nodeId}.output_handle`,
        label: 'output_handle',
        nodeId,
        path: 'output_handle',
        valueType: 'string',
        value: conditionalOutput.output_handle,
        depth: 0,
    });

    if (conditionalOutput.condition_result !== undefined) {
        suggestions.push({
            reference: `${nodeId}.condition_result`,
            label: 'condition_result',
            nodeId,
            path: 'condition_result',
            valueType: 'boolean',
            value: conditionalOutput.condition_result,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const conditionalOutput = asConditionalOutput(output);
    if (!conditionalOutput) {
        return { valid: false, error: 'No conditional output available' };
    }

    const validPaths = [
        'data',
        'output_handle',
        'condition_result',
        'status',
        'operation',
    ];
    if (validPaths.includes(path)) {
        return { valid: true };
    }

    // Allow nested data access
    if (path.startsWith('data.')) {
        return { valid: true };
    }

    return {
        valid: false,
        error: `Path "${path}" not available. Available: ${validPaths.join(', ')}`,
    };
}

// ============================================================================
// Output Panel Content Component
// ============================================================================

const ConditionalVariableRow = ({
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
    const dragId = `conditional-var-${nodeId}-${path}`;
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

const ConditionalOutputPanelContent = ({
    nodeId,
    output,
    draggable = true,
}: OutputPanelContentProps) => {
    const conditionalOutput = asConditionalOutput(output);

    if (!conditionalOutput) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No conditional output available
            </div>
        );
    }

    if (conditionalOutput.status === 'error') {
        return (
            <div className="text-xs text-red-600 dark:text-red-400 py-2">
                Error occurred during condition evaluation
            </div>
        );
    }

    if (conditionalOutput.status === 'skipped') {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                Skipped: {conditionalOutput.reason || 'Not on active branch'}
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {/* Branch Result */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Branch Result
                </div>
                <div className="flex items-center gap-2 text-[10px]">
                    <span
                        className={`px-2 py-0.5 rounded font-medium ${
                            conditionalOutput.output_handle === 'true'
                                ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                                : 'bg-red-500/20 text-red-600 dark:text-red-400'
                        }`}
                    >
                        {conditionalOutput.output_handle}
                    </span>
                    <span className="text-muted-foreground dark:text-zinc-500">
                        (condition:{' '}
                        {conditionalOutput.condition_result ? 'true' : 'false'})
                    </span>
                </div>
            </div>

            {/* Available Variables */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Available Variables
                </div>
                {conditionalOutput.data !== undefined && (
                    <ConditionalVariableRow
                        nodeId={nodeId}
                        path="data"
                        label="data"
                        value={conditionalOutput.data}
                        valueType={getValueType(conditionalOutput.data)}
                        draggable={draggable}
                    />
                )}
                <ConditionalVariableRow
                    nodeId={nodeId}
                    path="output_handle"
                    label="output_handle"
                    value={conditionalOutput.output_handle}
                    valueType="string"
                    draggable={draggable}
                />
                {conditionalOutput.condition_result !== undefined && (
                    <ConditionalVariableRow
                        nodeId={nodeId}
                        path="condition_result"
                        label="condition_result"
                        value={conditionalOutput.condition_result}
                        valueType="boolean"
                        draggable={draggable}
                    />
                )}
            </div>
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

export const conditionalDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: ConditionalOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

// Custom conditional node component with two output handles:
// - "true" (right-top): nodes that execute when condition is true
// - "false" (right-bottom): nodes that execute when condition is false
const ConditionalNodeComponent = ({ id, data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false;
    const hasMockedOutput = data?.mockedOutput != null;
    const isReadOnly = data?.isReadOnly === true;

    // Check if an edge is being dragged from this node
    const isConnecting = useStore(
        (state) =>
            state.connection.inProgress && state.connection.fromNode?.id === id
    );

    return (
        <div className="relative" style={{ width: 90, height: 90 }}>
            {/* Input Handle (left) */}
            <Handle
                type="target"
                position={Position.Left}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* True Handle (right-top) */}
            <Handle
                id="true"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: '30%', zIndex: 10 }}
                title="True branch - executes when condition is true"
            />
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-muted-foreground pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -38,
                        top: '30%',
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    true
                </div>
            )}

            {/* False Handle (right-bottom) */}
            <Handle
                id="false"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: '70%', zIndex: 10 }}
                title="False branch - executes when condition is false"
            />
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-muted-foreground pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -42,
                        top: '70%',
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    false
                </div>
            )}

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
                {/* Background gradient */}
                <div
                    className={`absolute inset-0 opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-60' : 'group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(251, 191, 36, 0.15), transparent 50%)',
                    }}
                />

                {/* Glass overlay */}
                <div
                    className={`absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.08] via-transparent to-transparent pointer-events-none ${shouldOptimize ? '' : 'backdrop-blur-[2px]'}`}
                />

                {/* Inner glow */}
                <div
                    className={`absolute inset-[1px] rounded-2xl bg-gradient-radial from-white/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-70'}`}
                />

                {/* Icon + MOCK label */}
                <div
                    className={`flex flex-col items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                    style={{
                        transform: hasMockedOutput ? 'scale(0.7)' : 'scale(1)',
                    }}
                >
                    <NodeSpinner isLoading={isRunning} spinnerRadius={28}>
                        <Signpost
                            className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-amber-600 dark:text-amber-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                            style={{
                                width: 48,
                                height: 48,
                                filter: isDisabled
                                    ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                    : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                            }}
                        />
                    </NodeSpinner>
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
            </div>
        </div>
    );
};

export const ConditionalNode: NodeDefinition = {
    type: 'conditional',
    label: 'Conditional',
    description: 'Branch workflow',
    Icon: Signpost,
    iconColor: 'text-amber-600 dark:text-amber-400',
    dimensions: DIMENSIONS,
    component: memo(ConditionalNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: conditionalDisplayStrategy,
    skipAutoMemo: true,
};
