// AlarmNode component for scheduling agent wake-ups.
// Connects top handle to an AgentNode's bottom handle (same pattern as ToolNode).
// Provides a schedule_alarm tool that agents can call to set countdown timers,
// one-time alarms, or recurring crons. When fired, re-invokes the connected agent.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { Bell, Ban } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
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
// Output Type Helpers
// ============================================================================

interface AlarmOutputShape {
    type: 'tool_definition' | 'alarm_trigger';
    tool_name?: string;
    tool_description?: string;
    message?: string;
    triggered_at?: string;
    parameters?: Array<{
        name: string;
        type: string;
        description: string;
        required: boolean;
    }>;
    tool_definition?: AlarmOutputShape;
}

function asAlarmOutput(output: JsonValue): AlarmOutputShape | null {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return null;
    }
    return output as unknown as AlarmOutputShape;
}

// ============================================================================
// Display Strategy Implementation
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    const alarmOutput = asAlarmOutput(output);
    if (!alarmOutput) return [];

    const suggestions: ReferenceSuggestion[] = [];

    if (alarmOutput.type === 'alarm_trigger') {
        if (alarmOutput.message) {
            suggestions.push({
                reference: `${nodeId}.message`,
                label: 'message',
                nodeId,
                path: 'message',
                valueType: 'string',
                value: alarmOutput.message,
                depth: 1,
            });
        }
        if (alarmOutput.triggered_at) {
            suggestions.push({
                reference: `${nodeId}.triggered_at`,
                label: 'triggered_at',
                nodeId,
                path: 'triggered_at',
                valueType: 'string',
                value: alarmOutput.triggered_at,
                depth: 1,
            });
        }
    }

    if (alarmOutput.type === 'tool_definition' && alarmOutput.parameters) {
        for (const param of alarmOutput.parameters) {
            suggestions.push({
                reference: `${nodeId}.arguments.${param.name}`,
                label: `${param.name} (${param.type})`,
                nodeId,
                path: `arguments.${param.name}`,
                valueType: 'string',
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
    const alarmOutput = asAlarmOutput(output);
    if (!alarmOutput) return { valid: false, error: 'No alarm output' };

    if (alarmOutput.type === 'alarm_trigger') {
        if (path === 'message' || path === 'triggered_at')
            return { valid: true };
    }

    if (path.startsWith('arguments.')) return { valid: true };

    return { valid: false, error: `Unknown path: ${path}` };
}

const AlarmOutputPanelContent = ({
    nodeId,
    output,
}: OutputPanelContentProps) => {
    const alarmOutput = asAlarmOutput(output);

    if (!alarmOutput) {
        return (
            <div className="p-3 text-sm text-muted-foreground dark:text-zinc-500">
                No output yet. Connect to an agent to provide the schedule_alarm
                tool.
            </div>
        );
    }

    if (alarmOutput.type === 'alarm_trigger') {
        return (
            <div className="p-3 space-y-2">
                <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 font-medium">
                    <Bell className="w-3 h-3" />
                    Alarm Triggered
                </div>
                {alarmOutput.message && (
                    <div className="text-sm text-foreground/80 bg-muted/50 rounded p-2 break-words">
                        {alarmOutput.message}
                    </div>
                )}
                {alarmOutput.triggered_at && (
                    <div className="text-xs text-muted-foreground dark:text-zinc-500">
                        Fired at:{' '}
                        {new Date(alarmOutput.triggered_at).toLocaleString()}
                    </div>
                )}
            </div>
        );
    }

    if (alarmOutput.type === 'tool_definition') {
        return (
            <div className="p-3 space-y-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground font-medium">
                    <Bell className="w-3 h-3" />
                    Tool: {alarmOutput.tool_name || 'schedule_alarm'}
                </div>
                {alarmOutput.parameters &&
                    alarmOutput.parameters.length > 0 && (
                        <div className="space-y-1">
                            <div className="text-xs text-muted-foreground dark:text-zinc-500 font-medium">
                                Parameters:
                            </div>
                            {alarmOutput.parameters.map((param) => (
                                <div
                                    key={param.name}
                                    className="text-xs text-muted-foreground flex gap-2 pl-2"
                                >
                                    <span className="text-foreground/80 font-mono">
                                        {param.name}
                                    </span>
                                    <span className="text-muted-foreground/70 dark:text-zinc-600">
                                        ({param.type})
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
            </div>
        );
    }

    return null;
};

export const alarmDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: AlarmOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const AlarmNodeComponent = ({ data, selected }: NodeProps) => {
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
                                  : 'border border-border/40 dark:border-zinc-700/40 shadow-lg hover:shadow-2xl hover:border-foreground/30 hover:shadow-foreground/10'
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
                            'radial-gradient(circle at 70% 70%, rgba(245, 158, 11, 0.15), transparent 50%)',
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
                        <Bell
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

export const AlarmNode: NodeDefinition = {
    type: 'alarm',
    label: 'Alarm',
    description: 'Alarms for agents',
    keywords: ['alarm', 'reminder', 'wake up', 'timer', 'schedule', 'snooze', 'follow up', 'later', 'delay', 'cron for agents'],
    Icon: Bell,
    iconColor: 'text-amber-600 dark:text-amber-400',
    dimensions: DIMENSIONS,
    component: memo(AlarmNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: alarmDisplayStrategy,
    skipAutoMemo: true,
};
