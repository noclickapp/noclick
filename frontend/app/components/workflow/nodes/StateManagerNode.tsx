// State Manager node for providing persistent state to Code nodes.
// Stores state in the database scoped to (workflow_id, node_id) so each instance
// has its own isolated state that persists across workflow executions.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { Database, GripVertical } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import AutomationNode from './base/AutomationNode';
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
// Type Helpers
// ============================================================================

interface StateManagerOutputShape {
    type: 'state_manager';
    status: string;
    state?: JsonObject;
    error?: string | null;
    timing_ms?: number;
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
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return [];
    }

    const suggestions: ReferenceSuggestion[] = [];
    const data = output as unknown as StateManagerOutputShape;
    const state = data.state;

    // Add state as a whole object reference
    if (state && typeof state === 'object') {
        suggestions.push({
            reference: `${nodeId}.state`,
            label: 'state',
            nodeId,
            path: 'state',
            valueType: 'object',
            value: state,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return { valid: false, error: 'No state output available' };
    }

    const data = output as unknown as StateManagerOutputShape;

    if (path === 'state') {
        return data.state !== undefined
            ? { valid: true }
            : { valid: false, error: 'No state data available' };
    }

    if (path.startsWith('state.')) {
        const fieldName = path.slice(6); // Remove "state."
        const state = data.state;
        if (state && typeof state === 'object') {
            if (fieldName in state) {
                return { valid: true };
            }
            const availableKeys = Object.keys(state).join(', ');
            return {
                valid: false,
                error: `Field "${fieldName}" not found in state. Available: ${availableKeys}`,
            };
        }
        return { valid: false, error: 'State is not an object with fields' };
    }

    return {
        valid: false,
        error: `Unknown field "${path}". Use state or state.fieldName`,
    };
}

// ============================================================================
// Variable Row Component (draggable)
// ============================================================================

const VariableRow = ({
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
    const dragId = `state-var-${nodeId}-${path}`;
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
        if (typeof val === 'string') {
            return val.length > 40 ? `"${val.slice(0, 40)}..."` : `"${val}"`;
        }
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

    return (
        <div
            ref={draggable ? setNodeRef : undefined}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-all ${
                draggable ? 'cursor-grab active:cursor-grabbing' : ''
            } ${
                isDragging
                    ? 'opacity-50 border-purple-500/50 bg-purple-500/10'
                    : 'border-border/50 dark:border-zinc-700/50 bg-muted/30 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50'
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
                        {valueType}
                    </span>
                </div>
                <div className="text-[10px] text-muted-foreground dark:text-zinc-500 truncate font-mono mt-0.5">
                    {formatValue(value)}
                </div>
            </div>
        </div>
    );
};

// ============================================================================
// Output Panel Content Component
// ============================================================================

const StateManagerOutputPanelContent = ({
    nodeId,
    output,
    draggable = true,
}: OutputPanelContentProps) => {
    if (!output || typeof output !== 'object' || Array.isArray(output)) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No state output yet. Run the workflow to see state.
            </div>
        );
    }

    const data = output as unknown as StateManagerOutputShape;
    const status = data.status;
    const state = data.state;
    const error = data.error;
    const timingMs = data.timing_ms;
    const isPreview = status === 'preview';

    return (
        <div className="space-y-3">
            {/* Status indicator */}
            <div className="flex items-center gap-2 flex-wrap">
                <span
                    className={`text-xs font-mono px-2 py-0.5 rounded ${
                        status === 'success'
                            ? 'bg-green-500/20 text-green-600 dark:text-green-400'
                            : isPreview
                              ? 'bg-purple-500/20 text-purple-600 dark:text-purple-400'
                              : 'bg-red-500/20 text-red-600 dark:text-red-400'
                    }`}
                >
                    {status === 'success'
                        ? '✓ Loaded'
                        : isPreview
                          ? '◎ Preview'
                          : '✗ Error'}
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-600 dark:text-purple-400">
                    State
                </span>
                {timingMs !== undefined && (
                    <span className="text-[10px] text-muted-foreground dark:text-zinc-500 font-mono">
                        {timingMs < 1 ? '<1ms' : `${Math.round(timingMs)}ms`}
                    </span>
                )}
            </div>

            {/* Error message */}
            {error && (
                <div className="space-y-1">
                    <div className="text-[10px] text-red-600 dark:text-red-400 uppercase tracking-wider">
                        Error
                    </div>
                    <pre className="text-xs text-red-700 dark:text-red-300 bg-red-500/10 rounded-lg p-2 overflow-x-auto font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                        {error}
                    </pre>
                </div>
            )}

            {/* Draggable state reference - show whole state object */}
            {(isPreview || (state && Object.keys(state).length > 0)) && (
                <div className="space-y-1.5">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        State
                    </div>
                    <VariableRow
                        nodeId={nodeId}
                        path="state"
                        label="state"
                        value={state || {}}
                        valueType="object"
                        draggable={draggable}
                    />
                    <div className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 italic">
                        Drag to use persistent state in your code
                    </div>
                </div>
            )}

            {/* Empty state (only show for executed, not preview) */}
            {!isPreview && state && Object.keys(state).length === 0 && (
                <div className="text-xs text-muted-foreground dark:text-zinc-500 italic">
                    State is empty. Configure initial state or it will be
                    populated on first run.
                </div>
            )}
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

const stateManagerDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: StateManagerOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const StateManagerNodeComponent = (props: NodeProps) => {
    return (
        <div className="relative">
            <AutomationNode
                {...props}
                Icon={Database}
                iconColor="text-muted-foreground"
                hideLeftHandle
            />
            {/* Top handle for connecting to Code node's state handle */}
            <Handle
                id="output"
                type="source"
                position={Position.Top}
                className="!w-4 !h-4 !bg-zinc-500 !border-2 !border-zinc-300 dark:!border-zinc-400 hover:!bg-zinc-300 dark:!bg-zinc-400 hover:!border-zinc-300 transition-all opacity-70 hover:opacity-100"
                style={{
                    zIndex: 10,
                    top: -8,
                    left: '50%',
                    transform: 'translateX(-50%)',
                }}
                title="Connect to Code node's state input"
            />
        </div>
    );
};

export const StateManagerNode: NodeDefinition = {
    type: 'state-manager',
    label: 'State',
    description: 'Persistent state for code',
    Icon: Database,
    iconColor: 'text-muted-foreground',
    dimensions: DIMENSIONS,
    component: memo(StateManagerNodeComponent),
    displayStrategy: stateManagerDisplayStrategy,
};
