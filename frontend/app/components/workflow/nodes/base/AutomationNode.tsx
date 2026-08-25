// AutomationNode component for rendering automation workflow nodes.
// This component displays automation nodes (Telegram, Gmail, etc.) with their icons.
// When being edited by AI, expands to show edit status with animated transitions.
// Note: Labels are rendered by withCollaborativeBorder HOC via NodeToolbar, not here.

import { memo, useEffect } from 'react';
import {
    NodeProps,
    Handle,
    Position,
    useUpdateNodeInternals,
} from '@xyflow/react';
import { IconType } from 'react-icons';
import { LucideIcon, Ban, Wrench } from 'lucide-react';
import { NodeStatusBadge } from './NodeStatusBadge';
import { TriggerBoltBadge } from './TriggerBoltBadge';
import type { SvgIconComponent } from '../types';
import { perfState } from '~/lib/perf-state';
import { cn } from '~/lib/utils';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { useIsMobile } from '~/hooks/useIsMobile';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeSchemas';
import { getNodeHandleLayout } from './nodeHandles';
import {
    useNodeEditingState,
    NodeEditOverlay,
    EDIT_EXPANDED_WIDTH,
    EDIT_EXPANDED_HEIGHT,
} from './nodeEditing';
import type { NodeEditInfo } from '~/components/workflow/WorkflowContext';

function isNodeEditInfo(value: unknown): value is NodeEditInfo {
    if (!value || typeof value !== 'object') return false;
    const candidate = value as { status?: unknown; action?: unknown };
    return (
        (candidate.status === 'processing' || candidate.status === 'complete') &&
        (candidate.action === 'added' ||
            candidate.action === 'removed' ||
            candidate.action === 'updated')
    );
}

interface AutomationNodeProps extends NodeProps {
    Icon: IconType | LucideIcon | SvgIconComponent; // Icon component to render
    iconColor: string; // Tailwind color class for icon
    width?: number; // Node width (default: 90)
    height?: number; // Node height (default: 90)
    iconSize?: number; // Icon size (default: 48)
    hideLeftHandle?: boolean; // Hide the left input handle
    hideRightHandle?: boolean; // Hide the right output handle
    bgGradient?: string; // Custom background gradient (overrides default)
    caption?: string; // Optional compact summary pill at the card's bottom edge (e.g. a cron schedule)
}

// Default dimensions for automation nodes
const DEFAULT_WIDTH = 90;
const DEFAULT_HEIGHT = 90;
// Dimensions for expanded editing state — imported from nodeEditing.tsx (shared
// with the xyflow-free ForkCanvas) so the expand animation matches in both.
const EXPANDED_WIDTH = EDIT_EXPANDED_WIDTH;
const EXPANDED_HEIGHT = EDIT_EXPANDED_HEIGHT;

const AutomationNode = ({
    id,
    type,
    data,
    selected,
    Icon,
    iconColor,
    iconSize = 48,
    hideLeftHandle = false,
    hideRightHandle = false,
    bgGradient,
    caption,
}: AutomationNodeProps) => {
    // Read perfState directly without subscription - avoids re-render overhead
    // The blur will be disabled on next paint after shouldOptimize changes
    const shouldOptimize = perfState.shouldOptimize;
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    // Run-status visuals (running sweep + completed/failed ring, glow, badge, pulse)
    // are drawn by the shared NodeAuroraLayers overlay in withNodeWrapper, so every
    // node type gets them identically — this component no longer renders its own.
    const isDisabled = data?.disabled === true;
    const configValid = data?.configValid !== false; // Default to true if not specified
    const hasMockedOutput = data?.mockedOutput != null;
    // Error output handle: appears when the user picks "Continue (Error Output)"
    // in NodeSettings. `_settings` is a regular config field, always at data.config._settings.
    const dataConfig = (data as Record<string, unknown> | undefined)?.config as
        | Record<string, unknown>
        | undefined;
    const nodeSettings =
        (dataConfig?._settings as Record<string, unknown> | undefined) ?? {};
    const errorOutputEnabled = nodeSettings.onError === 'continueErrorOutput';
    // Top source handle for wiring this node into an AI agent's bottom handle
    // as a tool provider (node_op tools). Only on schema-qualified types.
    const isToolProvider = isAgentToolProviderType(type);
    // Trigger mode: dedicated trigger-* types, or an integration node whose
    // SELECTED operation is a trigger (x-is-trigger) — config-dependent, so it
    // tracks data.operation. Triggers are entry points: nothing flows into
    // them, so the input handle is replaced by the amber bolt. The provider
    // (top) handle goes too — trigger and provider roles are either-or
    // (workflow_ops.trigger_provider_conflict), so the handle could never
    // legally connect.
    const isTrigger = isTriggerSource(
        type,
        (data as Record<string, unknown> | undefined)?.operation as
            | string
            | undefined
    );
    // Handle topology comes from the shared helper, so this node's dot set stays in
    // lockstep with the xyflow-free ForkCanvas (which has no <Handle> to read).
    const handleLayout = getNodeHandleLayout(
        type,
        (data as Record<string, unknown> | undefined)?.operation as
            | string
            | undefined,
        { hideLeft: hideLeftHandle, hideRight: hideRightHandle }
    );
    const showInputHandle = handleLayout.input;
    const showTopHandle = handleLayout.provider;
    // Actions allowlisted for an agent (set by the allowlist picker when the
    // node is wired as a tool provider) — surfaced as a count chip by the
    // top handle so providers are recognizable without opening the config.
    const agentToolOps = dataConfig?.agent_tool_operations;
    const agentToolCount =
        isToolProvider && Array.isArray(agentToolOps) ? agentToolOps.length : 0;
    // Read-only context (set by ReadOnlyFlowCanvas / replay state via createWorkflowNode extras).
    // In read-only previews AI editing can't happen and there's no live state to update, so we
    // skip the per-node setInterval polling, the per-mount rAF loop that calls
    // updateNodeInternals, and the backdrop-blur layer.
    const isReadOnly = data?.isReadOnly === true;
    const previewEditInfo = isNodeEditInfo(data?._previewEditInfo)
        ? data._previewEditInfo
        : null;
    const isMobile = useIsMobile();

    // Hook to notify ReactFlow when node dimensions change (for handle/edge recalculation)
    const updateNodeInternals = useUpdateNodeInternals();

    // AI editing state — shared with ForkCanvas via the useNodeEditingState hook so
    // the polling logic + status interpretation lives in one place.
    const { isBeingEdited, editInfo, remoteEditorName } = useNodeEditingState(
        id,
        { skip: isReadOnly && !previewEditInfo, previewEditInfo }
    );

    // Notify ReactFlow to recalculate handle positions and edges when dimensions change.
    // Continuously update during CSS transition so edges animate smoothly with the node.
    // Skip entirely in read-only mode (no editing, no expand/collapse animation, nothing
    // to recalc) — at 13 nodes this is 13 simultaneous rAF loops × ~18 frames each on
    // mobile mount, which alone is enough to OOM the WebContent process.
    useEffect(() => {
        if (isReadOnly && !previewEditInfo) return;
        const transitionDuration = 300; // matches CSS transition duration
        const startTime = performance.now();
        let rafId: number;

        const updateDuringTransition = () => {
            updateNodeInternals(id);
            const elapsed = performance.now() - startTime;
            if (elapsed < transitionDuration) {
                rafId = requestAnimationFrame(updateDuringTransition);
            }
        };

        rafId = requestAnimationFrame(updateDuringTransition);

        // Final update after transition completes
        const timer = setTimeout(() => {
            updateNodeInternals(id);
        }, transitionDuration + 20);

        return () => {
            cancelAnimationFrame(rafId);
            clearTimeout(timer);
        };
    }, [
        isBeingEdited,
        errorOutputEnabled,
        isTrigger,
        id,
        updateNodeInternals,
        isReadOnly,
        previewEditInfo,
    ]);

    // Calculate dimensions based on editing state
    // Note: Don't include LABEL_HEIGHT in the node's official height - the label is positioned
    // outside the node bounds (overflow: visible) so clicks on it don't trigger node selection
    // IMPORTANT: Use DEFAULT_WIDTH/HEIGHT constants for collapsed state, not the measured width/height
    // from ReactFlow props. ReactFlow caches measured dimensions, so if we expand to 220px during editing,
    // propWidth would become 220. Using constants ensures nodes collapse back to their original size.
    const currentWidth = isBeingEdited ? EXPANDED_WIDTH : DEFAULT_WIDTH;
    const currentHeight = isBeingEdited ? EXPANDED_HEIGHT : DEFAULT_HEIGHT;

    // Read-only short-circuit: render a flat card with no shimmer, no glow, no
    // gradient mesh, no drop-shadow filter, no infinite animation, no hover transforms,
    // no box-shadow. Each of those is a GPU compositing layer; ~37 nodes × 5+ layers
    // each blows the iPhone WebContent process budget. Bisecting against synthetic
    // ReactFlow stress tests showed a flat div + icon (~1 layer per node) is the
    // densest content that fits — see docs/mobile/canvas-tile-cache.md for the full story.
    //
    // GATED ON MOBILE: the flat render is only correct for the mobile public-share
    // viewer (WebKit memory crisis). On desktop, read-only surfaces — the desktop
    // public share AND execution-log replay — render the full node treatment so the
    // selection border, status badges, and overall feel match the live canvas.
    // (Mutation affordances like the run/delete pills are gated separately by
    // withNodeWrapper's `showAffordances && !isReadOnly` / `showDelete && !isReadOnly`.)
    if (isReadOnly && isMobile) {
        return (
            <div
                className="relative"
                style={{ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }}
            >
                {showInputHandle && (
                    <Handle
                        type="target"
                        position={Position.Left}
                        className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500"
                        style={{ zIndex: 10 }}
                    />
                )}
                {isTrigger && <TriggerBoltBadge />}
                {!hideRightHandle && (
                    <Handle
                        type="source"
                        position={Position.Right}
                        className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500"
                        style={{
                            top: errorOutputEnabled ? '35%' : '50%',
                            zIndex: 10,
                        }}
                    />
                )}
                {!hideRightHandle && errorOutputEnabled && (
                    <Handle
                        id="error"
                        type="source"
                        position={Position.Right}
                        className="!w-4 !h-4 !bg-red-400 !border-2 !border-red-500"
                        style={{ top: '70%', zIndex: 10 }}
                    />
                )}
                {showTopHandle && (
                    <Handle
                        id="top"
                        type="source"
                        position={Position.Top}
                        className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500"
                        style={{ zIndex: 10 }}
                    />
                )}
                <div
                    className="w-full h-full rounded-2xl flex items-center justify-center border border-border dark:border-zinc-700/40 overflow-hidden bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]"
                    style={{
                        background: bgGradient,
                        opacity: isDisabled ? 0.4 : hasMockedOutput ? 0.65 : 1,
                    }}
                >
                    <BrandIcon
                        Icon={Icon}
                        iconColor={isDisabled ? '' : iconColor}
                        className={cn(
                            'relative z-10',
                            isDisabled && 'opacity-35'
                        )}
                        style={{ width: iconSize, height: iconSize }}
                    />
                </div>
            </div>
        );
    }

    return (
        <div
            className="relative"
            style={{
                width: currentWidth,
                height: currentHeight,
                transition:
                    isRunning || shouldOptimize
                        ? 'none'
                        : 'width 300ms ease-out, height 300ms ease-out',
            }}
        >
            {/* Input Handle — absent on triggers (nothing flows into an entry
                point); the bolt badge marks where events come in instead */}
            {showInputHandle && (
                <Handle
                    type="target"
                    position={Position.Left}
                    className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                    style={{ zIndex: 10 }}
                />
            )}
            {isTrigger && !isBeingEdited && <TriggerBoltBadge />}

            {/* Output Handle (success) — shifted up when an error handle is also rendered */}
            {!hideRightHandle && (
                <Handle
                    type="source"
                    position={Position.Right}
                    className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                    style={{
                        top: errorOutputEnabled ? '35%' : '50%',
                        zIndex: 10,
                    }}
                />
            )}

            {/* Error Output Handle — only rendered when _settings.onError === 'continueErrorOutput'.
                Edges drawn from this handle carry the error payload from a failed node execution. */}
            {!hideRightHandle && errorOutputEnabled && (
                <>
                    <Handle
                        id="error"
                        type="source"
                        position={Position.Right}
                        className="!w-4 !h-4 !bg-red-400 !border-2 !border-red-500 hover:!bg-red-300 hover:!border-red-400 transition-all opacity-80 hover:opacity-100"
                        style={{ top: '70%', zIndex: 10 }}
                        title="Error output — receives the error payload when the node fails"
                    />
                    <div
                        className="absolute text-[9px] font-medium text-red-600/90 dark:text-red-400/90 pointer-events-none select-none px-1 py-px rounded bg-popover/95"
                        style={{
                            right: -38,
                            top: '70%',
                            transform: 'translateY(-50%)',
                            zIndex: 5,
                        }}
                    >
                        error
                    </div>
                </>
            )}

            {/* Top Handle — connects this node to an AI agent's bottom handle as a
                tool provider (its allowlisted operations become agent tools) */}
            {showTopHandle && (
                <Handle
                    id="top"
                    type="source"
                    position={Position.Top}
                    className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                    style={{ zIndex: 10 }}
                    title="Connect to an AI agent to expose this node's actions as tools"
                />
            )}

            {/* Allowlisted-actions chip — offset right of the top handle.
                Hidden while selected (the "↵ to edit" hint renders above the
                node center) and whenever a corner status badge occupies the
                same zone: errored/incomplete (NodeStatusBadge) or a persisted
                run result (NodeAuroraLayers' ✓/✗ badge keyed on _lastRunStatus). */}
            {agentToolCount > 0 &&
                !isTrigger &&
                !isBeingEdited &&
                !selected &&
                !isError &&
                configValid &&
                !data?._lastRunStatus && (
                    <div
                        className="absolute flex items-center gap-1 px-1.5 py-px rounded-full bg-popover/95 border border-border dark:border-zinc-700/60 text-[9px] font-medium text-foreground/80 pointer-events-none select-none"
                        style={{
                            top: -9,
                            left: '50%',
                            marginLeft: 14,
                            zIndex: 20,
                        }}
                        title={`${agentToolCount} action(s) exposed to the connected AI agent`}
                    >
                        <Wrench className="w-2 h-2" />
                        {agentToolCount}
                    </div>
                )}

            {/* Error Badge - shown when node execution failed (takes precedence over config badge) */}
            {isError && !isBeingEdited && <NodeStatusBadge variant="error" />}

            {/* Config Status Badge - only show if not disabled, not errored, and not editing */}
            {!isError && !isDisabled && !configValid && !isBeingEdited && (
                <NodeStatusBadge variant="incomplete" />
            )}

            {/* Main Container - visual node box (excludes label area) */}
            <div
                className={`
                    group relative w-full rounded-2xl overflow-hidden
                    bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]
                    ${isRunning || shouldOptimize ? 'transition-none' : 'transition-all duration-300 ease-out'}
                    ${
                        isBeingEdited
                            ? 'border border-border dark:border-white/[0.08] shadow-lg'
                            : selected
                              ? // A selected node always reads as full-foreground — the clearest
                                // selection cue — even when it's errored or incomplete
                                // (those colors return as soon as it's deselected).
                                `border-2 border-primary dark:border-foreground shadow-2xl shadow-primary/20 dark:shadow-foreground/20 ${isReadOnly ? '' : 'scale-105'}`
                              : isError
                                ? 'border-2 border-red-500/60 shadow-lg shadow-red-500/20'
                                : !configValid
                                  ? 'border-2 border-amber-500/50 shadow-lg shadow-amber-500/15'
                                  : 'border border-border dark:border-zinc-700/40 shadow-lg hover:shadow-2xl hover:border-foreground/30 hover:shadow-foreground/10'
                    }
                `}
                style={{
                    height: isBeingEdited ? EXPANDED_HEIGHT : DEFAULT_HEIGHT,
                    background: bgGradient,
                    // Lower opacity when using mock data — suppressed in read-only
                    // surfaces (replay / share view) where the mock state is a
                    // configuration detail, not an active editing cue, and a mix
                    // of dimmed + full-opacity nodes reads as visual inconsistency.
                    opacity:
                        hasMockedOutput && !isBeingEdited && !isReadOnly
                            ? 0.65
                            : 1,
                }}
            >
                {/* Non-editing state: centered icon */}
                {!isBeingEdited && (
                    <>
                        {/* Animated background gradient mesh — a dark-body depth cue; on the
                            white light-mode body it reads as a gray inner shadow, so it's
                            gated to dark only. */}
                        <div
                            className={`absolute inset-0 opacity-0 dark:opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'dark:opacity-60' : 'dark:group-hover:opacity-50'}`}
                            style={{
                                background:
                                    'radial-gradient(circle at 70% 70%, rgba(120, 113, 108, 0.15), transparent 50%)',
                            }}
                        />

                        {/* Glass overlay with noise texture - disable blur during drag and on
                            MOBILE read-only previews (each backdrop-blur creates its own GPU
                            layer, and N backdrop-blur layers reliably crash mobile WebKit).
                            Desktop read-only surfaces (replay, public share) keep the blur so
                            nodes look identical to the live canvas. */}
                        {/* No own rounded-2xl: a 16px radius curves in MORE than the
                            bordered body's 14px inner clip, leaving a corner sliver. Drop
                            it and let the parent's overflow-hidden clip to the exact shape. */}
                        <div
                            className={`absolute inset-0 rounded-[14px] bg-gradient-to-br from-white/[0.08] via-transparent to-transparent pointer-events-none opacity-0 dark:opacity-100 ${shouldOptimize || (isReadOnly && isMobile) ? '' : 'dark:backdrop-blur-[2px]'}`}
                        />

                        {/* Inner soft glow — a dark-body inner highlight. inset-0 (not [1px])
                            + no own radius so it's clipped to the bordered corner, not
                            slivering. Dark only. */}
                        <div
                            className={`absolute inset-0 bg-gradient-radial from-white/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-0 dark:opacity-100' : 'opacity-0 dark:group-hover:opacity-70'}`}
                        />

                        {/* Multi-layer shimmer effect - subtle and elegant */}
                        <div className="absolute inset-0 rounded-2xl overflow-hidden pointer-events-none">
                            {/* Primary shimmer sweep */}
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
                            {/* Secondary diffuse glow */}
                            <div
                                className="absolute inset-0 opacity-0 group-hover:opacity-40 transition-opacity duration-500"
                                style={{
                                    background:
                                        'radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.04) 0%, transparent 70%)',
                                }}
                            />
                        </div>

                        {/* Icon + MOCK label container - absolutely centered when mocked */}
                        <div
                            className={`absolute inset-0 flex flex-col items-center justify-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                            style={{
                                transform: hasMockedOutput
                                    ? 'scale(0.7)'
                                    : 'scale(1)',
                            }}
                        >
                            <BrandIcon
                                Icon={Icon}
                                iconColor={isDisabled ? '' : iconColor}
                                className={cn(
                                    'relative z-10',
                                    !shouldOptimize &&
                                        'transition-all duration-500',
                                    isDisabled && 'opacity-35',
                                    selected
                                        ? 'scale-115 brightness-110'
                                        : 'group-hover:scale-110 group-hover:brightness-105'
                                )}
                                style={{
                                    width: iconSize,
                                    height: iconSize,
                                    // invert(var(--brand-invert,0)) composes with the shadow so
                                    // monochrome marks (.brand-mono sets the var) flip in light.
                                    filter: isDisabled
                                        ? 'grayscale(100%) brightness(0.4) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))'
                                        : 'invert(var(--brand-invert, 0)) drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))',
                                }}
                            />
                            {/* MOCK label - part of the centered flex column */}
                            {hasMockedOutput && (
                                <div className="text-[18px] font-bold tracking-widest text-foreground mt-0.5 dark:[text-shadow:0_2px_6px_rgba(0,0,0,0.9)]">
                                    MOCK
                                </div>
                            )}
                            {/* Caption pill - lives inside the centered column so
                                the icon + chip render as one vertically-centered
                                group (no empty space above the icon). */}
                            {caption && (
                                <span className="mt-1 max-w-[80px] truncate rounded-full border border-border dark:border-zinc-700/60 bg-popover/90 px-1.5 py-px text-[8px] font-medium leading-tight text-foreground/80 pointer-events-none">
                                    {caption}
                                </span>
                            )}
                        </div>

                        {/* Disabled Overlay - centered over the icon */}
                        {isDisabled && (
                            <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                                <Ban
                                    className="text-muted-foreground dark:text-zinc-500 opacity-50"
                                    style={{
                                        width: iconSize * 1.15,
                                        height: iconSize * 1.15,
                                    }}
                                />
                            </div>
                        )}
                    </>
                )}

                {/* Editing state: expanded with icon on left, status on right */}
                {isBeingEdited && (
                    <NodeEditOverlay
                        Icon={Icon}
                        iconColor={iconColor}
                        editInfo={editInfo}
                        remoteEditorName={remoteEditorName}
                    />
                )}
            </div>
        </div>
    );
};

// Memoize to prevent unnecessary re-renders
const readOnError = (d: unknown): unknown => {
    const data = d as Record<string, unknown> | undefined;
    const settings = (data?.config as Record<string, unknown> | undefined)
        ?._settings as Record<string, unknown> | undefined;
    return settings?.onError;
};

// Allowlist length drives the actions chip — compare by count so picker edits
// re-render the node without breaking memoization on unrelated config churn.
const readAgentToolOpsCount = (d: unknown): number => {
    const data = d as Record<string, unknown> | undefined;
    const ops = (data?.config as Record<string, unknown> | undefined)
        ?.agent_tool_operations;
    return Array.isArray(ops) ? ops.length : 0;
};

export default memo(AutomationNode, (prev, next) => {
    return (
        prev.id === next.id &&
        prev.Icon === next.Icon &&
        prev.iconColor === next.iconColor &&
        prev.selected === next.selected &&
        prev.width === next.width &&
        prev.height === next.height &&
        prev.iconSize === next.iconSize &&
        prev.hideLeftHandle === next.hideLeftHandle &&
        prev.hideRightHandle === next.hideRightHandle &&
        prev.bgGradient === next.bgGradient &&
        prev.caption === next.caption &&
        prev.data?.executionState === next.data?.executionState &&
        // Operation drives trigger-mode visuals (shape, bolt badge, hidden input handle)
        prev.data?.operation === next.data?.operation &&
        prev.data?.configValid === next.data?.configValid &&
        prev.data?.disabled === next.data?.disabled &&
        prev.data?.mockedOutput === next.data?.mockedOutput &&
        prev.data?.label === next.data?.label &&
        prev.data?._previewEditInfo === next.data?._previewEditInfo &&
        prev.data?._lastRunStatus === next.data?._lastRunStatus &&
        readOnError(prev.data) === readOnError(next.data) &&
        readAgentToolOpsCount(prev.data) === readAgentToolOpsCount(next.data)
    );
});
