// ToolNode component for defining tools that AI agents can use.
// Tools connect their top handle to an AgentNode's bottom handle,
// enabling the agent to call the tool with arguments.
// When called, the tool's arguments are exposed as draggable variables for downstream nodes.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { Wrench, Ban, GripVertical } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
import { useDraggable } from '@dnd-kit/core';
import type {
    NodeDefinition,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    JsonObject,
    ReferenceSuggestion,
} from './types';
import { NodeSpinner } from './base/NodeSpinner';
import { perfState } from '~/lib/perf-state';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Tool Output Type Helpers
// ============================================================================

interface ToolOutputShape {
    type: 'tool_call' | 'tool_definition';
    tool_name?: string;
    tool_description?: string;
    arguments?: JsonObject;
    parameters?: Array<{
        name: string;
        type: string;
        description: string;
        required: boolean;
    }>;
}

function asToolOutput(output: JsonValue): ToolOutputShape | null {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return null;
    }
    return output as unknown as ToolOutputShape;
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
    const toolOutput = asToolOutput(output);
    if (!toolOutput) return [];

    const suggestions: ReferenceSuggestion[] = [];

    // For tool_call output, expose the arguments
    if (toolOutput.type === 'tool_call' && toolOutput.arguments) {
        for (const [key, value] of Object.entries(toolOutput.arguments)) {
            suggestions.push({
                reference: `${nodeId}.arguments.${key}`,
                label: key,
                nodeId,
                path: `arguments.${key}`,
                valueType: getValueType(value),
                value,
                depth: 1,
            });
        }

        // Also add tool_name for context
        if (toolOutput.tool_name) {
            suggestions.push({
                reference: `${nodeId}.tool_name`,
                label: 'tool_name',
                nodeId,
                path: 'tool_name',
                valueType: 'string',
                value: toolOutput.tool_name,
                depth: 0,
            });
        }
    }

    // For tool_definition output (before tool is called), show expected parameters
    if (toolOutput.type === 'tool_definition' && toolOutput.parameters) {
        for (const param of toolOutput.parameters) {
            suggestions.push({
                reference: `${nodeId}.arguments.${param.name}`,
                label: `${param.name} (${param.type})`,
                nodeId,
                path: `arguments.${param.name}`,
                valueType: param.type as ReferenceSuggestion['valueType'],
                value: `<${param.type}>`,
                depth: 1,
            });
        }
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const toolOutput = asToolOutput(output);
    if (!toolOutput) {
        return { valid: false, error: 'No tool output available' };
    }

    // Check for tool_name
    if (path === 'tool_name') {
        return { valid: true };
    }

    // Check for arguments.fieldName
    if (path.startsWith('arguments.')) {
        const fieldName = path.slice(10); // Remove "arguments."

        if (toolOutput.type === 'tool_call' && toolOutput.arguments) {
            if (fieldName in toolOutput.arguments) {
                return { valid: true };
            }
            const availableArgs = Object.keys(toolOutput.arguments).join(', ');
            return {
                valid: false,
                error: `Argument "${fieldName}" not found. Available: ${availableArgs}`,
            };
        }

        if (toolOutput.type === 'tool_definition' && toolOutput.parameters) {
            const paramNames = toolOutput.parameters.map((p) => p.name);
            if (paramNames.includes(fieldName)) {
                return { valid: true };
            }
            return {
                valid: false,
                error: `Parameter "${fieldName}" not defined. Available: ${paramNames.join(', ')}`,
            };
        }

        return { valid: false, error: 'No arguments available' };
    }

    return {
        valid: false,
        error: `Unknown path "${path}". Use arguments.paramName`,
    };
}

// Display variable structure for internal use
interface DisplayVariable {
    path: string;
    label: string;
    value: JsonValue;
    type: string;
    description?: string;
}

function getDisplayVariables(output: JsonValue): DisplayVariable[] {
    const toolOutput = asToolOutput(output);
    if (!toolOutput) return [];

    const variables: DisplayVariable[] = [];

    // For tool_call output, show actual argument values
    if (toolOutput.type === 'tool_call' && toolOutput.arguments) {
        for (const [key, value] of Object.entries(toolOutput.arguments)) {
            variables.push({
                path: `arguments.${key}`,
                label: key,
                value: value,
                type:
                    value === null
                        ? 'null'
                        : Array.isArray(value)
                          ? 'array'
                          : typeof value,
            });
        }
    }

    // For tool_definition output, show expected parameters (before tool is called)
    if (toolOutput.type === 'tool_definition' && toolOutput.parameters) {
        for (const param of toolOutput.parameters) {
            variables.push({
                path: `arguments.${param.name}`,
                label: param.name,
                value: `<${param.type}>`,
                type: param.type,
                description: param.description,
            });
        }
    }

    return variables;
}

// ============================================================================
// Output Panel Content Component
// ============================================================================

// Single variable row - draggable
const ToolVariableRow = ({
    nodeId,
    path,
    label,
    value,
    valueType,
    description,
    draggable = true,
}: {
    nodeId: string;
    path: string;
    label: string;
    value: JsonValue;
    valueType: string;
    description?: string;
    draggable?: boolean;
}) => {
    const dragId = `tool-var-${nodeId}-${path}`;
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
            // Check if it's a placeholder like <string>
            if (val.startsWith('<') && val.endsWith('>')) return val;
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

    const isPlaceholder =
        typeof value === 'string' &&
        value.startsWith('<') &&
        value.endsWith('>');

    return (
        <div
            ref={draggable ? setNodeRef : undefined}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-all ${
                draggable ? 'cursor-grab active:cursor-grabbing' : ''
            } ${
                isDragging
                    ? 'opacity-50 border-orange-500/50 bg-orange-500/10'
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
                        {valueType}
                    </span>
                </div>
                <div
                    className={`text-[10px] truncate font-mono mt-0.5 ${isPlaceholder ? 'text-muted-foreground/70 dark:text-zinc-600 italic' : 'text-muted-foreground dark:text-zinc-500'}`}
                >
                    {isPlaceholder && description
                        ? description
                        : formatValue(value)}
                </div>
            </div>
        </div>
    );
};

// Custom panel content for tool nodes
const ToolOutputPanelContent = ({
    nodeId,
    output,
    draggable = true,
}: OutputPanelContentProps) => {
    const toolOutput = asToolOutput(output);
    const variables = getDisplayVariables(output);

    // Show tool definition info when not yet called
    if (toolOutput?.type === 'tool_definition') {
        return (
            <div className="space-y-3">
                <div className="space-y-1">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        Tool Definition
                    </div>
                    <div className="bg-muted/50 dark:bg-black/20 border border-border/50 dark:border-zinc-800/50 rounded-lg p-2">
                        <div className="text-xs text-orange-600 dark:text-orange-400 font-medium">
                            {toolOutput.tool_name}
                        </div>
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-1">
                            {toolOutput.tool_description}
                        </div>
                    </div>
                </div>

                {variables.length > 0 && (
                    <div className="space-y-1.5">
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                            Expected Arguments
                        </div>
                        <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mb-2">
                            These variables will be populated when the AI calls
                            this tool
                        </p>
                        {variables.map((variable) => (
                            <ToolVariableRow
                                key={variable.path}
                                nodeId={nodeId}
                                path={variable.path}
                                label={variable.label}
                                value={variable.value}
                                valueType={variable.type}
                                description={variable.description}
                                draggable={draggable}
                            />
                        ))}
                    </div>
                )}
            </div>
        );
    }

    // Show actual argument values when tool has been called
    if (toolOutput?.type === 'tool_call') {
        return (
            <div className="space-y-3">
                <div className="flex items-center gap-2">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        Tool Called
                    </div>
                    <div className="text-xs text-orange-600 dark:text-orange-400 font-medium">
                        {toolOutput.tool_name}
                    </div>
                </div>

                {variables.length > 0 && (
                    <div className="space-y-1.5">
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                            Arguments
                        </div>
                        {variables.map((variable) => (
                            <ToolVariableRow
                                key={variable.path}
                                nodeId={nodeId}
                                path={variable.path}
                                label={variable.label}
                                value={variable.value}
                                valueType={variable.type}
                                draggable={draggable}
                            />
                        ))}
                    </div>
                )}

                {variables.length === 0 && (
                    <div className="text-xs text-muted-foreground dark:text-zinc-500 italic">
                        Tool was called with no arguments
                    </div>
                )}
            </div>
        );
    }

    // Fallback for unknown output type
    if (variables.length === 0) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No tool output available. Connect to an agent and run the
                workflow.
            </div>
        );
    }

    return (
        <div className="space-y-1.5">
            {variables.map((variable) => (
                <ToolVariableRow
                    key={variable.path}
                    nodeId={nodeId}
                    path={variable.path}
                    label={variable.label}
                    value={variable.value}
                    valueType={variable.type}
                    draggable={draggable}
                />
            ))}
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

export const toolDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: ToolOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const ToolNodeComponent = ({ data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false;
    const hasMockedOutput = data?.mockedOutput != null;

    return (
        <div className="relative">
            {/* Top Handle - connects TO AgentNode's bottom handle */}
            <Handle
                id="top"
                type="source"
                position={Position.Top}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Left Input Handle - for receiving data from upstream nodes */}
            <Handle
                id="left"
                type="target"
                position={Position.Left}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Right Output Handle - for downstream workflow (tool side effects) */}
            <Handle
                id="right"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Config Status Badge */}
            {!isDisabled && !configValid && (
                <NodeStatusBadge variant="incomplete" />
            )}

            {/* Main Container */}
            <div
                className={`
                    group relative w-full h-full rounded-2xl overflow-hidden
                    flex flex-col items-center justify-center p-3
                    ${isRunning || shouldOptimize ? 'transition-none' : 'transition-all duration-500 ease-out'}
                    bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]
                    ${
                        selected
                            ? 'border-2 border-primary dark:border-foreground shadow-2xl shadow-primary/20 dark:shadow-foreground/20 scale-105'
                            : isRunning
                              ? 'border-2 border-foreground/60 shadow-lg shadow-foreground/10'
                              : isError
                                ? 'border border-red-500/40 shadow-lg shadow-red-500/10'
                                : !configValid
                                  ? 'border border-amber-500/40 shadow-lg shadow-amber-500/10'
                                  : 'border border-border dark:border-zinc-700/40 shadow-lg hover:shadow-2xl hover:border-foreground/30 hover:shadow-foreground/10'
                    }
                `}
                style={{
                    width: 90,
                    height: 90,
                    opacity: hasMockedOutput ? 0.65 : 1,
                }}
            >
                {/* Background gradient */}
                <div
                    className={`absolute inset-0 opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-60' : 'group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(249, 115, 22, 0.15), transparent 50%)',
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

                {/* Icon */}
                <div
                    className={`flex items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                    style={{
                        transform: hasMockedOutput ? 'scale(0.85)' : 'scale(1)',
                    }}
                >
                    <NodeSpinner isLoading={isRunning} spinnerRadius={28}>
                        <Wrench
                            className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-orange-600 dark:text-orange-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                            style={{
                                width: 48,
                                height: 48,
                                filter: isDisabled
                                    ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                    : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                            }}
                        />
                    </NodeSpinner>
                </div>

                {/* MOCK label overlay */}
                {hasMockedOutput && (
                    <div className="absolute bottom-2 text-[10px] font-bold tracking-widest text-foreground dark:[text-shadow:0_2px_6px_rgba(0,0,0,0.9)]">
                        MOCK
                    </div>
                )}

                {/* Disabled Overlay */}
                {isDisabled && (
                    <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                        <Ban
                            className="text-muted-foreground dark:text-zinc-500 opacity-50"
                            style={{ width: 38, height: 38 }}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

export const ToolNode: NodeDefinition = {
    type: 'tool',
    label: 'Tool',
    description: 'Custom tool for AI',
    keywords: ['tool', 'custom tool', 'function', 'function calling', 'agent tool', 'subworkflow', 'callable'],
    Icon: Wrench,
    iconColor: 'text-orange-600 dark:text-orange-400',
    dimensions: DIMENSIONS,
    component: memo(ToolNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: toolDisplayStrategy,
    skipAutoMemo: true,
};
