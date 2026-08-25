// FilesystemNode component for persistent agent storage.
// Connects top handle to an AgentNode's bottom handle (same pattern as ToolNode/AlarmNode).
// Provides a managed workspace volume that persists files across agent executions.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { FolderOpen, Ban } from 'lucide-react';
import { NodeStatusBadge } from './base/NodeStatusBadge';
import type {
    NodeDefinition,
    NodeDisplayStrategy,
    OutputPanelContentProps,
    JsonValue,
    ReferenceSuggestion,
} from './types';
import { NodeSpinner } from './base/NodeSpinner';
import { perfState } from '~/lib/perf-state';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// ============================================================================
// Output Type Helpers
// ============================================================================

interface FilesystemOutputShape {
    type: 'filesystem_config';
    volume_mode: string;
    mount_path: string;
    node_id: string;
}

function asFilesystemOutput(output: JsonValue): FilesystemOutputShape | null {
    if (
        output === null ||
        typeof output !== 'object' ||
        Array.isArray(output)
    ) {
        return null;
    }
    const obj = output as Record<string, unknown>;
    if (obj.type !== 'filesystem_config') return null;
    return obj as unknown as FilesystemOutputShape;
}

// ============================================================================
// Display Strategy Implementation
// ============================================================================

function buildSuggestions(
    output: JsonValue,
    nodeId: string
): ReferenceSuggestion[] {
    const fsOutput = asFilesystemOutput(output);
    if (!fsOutput) return [];

    return [
        {
            reference: `${nodeId}.volume_mode`,
            label: 'volume_mode',
            nodeId,
            path: 'volume_mode',
            valueType: 'string',
            value: fsOutput.volume_mode,
            depth: 1,
        },
        {
            reference: `${nodeId}.mount_path`,
            label: 'mount_path',
            nodeId,
            path: 'mount_path',
            valueType: 'string',
            value: fsOutput.mount_path,
            depth: 1,
        },
    ];
}

function validateReference(
    output: JsonValue,
    path: string
): { valid: boolean; error?: string } {
    const fsOutput = asFilesystemOutput(output);
    if (!fsOutput) return { valid: false, error: 'No filesystem output' };

    if (path === 'volume_mode' || path === 'mount_path' || path === 'node_id') {
        return { valid: true };
    }

    return { valid: false, error: `Unknown path: ${path}` };
}

const FilesystemOutputPanelContent = ({ output }: OutputPanelContentProps) => {
    const fsOutput = asFilesystemOutput(output);

    if (!fsOutput) {
        return (
            <div className="p-3 text-sm text-muted-foreground dark:text-zinc-500">
                No output yet. Connect to an agent to provide persistent
                storage.
            </div>
        );
    }

    return (
        <div className="p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 font-medium">
                <FolderOpen className="w-3 h-3" />
                Persistent Volume
            </div>
            <div className="space-y-1 text-xs text-muted-foreground">
                <div>
                    <span className="text-muted-foreground dark:text-zinc-500">Mount path: </span>
                    <span className="text-foreground/80 font-mono">
                        {fsOutput.mount_path}
                    </span>
                </div>
                <div>
                    <span className="text-muted-foreground dark:text-zinc-500">Mode: </span>
                    <span className="text-foreground/80">
                        {fsOutput.volume_mode === 'common'
                            ? 'Shared'
                            : 'Per conversation key'}
                    </span>
                </div>
            </div>
        </div>
    );
};

export const filesystemDisplayStrategy: NodeDisplayStrategy = {
    buildSuggestions,
    validateReference,
    OutputPanelContent: FilesystemOutputPanelContent,
};

// ============================================================================
// Node Component
// ============================================================================

const FilesystemNodeComponent = ({ data, selected }: NodeProps) => {
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
                        <FolderOpen
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

export const FilesystemNode: NodeDefinition = {
    type: 'filesystem',
    label: 'Filesystem',
    description: 'Persistent storage for agents',
    keywords: ['files', 'file storage', 'disk', 'volume', 'persistent storage', 'memory', 'workspace', 'sandbox', 'upload file'],
    Icon: FolderOpen,
    iconColor: 'text-amber-600 dark:text-amber-400',
    dimensions: DIMENSIONS,
    component: memo(FilesystemNodeComponent, (prev, next) => {
        return (
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput
        );
    }),
    displayStrategy: filesystemDisplayStrategy,
    skipAutoMemo: true,
};
