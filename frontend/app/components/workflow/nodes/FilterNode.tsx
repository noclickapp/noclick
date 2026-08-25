// Filter node for data filtering and transformation in workflows.
// This is a control flow node that filters arrays/objects based on conditions.
// Includes display strategy for how filter output appears in helper panels.

import { memo } from 'react';
import { NodeProps } from '@xyflow/react';
import { Filter, GripVertical } from 'lucide-react';
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
// Filter Output Type Helpers
// ============================================================================

interface FilterOutputShape {
    status: 'success' | 'error' | 'no_config';
    filtered: JsonValue;
    count?: number;
    original_count?: number;
    operation?: string;
    error?: string;
    // Operation-specific fields
    duplicates_removed?: number;
    limit?: number;
    offset?: number;
    sort_field?: string;
    sort_order?: string;
    keys_count?: number;
    original_keys_count?: number;
}

function asFilterOutput(output: JsonValue): FilterOutputShape | null {
    if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return null;
    }
    const obj = output as JsonObject;
    if (!('filtered' in obj)) {
        return null;
    }
    return output as unknown as FilterOutputShape;
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
    const filterOutput = asFilterOutput(output);
    if (!filterOutput || filterOutput.status !== 'success') return [];

    const suggestions: ReferenceSuggestion[] = [];

    // Add filtered data
    suggestions.push({
        reference: `${nodeId}.filtered`,
        label: 'filtered',
        nodeId,
        path: 'filtered',
        valueType: getValueType(filterOutput.filtered),
        value: filterOutput.filtered,
        depth: 0,
    });

    // Add count
    if (filterOutput.count !== undefined) {
        suggestions.push({
            reference: `${nodeId}.count`,
            label: 'count',
            nodeId,
            path: 'count',
            valueType: 'number',
            value: filterOutput.count,
            depth: 0,
        });
    }

    // Add original_count
    if (filterOutput.original_count !== undefined) {
        suggestions.push({
            reference: `${nodeId}.original_count`,
            label: 'original_count',
            nodeId,
            path: 'original_count',
            valueType: 'number',
            value: filterOutput.original_count,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(output: JsonValue, path: string): { valid: boolean; error?: string } {
    const filterOutput = asFilterOutput(output);
    if (!filterOutput) {
        return { valid: false, error: 'No filter output available' };
    }

    const validPaths = ['filtered', 'count', 'original_count', 'operation', 'status'];
    if (validPaths.includes(path)) {
        return { valid: true };
    }

    return { valid: false, error: `Path "${path}" not available. Available: ${validPaths.join(', ')}` };
}

// ============================================================================
// Output Panel Content Component
// ============================================================================

// Draggable variable row
const FilterVariableRow = ({
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
    const dragId = `filter-var-${nodeId}-${path}`;
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

// Custom panel content for filter nodes
const FilterOutputPanelContent = ({ nodeId, output, draggable = true }: OutputPanelContentProps) => {
    const filterOutput = asFilterOutput(output);

    if (!filterOutput) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No filter output available
            </div>
        );
    }

    if (filterOutput.status === 'error') {
        return (
            <div className="text-xs text-red-600 dark:text-red-400 py-2">
                Error: {filterOutput.error || 'Unknown error'}
            </div>
        );
    }

    if (filterOutput.status === 'no_config') {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No configuration. Configure the filter operation in the node settings.
            </div>
        );
    }

    return (
        <div className="space-y-3">
            {/* Filter Stats */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Filter Results
                </div>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                    {filterOutput.operation && (
                        <>
                            <span className="capitalize">{filterOutput.operation.replace(/_/g, ' ')}</span>
                            <span className="text-muted-foreground/50 dark:text-zinc-700">•</span>
                        </>
                    )}
                    {filterOutput.count !== undefined && (
                        <>
                            <span>{filterOutput.count} items</span>
                        </>
                    )}
                    {filterOutput.keys_count !== undefined && (
                        <>
                            <span>{filterOutput.keys_count} keys</span>
                        </>
                    )}
                    {filterOutput.original_count !== undefined && filterOutput.count !== undefined && (
                        <>
                            <span className="text-muted-foreground/50 dark:text-zinc-700">•</span>
                            <span className="text-muted-foreground dark:text-zinc-500">
                                {filterOutput.count}/{filterOutput.original_count}
                            </span>
                        </>
                    )}
                </div>
                {filterOutput.duplicates_removed !== undefined && filterOutput.duplicates_removed > 0 && (
                    <div className="text-[10px] text-purple-600 dark:text-purple-400">
                        Removed {filterOutput.duplicates_removed} duplicate{filterOutput.duplicates_removed !== 1 ? 's' : ''}
                    </div>
                )}
            </div>

            {/* Available Variables */}
            <div className="space-y-1.5">
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Available Variables
                </div>
                <FilterVariableRow
                    nodeId={nodeId}
                    path="filtered"
                    label="filtered"
                    value={filterOutput.filtered}
                    valueType={getValueType(filterOutput.filtered)}
                    draggable={draggable}
                />
                {filterOutput.count !== undefined && (
                    <FilterVariableRow
                        nodeId={nodeId}
                        path="count"
                        label="count"
                        value={filterOutput.count}
                        valueType="number"
                        draggable={draggable}
                    />
                )}
                {filterOutput.original_count !== undefined && (
                    <FilterVariableRow
                        nodeId={nodeId}
                        path="original_count"
                        label="original_count"
                        value={filterOutput.original_count}
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

export const filterDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: FilterOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const FilterNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={Filter} iconColor="text-purple-600 dark:text-purple-400" />;
};

export const FilterNode: NodeDefinition = {
    type: 'filter',
    label: 'Filter',
    description: 'Filter data',
    Icon: Filter,
    iconColor: 'text-purple-600 dark:text-purple-400',
    dimensions: DIMENSIONS,
    component: FilterNodeComponent,
    displayStrategy: filterDisplayStrategy,
};
