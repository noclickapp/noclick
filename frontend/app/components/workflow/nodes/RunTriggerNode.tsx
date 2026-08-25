// Run trigger node definition.
// Acts as the deterministic entry point when users click "Run".
// Highest-priority trigger node — when present, execution starts here.
// Theme-toned body with a subtle edge glow and a filled play icon.

import { memo } from 'react';
import { NodeProps, Handle, Position } from '@xyflow/react';
import { NodeSpinner } from './base/NodeSpinner';
import { TriggerBoltBadge } from './base/TriggerBoltBadge';
import { NodeDefinition } from './types';
import { perfState } from '~/lib/perf-state';

const DIMENSIONS = { width: 90, height: 90, iconSize: 68 };

// Filled play triangle — solid fill, not a stroked outline
const PlayFilled = ({
    className,
    style,
}: {
    className?: string;
    style?: React.CSSProperties;
}) => (
    <svg
        viewBox="0 0 24 24"
        fill="currentColor"
        className={className}
        style={style}
    >
        <path d="M8 5.14v14l11-7-11-7z" />
    </svg>
);

const RunTriggerNodeComponent = ({ id, data, selected }: NodeProps) => {
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';

    return (
        <div
            className="relative"
            style={{ width: DIMENSIONS.width, height: DIMENSIONS.height }}
        >
            {/* Output Handle */}
            <Handle
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Trigger family marker — manual Run is a trigger too (no input) */}
            <TriggerBoltBadge />

            {/* Main Container */}
            <div
                className={`
                    group relative w-full rounded-2xl overflow-hidden
                    bg-card dark:bg-[linear-gradient(145deg,#1a1a1a_0%,#0a0a0a_100%)]
                    ${shouldOptimize ? 'transition-none' : 'transition-all duration-300 ease-out'}
                    ${
                        selected
                            ? 'border-2 border-foreground shadow-2xl shadow-foreground/25 scale-105'
                            : isRunning
                              ? 'border-2 border-foreground/60 shadow-lg shadow-foreground/10'
                              : isError
                                ? 'border-2 border-red-500/60 shadow-lg shadow-red-500/20'
                                : 'border border-border dark:border-white/[0.12] shadow-lg dark:shadow-black/50 hover:shadow-2xl hover:border-foreground/25 hover:shadow-foreground/10'
                    }
                `}
                style={{
                    height: DIMENSIONS.height,
                }}
            >
                {/* Subtle top-edge highlight for depth */}
                <div
                    className="absolute inset-x-0 top-0 h-px pointer-events-none"
                    style={{
                        background:
                            'linear-gradient(90deg, transparent, hsl(var(--foreground) / 0.08), transparent)',
                    }}
                />

                {/* Icon centered */}
                <div className="absolute inset-0 flex items-center justify-center">
                    <NodeSpinner
                        isLoading={isRunning}
                        spinnerRadius={DIMENSIONS.iconSize * 0.65}
                    >
                        <PlayFilled
                            className={`relative z-10 text-foreground ${shouldOptimize ? '' : 'transition-all duration-500'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                            style={{
                                width: DIMENSIONS.iconSize,
                                height: DIMENSIONS.iconSize,
                                filter: 'drop-shadow(0 2px 8px hsl(var(--foreground) / 0.15))',
                            }}
                        />
                    </NodeSpinner>
                </div>
            </div>
        </div>
    );
};

export const RunTriggerNode: NodeDefinition = {
    type: 'trigger-run',
    label: 'Run',
    description: 'Manual Run Trigger',
    keywords: ['run', 'manual', 'start', 'button', 'trigger manually', 'test run', 'on demand'],
    Icon: PlayFilled as any,
    iconColor: 'text-foreground',
    dimensions: DIMENSIONS,
    component: memo(RunTriggerNodeComponent),
};
