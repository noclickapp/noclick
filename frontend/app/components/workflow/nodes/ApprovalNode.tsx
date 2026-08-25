// Approval node for human-in-the-loop workflow execution.
// Creates an approval request in the feed and pauses execution until approved/rejected.
// Has two output handles: "approved" and "rejected" for branching.

import React, { memo } from 'react';
import { NodeProps, Handle, Position, useStore } from '@xyflow/react';
import { ShieldCheck, Ban } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
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
// Display Strategy
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    if (output === null || typeof output !== 'object' || Array.isArray(output))
        return [];
    const obj = output as JsonObject;
    if (!('isConditionalNode' in obj)) return [];

    const suggestions: ReferenceSuggestion[] = [];

    suggestions.push({
        reference: `${nodeId}.output_handle`,
        label: 'output_handle',
        nodeId,
        path: 'output_handle',
        valueType: 'string',
        value: (obj.output_handle as string) ?? 'pending',
        depth: 0,
    });

    suggestions.push({
        reference: `${nodeId}.status`,
        label: 'status',
        nodeId,
        path: 'status',
        valueType: 'string',
        value: (obj.status as string) ?? 'pending',
        depth: 0,
    });

    return suggestions;
}

function validateReference(
    _output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const validPaths = ['output_handle', 'status', 'title', 'content'];
    if (validPaths.includes(path)) return { valid: true };
    return {
        valid: false,
        error: `Path "${path}" not available. Available: ${validPaths.join(', ')}`,
    };
}

const ApprovalOutputPanelContent = ({ output }: OutputPanelContentProps) => {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return (
            <div className="text-xs text-muted-foreground dark:text-zinc-500 italic py-2">
                No output available
            </div>
        );
    }

    const obj = output as JsonObject;
    const status = (obj.status as string) ?? 'pending';

    return (
        <div className="space-y-2">
            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                Approval Status
            </div>
            <div className="flex items-center gap-2 text-[10px]">
                <span
                    className={`px-2 py-0.5 rounded font-medium ${
                        status === 'approved'
                            ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                            : status === 'rejected'
                              ? 'bg-red-500/20 text-red-600 dark:text-red-400'
                              : 'bg-amber-500/20 text-amber-600 dark:text-amber-400'
                    }`}
                >
                    {status}
                </span>
            </div>
        </div>
    );
};

export const approvalDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: ApprovalOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const ApprovalNodeComponent = ({ id, data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false;
    const hasMockedOutput = data?.mockedOutput != null;

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

            {/* Approved Handle (right-top) */}
            <Handle
                id="approved"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: '30%', zIndex: 10 }}
                title="Approved branch"
            />
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-emerald-600 dark:text-emerald-400 pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -26,
                        top: '30%',
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    ✓
                </div>
            )}

            {/* Rejected Handle (right-bottom) */}
            <Handle
                id="rejected"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ top: '70%', zIndex: 10 }}
                title="Rejected branch"
            />
            {!isConnecting && (
                <div
                    className="absolute text-[10px] font-medium text-red-600 dark:text-red-400 pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                    style={{
                        right: -26,
                        top: '70%',
                        transform: 'translateY(-50%)',
                        zIndex: 5,
                    }}
                >
                    ✗
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
                    bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]
                    ${isRunning || shouldOptimize ? 'transition-none' : 'transition-all duration-500 ease-out'}
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
                    opacity: hasMockedOutput ? 0.65 : 1,
                }}
            >
                {/* Background gradient — teal/green theme */}
                <div
                    className={`absolute inset-0 opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-60' : 'group-hover:opacity-50'}`}
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(20, 184, 166, 0.15), transparent 50%)',
                    }}
                />

                <div
                    className={`absolute inset-0 rounded-2xl bg-gradient-to-br from-foreground/[0.08] via-transparent to-transparent pointer-events-none ${shouldOptimize ? '' : 'backdrop-blur-[2px]'}`}
                />
                <div
                    className={`absolute inset-[1px] rounded-2xl bg-gradient-radial from-foreground/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-70'}`}
                />

                <div
                    className={`flex flex-col items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                    style={{
                        transform: hasMockedOutput ? 'scale(0.7)' : 'scale(1)',
                    }}
                >
                    <NodeSpinner isLoading={isRunning} spinnerRadius={28}>
                        <ShieldCheck
                            className={`relative z-10 ${shouldOptimize ? '' : 'transition-all duration-500'} ${isDisabled ? 'opacity-35' : 'text-teal-600 dark:text-teal-400'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
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

export const ApprovalNode: NodeDefinition = {
    type: 'approval',
    label: 'Approval',
    description: 'Human approval gate',
    Icon: ShieldCheck,
    iconColor: 'text-teal-600 dark:text-teal-400',
    dimensions: DIMENSIONS,
    component: memo(ApprovalNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: approvalDisplayStrategy,
    skipAutoMemo: true,
};
