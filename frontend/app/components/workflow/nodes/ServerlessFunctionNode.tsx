// Serverless Function node for executing isolated Python or JavaScript (QuickJS) code.
// Python supports configurable hardware (GPU, CPU, memory) and pip packages.
// Custom output panel displays stdout, stderr, return value variables, and exit code.
// Includes a bottom handle for connecting State Manager nodes for persistent state.

import { memo, useCallback } from 'react';
import { NodeProps, Handle, Position, useReactFlow } from '@xyflow/react';
import { Code2, GripVertical, Database } from 'lucide-react';
import { useDraggable } from '@dnd-kit/core';
import { CopyButton } from '~/components/ui/CopyButton';
import AutomationNode from './base/AutomationNode';
import { createStyledEdge } from '~/utils/workflowLayout';
import { createWorkflowNode, updateNodeInList } from '~/lib/applyNodeUpdate';
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

interface ServerlessFunctionOutputShape {
    type: 'serverless_function';
    status: string;
    runtime?: 'python' | 'javascript';
    result?: JsonValue;
    stdout?: string;
    stderr?: string;
    error?: string | null;
    exit_code?: number;
    execution_time_ms?: number;
    hardware?: {
        gpu_type: string;
        gpu_count: number;
        cpu_cores: number;
        memory_mb: number;
    };
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
    if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return [];
    }

    const suggestions: ReferenceSuggestion[] = [];
    const data = output as unknown as ServerlessFunctionOutputShape;
    const result = data.result;

    // Add result fields if result is an object
    if (result && typeof result === 'object' && !Array.isArray(result)) {
        const resultObj = result as JsonObject;
        for (const key of Object.keys(resultObj)) {
            const value = resultObj[key];
            suggestions.push({
                reference: `${nodeId}.result.${key}`,
                label: `result.${key}`,
                nodeId,
                path: `result.${key}`,
                valueType: getValueType(value),
                value,
                depth: 1,
            });
        }
    } else if (result !== undefined && result !== null) {
        // Result is a primitive or array
        suggestions.push({
            reference: `${nodeId}.result`,
            label: 'result',
            nodeId,
            path: 'result',
            valueType: getValueType(result),
            value: result,
            depth: 0,
        });
    }

    // Add stdout/stderr if present
    if (data.stdout) {
        suggestions.push({
            reference: `${nodeId}.stdout`,
            label: 'stdout',
            nodeId,
            path: 'stdout',
            valueType: 'string',
            value: data.stdout,
            depth: 0,
        });
    }

    if (data.stderr) {
        suggestions.push({
            reference: `${nodeId}.stderr`,
            label: 'stderr',
            nodeId,
            path: 'stderr',
            valueType: 'string',
            value: data.stderr,
            depth: 0,
        });
    }

    // Add exit_code
    suggestions.push({
        reference: `${nodeId}.exit_code`,
        label: 'exit_code',
        nodeId,
        path: 'exit_code',
        valueType: 'number',
        value: data.exit_code ?? 0,
        depth: 0,
    });

    return suggestions;
}

function validateReference(output: JsonValue, path: string): { valid: boolean; error?: string } {
    if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return { valid: false, error: 'No function output available' };
    }

    const data = output as unknown as ServerlessFunctionOutputShape;

    // Check for top-level fields
    if (path === 'stdout' || path === 'stderr' || path === 'exit_code' || path === 'error') {
        return { valid: true };
    }

    // Check for result or result.fieldName
    if (path === 'result') {
        return data.result !== undefined ? { valid: true } : { valid: false, error: 'No result data available' };
    }

    if (path.startsWith('result.')) {
        const fieldName = path.slice(7); // Remove "result."
        const result = data.result;
        if (result && typeof result === 'object' && !Array.isArray(result)) {
            const resultObj = result as JsonObject;
            if (fieldName in resultObj) {
                return { valid: true };
            }
            const availableKeys = Object.keys(resultObj).join(', ');
            return { valid: false, error: `Field "${fieldName}" not found in result. Available: ${availableKeys}` };
        }
        return { valid: false, error: 'Result is not an object with fields' };
    }

    return { valid: false, error: `Unknown field "${path}". Use result.fieldName, stdout, stderr, or exit_code` };
}

// ============================================================================
// Variable Row Component (matches IterationNode style)
// ============================================================================

interface DisplayVariable {
    path: string;
    label: string;
    value: JsonValue;
    type: string;
}

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
    const dragId = `serverless-var-${nodeId}-${path}`;
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

    return (
        <div
            ref={draggable ? setNodeRef : undefined}
            {...(draggable ? attributes : {})}
            {...(draggable ? listeners : {})}
            className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-all ${
                draggable ? 'cursor-grab active:cursor-grabbing' : ''
            } ${
                isDragging
                    ? 'opacity-50 border-violet-500/50 bg-violet-500/10'
                    : 'border-border/50 dark:border-zinc-700/50 bg-muted/30 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50'
            }`}
        >
            {draggable && <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0" />}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <code className="text-xs text-foreground font-medium">{label}</code>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${typeColor}`}>
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

function getDisplayVariables(output: JsonValue): DisplayVariable[] {
    if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return [];
    }

    const variables: DisplayVariable[] = [];
    const data = output as unknown as ServerlessFunctionOutputShape;
    const result = data.result;

    // Add result fields if result is an object
    if (result && typeof result === 'object' && !Array.isArray(result)) {
        const resultObj = result as JsonObject;
        for (const key of Object.keys(resultObj)) {
            const value = resultObj[key];
            variables.push({
                path: `result.${key}`,
                label: key,
                value: value,
                type: value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value,
            });
        }
    } else if (result !== undefined && result !== null) {
        // Result is a primitive or array
        variables.push({
            path: 'result',
            label: 'result',
            value: result,
            type: result === null ? 'null' : Array.isArray(result) ? 'array' : typeof result,
        });
    }

    return variables;
}

const ServerlessFunctionOutputPanelContent = ({ nodeId, output, draggable = true }: OutputPanelContentProps) => {
    if (!output || typeof output !== 'object' || Array.isArray(output)) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No execution output yet. Run the workflow to see results.
            </div>
        );
    }

    const data = output as unknown as ServerlessFunctionOutputShape;
    const status = data.status;
    const stdout = data.stdout;
    const stderr = data.stderr;
    const exitCode = data.exit_code;
    const error = data.error;
    const hardware = data.hardware;

    const runtime = data.runtime || 'python';
    const executionTimeMs = data.execution_time_ms;

    // Show status indicator for running/building states
    if (status === 'starting' || status === 'building_image' || status === 'running') {
        // JS doesn't have starting/building_image phases
        const isJs = runtime === 'javascript';
        return (
            <div className="space-y-3">
                <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                        {isJs ? 'Executing...' : (
                            <>
                                {status === 'starting' && 'Starting sandbox...'}
                                {status === 'building_image' && 'Building image...'}
                                {status === 'running' && 'Executing function...'}
                            </>
                        )}
                    </span>
                </div>
                {!isJs && hardware && (
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500">
                        {hardware.gpu_type !== 'none' && `${hardware.gpu_type} x${hardware.gpu_count} • `}
                        {hardware.cpu_cores} CPU • {hardware.memory_mb}MB RAM
                    </div>
                )}
            </div>
        );
    }

    const variables = getDisplayVariables(output);

    const isJs = runtime === 'javascript';
    const runtimeLabel = isJs ? 'JS' : 'Python';
    const runtimeColor = isJs ? 'bg-yellow-500/20 text-yellow-600 dark:text-yellow-400' : 'bg-violet-500/20 text-violet-600 dark:text-violet-400';

    return (
        <div className="space-y-3">
            {/* Exit code badge + runtime + timing */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-xs font-mono px-2 py-0.5 rounded ${
                    exitCode === 0 ? 'bg-green-500/20 text-green-600 dark:text-green-400' : 'bg-red-500/20 text-red-600 dark:text-red-400'
                }`}>
                    {exitCode === 0 ? '✓ Success' : `✗ Exit ${exitCode ?? 'N/A'}`}
                </span>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${runtimeColor}`}>
                    {runtimeLabel}
                </span>
                {executionTimeMs !== undefined && (
                    <span className="text-[10px] text-muted-foreground dark:text-zinc-500 font-mono">
                        {executionTimeMs < 1 ? '<1ms' : `${Math.round(executionTimeMs)}ms`}
                    </span>
                )}
                {!isJs && hardware && (
                    <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 ml-auto">
                        {hardware.gpu_type !== 'none' && `${hardware.gpu_type} • `}
                        {hardware.cpu_cores} CPU
                    </span>
                )}
            </div>

            {/* Error message */}
            {error && (
                <div className="space-y-1">
                    <div className="text-[10px] text-red-600 dark:text-red-400 uppercase tracking-wider">Error</div>
                    <pre className="text-xs text-red-700 dark:text-red-300 bg-red-500/10 rounded-lg p-2 overflow-x-auto font-mono whitespace-pre-wrap max-h-32 overflow-y-auto">
                        {error}
                    </pre>
                </div>
            )}

            {/* Return value variables - draggable like iteration node */}
            {variables.length > 0 && (
                <div className="space-y-1.5">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">Return Value</div>
                    {variables.map((variable) => (
                        <VariableRow
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

            {/* Stdout */}
            {stdout && stdout.trim() && (
                <details className="group">
                    <summary className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider cursor-pointer hover:text-muted-foreground flex items-center gap-1">
                        <span className="group-open:rotate-90 transition-transform">▶</span>
                        Stdout ({stdout.split('\n').filter(l => l.trim()).length} lines)
                    </summary>
                    <div className="relative mt-1">
                        <pre className="text-xs text-muted-foreground bg-muted/30 rounded-lg p-2 pr-8 overflow-x-auto font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
                            {stdout}
                        </pre>
                        <div className="absolute top-1 right-1">
                            <CopyButton value={stdout} className="!p-1 bg-muted/50 hover:bg-accent dark:hover:bg-zinc-700/50" />
                        </div>
                    </div>
                </details>
            )}

            {/* Stderr */}
            {stderr && stderr.trim() && (
                <details className="group" open>
                    <summary className="text-[10px] text-amber-500 uppercase tracking-wider cursor-pointer hover:text-amber-400 flex items-center gap-1">
                        <span className="group-open:rotate-90 transition-transform">▶</span>
                        Stderr ({stderr.split('\n').filter(l => l.trim()).length} lines)
                    </summary>
                    <div className="relative mt-1">
                        <pre className="text-xs text-amber-700 dark:text-amber-300 bg-amber-500/10 rounded-lg p-2 pr-8 overflow-x-auto font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
                            {stderr}
                        </pre>
                        <div className="absolute top-1 right-1">
                            <CopyButton value={stderr} className="!p-1 bg-amber-900/30 hover:bg-amber-800/30" />
                        </div>
                    </div>
                </details>
            )}
        </div>
    );
};

// ============================================================================
// Display Strategy Export
// ============================================================================

const serverlessFunctionDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: ServerlessFunctionOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const ServerlessFunctionNodeComponent = (props: NodeProps) => {
    const { id: nodeId, data } = props;
    const { addNodes, addEdges, getEdges, getNodes, setNodes } = useReactFlow();

    // Check if this node already has a state connection
    const hasStateConnection = useCallback(() => {
        const edges = getEdges();
        return edges.some(e => e.target === nodeId && e.targetHandle === 'state');
    }, [getEdges, nodeId]);

    const handleAddStateNode = useCallback((e: React.MouseEvent) => {
        e.stopPropagation();
        e.preventDefault();

        if (hasStateConnection()) return;

        // Get current node position from ReactFlow state (more reliable than props)
        const currentNode = getNodes().find(n => n.id === nodeId);
        const nodePosition = currentNode?.position ?? { x: 0, y: 0 };

        const stateNodeId = `state-manager-${Date.now()}`;

        // Create state manager node positioned below the code node
        // Include a preview output so the state field is draggable in the input panel
        const stateNode = createWorkflowNode(
            stateNodeId,
            'state-manager',
            { x: nodePosition.x, y: nodePosition.y + 130 },
            { label: 'State', state: {} },
            {
                output: {
                    type: 'state_manager',
                    status: 'preview',
                    state: {},
                },
            },
        );

        // Create properly styled edge
        const edge = createStyledEdge({
            id: `edge-${stateNodeId}-${nodeId}`,
            source: stateNodeId,
            sourceHandle: 'output',
            target: nodeId,
            targetHandle: 'state',
        });

        // Add node and edge
        addNodes(stateNode);
        addEdges(edge);

        // Update function_inputs after a brief delay to ensure node is added
        requestAnimationFrame(() => {
            setNodes((nodes) => {
                const target = nodes.find(n => n.id === nodeId);
                if (!target) return nodes;
                const existingConfig = (target.data?.config ?? {}) as Record<string, any>;
                const currentInputs = Array.isArray(existingConfig.function_inputs)
                    ? (existingConfig.function_inputs as Array<{ name: string; value: string }>)
                    : [];
                const filteredInputs = currentInputs.filter(i => i.name !== 'state');
                const stateInput = { name: 'state', value: `{{${stateNodeId}.state}}` };
                return updateNodeInList(nodes, nodeId, {
                    config: { function_inputs: [...filteredInputs, stateInput] },
                });
            });
        });
    }, [addNodes, addEdges, setNodes, getNodes, nodeId, hasStateConnection]);

    const isConnected = hasStateConnection();

    return (
        <div className="relative">
            <AutomationNode {...props} Icon={Code2} iconColor="text-violet-600 dark:text-violet-400" />
            {/* Bottom handle with database icon - clickable to add State Manager */}
            <Handle
                id="state"
                type="target"
                position={Position.Bottom}
                className="!w-5 !h-5 !bg-transparent !border-0"
                style={{
                    bottom: -10,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    zIndex: 10000,
                }}
            />
            {/* Clickable database button positioned over the handle */}
            <div
                role="button"
                tabIndex={isConnected ? -1 : 0}
                onClick={(e) => {
                    if (!isConnected) handleAddStateNode(e);
                }}
                onMouseDown={(e) => e.stopPropagation()}
                className={`absolute flex items-center justify-center w-5 h-5 rounded-md border transition-all ${
                    isConnected
                        ? 'bg-muted dark:bg-muted-foreground/40 border-muted-foreground/50 dark:border-zinc-500 cursor-default'
                        : 'bg-card dark:bg-foreground/20 border-border dark:border-zinc-600 hover:bg-muted dark:hover:bg-muted-foreground/40 hover:border-muted-foreground/50 dark:hover:border-zinc-500 cursor-pointer'
                }`}
                style={{
                    bottom: -10,
                    left: '50%',
                    transform: 'translateX(-50%)',
                    zIndex: 10001,
                }}
                title={isConnected ? 'State Manager connected' : 'Click to add State Manager'}
            >
                <Database className={`w-3 h-3 ${isConnected ? 'text-foreground/80' : 'text-muted-foreground group-hover:text-foreground/80'}`} strokeWidth={2.5} />
            </div>
        </div>
    );
};

export const ServerlessFunctionNode: NodeDefinition = {
    type: 'automation-serverless-function',
    label: 'Code',
    description: 'Custom code',
    Icon: Code2,
    iconColor: 'text-violet-600 dark:text-violet-400',
    dimensions: DIMENSIONS,
    component: memo(ServerlessFunctionNodeComponent),
    displayStrategy: serverlessFunctionDisplayStrategy,
};
