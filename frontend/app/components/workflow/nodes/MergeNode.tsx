// Merge node for combining multiple data streams into one.
// This is a control flow node that waits for all inputs before merging.
// Has a single output handle that contains the merged data.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { GitFork, GripVertical } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import AutomationNode from './base/AutomationNode';
import type {
    NodeDefinition,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    JsonObject,
    JsonArray,
    ReferenceSuggestion,
} from './types';

const DIMENSIONS = { width: 110, height: 110, iconSize: 56 };

// ============================================================================
// Merge Output Type Helpers
// ============================================================================

interface MergeOutputShape {
    status: 'success' | 'error' | 'no_config';
    merged: JsonValue;
    count?: number;
    input_count?: number;
    total_input_items?: number;
    operation?: string;
    error?: string;
    isMergeNode?: true;
    // Operation-specific fields
    match_field?: string;
    dedupe_field?: string;
    conflict_resolution?: string;
    message?: string;
}

function asMergeOutput(output: JsonValue): MergeOutputShape | null {
    if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return null;
    }
    const obj = output as JsonObject;
    if (!('merged' in obj)) {
        return null;
    }
    return output as unknown as MergeOutputShape;
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

function buildSuggestions(output: JsonValue, nodeId: string): ReferenceSuggestion[] {
    const mergeOutput = asMergeOutput(output);
    if (!mergeOutput || mergeOutput.status !== 'success') return [];

    const suggestions: ReferenceSuggestion[] = [];

    // Add merged data
    suggestions.push({
        reference: `${nodeId}.merged`,
        label: 'merged',
        nodeId,
        path: 'merged',
        valueType: getValueType(mergeOutput.merged),
        value: mergeOutput.merged,
        depth: 0,
    });

    // Add count
    if (mergeOutput.count !== undefined) {
        suggestions.push({
            reference: `${nodeId}.count`,
            label: 'count',
            nodeId,
            path: 'count',
            valueType: 'number',
            value: mergeOutput.count,
            depth: 0,
        });
    }

    // Add input_count
    if (mergeOutput.input_count !== undefined) {
        suggestions.push({
            reference: `${nodeId}.input_count`,
            label: 'input_count',
            nodeId,
            path: 'input_count',
            valueType: 'number',
            value: mergeOutput.input_count,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(output: JsonValue, path: string): { valid: boolean; error?: string } {
    const mergeOutput = asMergeOutput(output);
    if (!mergeOutput) {
        return { valid: false, error: 'No merge output available' };
    }

    const validPaths = ['merged', 'count', 'input_count', 'total_input_items', 'operation', 'status'];
    if (validPaths.includes(path)) {
        return { valid: true };
    }

    // Allow nested merged access
    if (path.startsWith('merged.') || path.startsWith('merged[')) {
        return { valid: true };
    }

    return { valid: false, error: `Path "${path}" not available. Available: ${validPaths.join(', ')}` };
}

// ============================================================================
// Output Panel Content Component
// ============================================================================

const MergeVariableRow = ({
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
    const dragId = `merge-var-${nodeId}-${path}`;
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
        if (typeof val === 'string') return val.length > 40 ? `"${val.slice(0, 40)}..."` : `"${val}"`;
        if (Array.isArray(val)) return `[${val.length} items]`;
        if (typeof val === 'object') return `{${Object.keys(val as JsonObject).length} keys}`;
        return String(val);
    }

    const typeColor = {
        string: 'text-emerald-600 dark:text-emerald-400 bg-emerald-400/10',
        number: 'text-blue-600 dark:text-blue-400 bg-blue-400/10',
        boolean: 'text-amber-600 dark:text-amber-400 bg-amber-400/10',
        object: 'text-purple-600 dark:text-purple-400 bg-purple-400/10',
        array: 'text-cyan-600 dark:text-cyan-400 bg-cyan-400/10',
        null: 'text-muted-foreground dark:text-zinc-500 bg-zinc-500/10',
    }[valueType] || 'text-muted-foreground bg-zinc-400/10';

    const typeLabel = {
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
                    : 'border-border/50 dark:border-zinc-700/50 bg-muted/30 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50'
            }`}
        >
            {draggable && <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <code className="text-xs text-foreground font-medium">{label}</code>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${typeColor}`}>
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

const MergeOutputPanelContent = ({ nodeId, output, draggable = true }: OutputPanelContentProps) => {
    const mergeOutput = asMergeOutput(output);

    if (!mergeOutput) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No merge output available
            </div>
        );
    }

    if (mergeOutput.status === 'error') {
        return (
            <div className="text-xs text-red-600 dark:text-red-400 py-2">
                Error: {mergeOutput.error || 'Unknown error'}
            </div>
        );
    }

    if (mergeOutput.status === 'no_config') {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No configuration. Configure the merge operation in the node settings.
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {/* Merge Stats */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Merge Results
                </div>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    {mergeOutput.operation && (
                        <>
                            <span className="capitalize">{mergeOutput.operation.replace(/_/g, ' ')}</span>
                            <span className="text-muted-foreground/50 dark:text-zinc-700">•</span>
                        </>
                    )}
                    {mergeOutput.input_count !== undefined && (
                        <>
                            <span>{mergeOutput.input_count} inputs</span>
                            <span className="text-muted-foreground/50 dark:text-zinc-700">•</span>
                        </>
                    )}
                    {mergeOutput.count !== undefined && (
                        <span>{mergeOutput.count} items</span>
                    )}
                </div>
                {mergeOutput.total_input_items !== undefined && mergeOutput.count !== undefined && (
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500">
                        {mergeOutput.total_input_items} input items → {mergeOutput.count} merged
                    </div>
                )}
            </div>

            {/* Available Variables */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Available Variables
                </div>
                <MergeVariableRow
                    nodeId={nodeId}
                    path="merged"
                    label="merged"
                    value={mergeOutput.merged}
                    valueType={getValueType(mergeOutput.merged)}
                    draggable={draggable}
                />
                {mergeOutput.count !== undefined && (
                    <MergeVariableRow
                        nodeId={nodeId}
                        path="count"
                        label="count"
                        value={mergeOutput.count}
                        valueType="number"
                        draggable={draggable}
                    />
                )}
                {mergeOutput.input_count !== undefined && (
                    <MergeVariableRow
                        nodeId={nodeId}
                        path="input_count"
                        label="input_count"
                        value={mergeOutput.input_count}
                        valueType="number"
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

export const mergeDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: MergeOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

// Rotated GitFork icon (270° clockwise) - shows inputs converging to single output
const MergeIcon = (props: any) => <GitFork {...props} style={{ ...props.style, transform: 'rotate(270deg)' }} />;

const MergeNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={MergeIcon} iconColor="text-cyan-600 dark:text-cyan-400" />;
};

export const MergeNode: NodeDefinition = {
    type: 'merge',
    label: 'Merge',
    description: 'Combine data streams',
    Icon: MergeIcon,
    iconColor: 'text-cyan-600 dark:text-cyan-400',
    dimensions: DIMENSIONS,
    component: MergeNodeComponent,
    displayStrategy: mergeDisplayStrategy,
};
