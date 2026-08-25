// NoClick MCP node — provides NoClick's own MCP tools to Agent nodes
// without requiring authentication. Connect its top handle to an Agent's
// bottom handle to give the agent access to workflow CRUD, execution, etc.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { Ban } from 'lucide-react';
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
import { LogoMark } from '~/components/shared/LogoMark';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Output Type Helpers (same shape as MCPServerNode)
// ============================================================================

interface NoClickToolDefinition {
    type: 'tool_definition';
    tool_type: 'mcp';
    tool_name: string;
    original_tool_name: string;
    tool_description: string;
    parameters: Array<{
        name: string;
        type: string;
        description: string;
        required: boolean;
    }>;
}

interface NoClickOutputShape {
    type: 'mcp_tool_definitions';
    server_name?: string;
    tool_count?: number;
    tools?: NoClickToolDefinition[];
    error?: string;
}

function asNoClickOutput(output: JsonValue): NoClickOutputShape | null {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return null;
    }
    if ((output as JsonObject).type !== 'mcp_tool_definitions') {
        return null;
    }
    return output as unknown as NoClickOutputShape;
}

// ============================================================================
// Display Strategy
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    const ncOutput = asNoClickOutput(output);
    if (!ncOutput) return [];

    const suggestions: ReferenceSuggestion[] = [];

    if (ncOutput.tool_count !== undefined) {
        suggestions.push({
            reference: `${nodeId}.tool_count`,
            label: 'tool_count',
            nodeId,
            path: 'tool_count',
            valueType: 'number',
            value: ncOutput.tool_count,
            depth: 0,
        });
    }

    return suggestions;
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const ncOutput = asNoClickOutput(output);
    if (!ncOutput) {
        return { valid: false, error: 'No NoClick output available' };
    }

    if (path === 'tool_count' || path === 'server_name') {
        return { valid: true };
    }

    return { valid: false, error: `Unknown path "${path}"` };
}

interface DisplayTool {
    name: string;
    description: string;
    paramCount: number;
}

function getDisplayTools(output: JsonValue): DisplayTool[] {
    const ncOutput = asNoClickOutput(output);
    if (!ncOutput || !ncOutput.tools) return [];

    return ncOutput.tools.map((tool) => ({
        name: tool.tool_name,
        description: tool.tool_description,
        paramCount: tool.parameters?.length || 0,
    }));
}

// ============================================================================
// Output Panel Content
// ============================================================================

const ToolRow = ({
    name,
    description,
    paramCount,
}: {
    name: string;
    description: string;
    paramCount: number;
}) => (
    <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-border/50 dark:border-zinc-700/50 bg-muted/30 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 hover:bg-accent dark:hover:bg-zinc-800/50 transition-all">
        <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
                <code
                    className="text-xs text-foreground/80 font-medium truncate"
                    title={name}
                >
                    {name}
                </code>
                <span className="text-[9px] px-1.5 py-0.5 rounded text-muted-foreground bg-zinc-400/10 flex-none whitespace-nowrap">
                    {paramCount}p
                </span>
            </div>
            <div className="text-[10px] truncate text-muted-foreground dark:text-zinc-500 mt-0.5">
                {description}
            </div>
        </div>
    </div>
);

// eslint-disable-next-line @typescript-eslint/no-unused-vars
const NoClickOutputPanelContent = ({
    nodeId,
    output,
}: OutputPanelContentProps) => {
    const ncOutput = asNoClickOutput(output);
    const tools = getDisplayTools(output);

    if (ncOutput?.error) {
        return (
            <div className="space-y-3">
                <div className="text-[10px] text-red-600 dark:text-red-400 uppercase tracking-wider">
                    Error
                </div>
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2">
                    <div className="text-xs text-red-600 dark:text-red-400">
                        {ncOutput.error}
                    </div>
                </div>
            </div>
        );
    }

    if (ncOutput?.type === 'mcp_tool_definitions') {
        return (
            <div className="space-y-3">
                <div className="space-y-1">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        NoClick MCP
                    </div>
                    <div className="bg-black/20 border border-border/50 dark:border-zinc-800/50 rounded-lg p-2">
                        <div className="text-xs text-foreground/80 font-medium">
                            NoClick Tools
                        </div>
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 mt-1">
                            Built-in workflow automation tools (no auth
                            required)
                        </div>
                    </div>
                </div>

                {tools.length > 0 && (
                    <div className="space-y-1.5">
                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                            Available Tools ({tools.length})
                        </div>
                        <p className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 mb-2">
                            These tools will be available to connected AI Agents
                        </p>
                        {tools.map((tool) => (
                            <ToolRow
                                key={tool.name}
                                name={tool.name}
                                description={tool.description}
                                paramCount={tool.paramCount}
                            />
                        ))}
                    </div>
                )}

                {tools.length === 0 && (
                    <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                        No tools discovered. Run the workflow to discover tools.
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
            No output available. Connect to an agent and run the workflow.
        </div>
    );
};

export const noClickDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: NoClickOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const NoClickNodeComponent = ({ data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
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
                                : 'border border-border/40 dark:border-zinc-700/40 shadow-lg hover:shadow-2xl hover:border-foreground/30 hover:shadow-foreground/10'
                    }
                `}
                style={{
                    width: 90,
                    height: 90,
                    opacity: hasMockedOutput ? 0.65 : 1,
                }}
            >
                {/* Background gradient - emerald/teal theme */}
                <div
                    className={`absolute inset-0 opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-60' : 'group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(16, 185, 129, 0.15), transparent 50%)',
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
                        <div
                            className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : ''} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                            style={{
                                filter: isDisabled
                                    ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                    : 'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                            }}
                        >
                            <LogoMark width={48} height={48} className="" />
                        </div>
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

// Icon wrapper for sidebar/search — renders NoClick logo at the given size
const NoClickIcon = ({
    className,
    style,
}: {
    className?: string;
    style?: React.CSSProperties;
}) => {
    const size = style?.width ? Number(style.width) : 24;
    return (
        <div className={className} style={style}>
            <LogoMark width={size} height={size} className="" />
        </div>
    );
};

export const NoClickNode: NodeDefinition = {
    type: 'noclick',
    label: 'NoClick',
    description: 'NoClick workflow tools',
    Icon: NoClickIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(NoClickNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: noClickDisplayStrategy,
    skipAutoMemo: true,
};
