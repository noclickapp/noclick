// AI Agent node definition.
// Displays AI agent workflow nodes with integrated model selection dropdown.
// When being edited by AI, expands to show edit status with animated transitions.

import { memo, useCallback, useState, useEffect } from 'react';
import { useSnapshot } from 'valtio';
import {
    NodeProps,
    Handle,
    Position,
    useUpdateNodeInternals,
} from '@xyflow/react';
import {
    Bot,
    Ban,
    ChevronDown,
    Loader2,
    CheckCircle2,
    MessageSquare,
} from 'lucide-react';
import { agentPresenceStore } from '~/lib/agentPresenceStore';
import {
    Tooltip,
    TooltipTrigger,
    TooltipContent,
    TooltipProvider,
} from '~/components/ui/tooltip';
import { NodeStatusBadge } from './base/NodeStatusBadge';
import { AgentModelIcon } from './base/AgentModelIcon';
import { CanvasDropTarget } from '~/components/workflow/CanvasDropTarget';
import { canFeedAgentBottom } from '~/utils/nodeSchemas';
import {
    NodeDefinition,
    OutputPanelContentProps,
    ReferenceSuggestion,
} from './types';
import { useModels } from '~/hooks/useModels';
import { ModelPickerModal } from '~/components/workflow/ModelPickerModal';
import { bumpedIconScale } from '~/components/chat/ModelDropdown';
import { modelShortName } from '~/lib/modelFiltering';
import { getProviderMetadata } from '~/types/provider';
import { NodeSpinner } from './base/NodeSpinner';
import { IODataDisplay } from '../IODataDisplay';
import {
    useWorkflowId,
    isNodeBeingEdited,
    getIsAiEditing,
    getNodeEditInfo,
    isNodeBeingEditedByRemote,
    type NodeEditInfo,
} from '../WorkflowContext';
import { perfState } from '~/lib/perf-state';
import { DEFAULT_AGENT_MODEL } from '~/lib/agentChat';
import { seedWrapperSubmodel } from '~/lib/agentCredentialModel';
import { agentOutputMedia } from '~/lib/agentOutputMedia';
import { HARNESS_BRANDS } from '~/lib/harnessBrand';

// CLI agent models pinned to the top of the model dropdown when opened from
// inside an agent node, since they're the most useful options here.
const AGENT_NODE_PRIORITY_MODELS = [
    'codex',
    'claude-code',
    'opencode',
    'openclaw',
    'hermes',
] as const;
const OPENCLAW_MARKER_ICON_SRC = HARNESS_BRANDS.openclaw.markSrc;
const HERMES_MARKER_ICON_SRC = HARNESS_BRANDS.hermes.markSrc;

// Component that renders the agent node with model management
const AIAgentNodeComponent = (props: NodeProps) => {
    const { models, getModelById } = useModels();
    const workflowId = useWorkflowId();
    const { id, selected, data, type } = props;
    // The workflow relay publishes each live local CLI turn. This is
    // transient viewer state, so it never writes into the workflow graph.
    const nodePresence = useSnapshot(agentPresenceStore).byNode[id];
    const agentCount = nodePresence?.count ?? 0;
    const agentBusy = nodePresence?.busy ?? false;
    const config = (data?.config ?? {}) as Record<string, any>;
    const model = (config.model as string) ?? DEFAULT_AGENT_MODEL;
    // isOpenClaw / isHermes drive the model-picker trigger's marker icon below;
    // the main node logo is resolved inside AgentModelIcon from `model` directly.
    const isOpenClaw = model === 'openclaw';
    const isHermes = model.includes('hermes') || model.includes('nousresearch');
    const executionState = data?.executionState || 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const isDisabled = data?.disabled === true;
    // Read-only render (e.g. the marketing/auth agent-scaffold preview) has no app
    // runtime, so hover action affordances like the Chat pill must not appear.
    const isReadOnly = data?.isReadOnly === true;
    const hasPreviewEditState = Object.prototype.hasOwnProperty.call(
        data ?? {},
        '_previewEditInfo'
    );
    const previewEditInfo = data?._previewEditInfo as
        | NodeEditInfo
        | null
        | undefined;
    const configValid = data?.configValid !== false; // Default to true if not specified
    const hasMockedOutput = data?.mockedOutput != null;
    const shouldOptimize = perfState.shouldOptimize;
    const [showModelPicker, setShowModelPicker] = useState(false);

    // Hook to notify ReactFlow when node dimensions change (for handle/edge recalculation)
    const updateNodeInternals = useUpdateNodeInternals();

    // AI editing state - subscribe to changes via interval since WorkflowContext uses module-level store
    // Also checks for remote collaborator AI editing to show their animations
    // Seeded from the preview prop so a node that mounts already-editing paints
    // its expanded card on the FIRST frame: an effect-only state leaves the
    // canvas measuring the un-edited size and framing a graph the card is about
    // to outgrow, which crops it at the canvas edge.
    const [isBeingEdited, setIsBeingEdited] = useState(
        () => hasPreviewEditState && previewEditInfo != null
    );
    const [editInfo, setEditInfo] = useState<NodeEditInfo | undefined>(() =>
        hasPreviewEditState ? (previewEditInfo ?? undefined) : undefined
    );
    const [remoteEditorName, setRemoteEditorName] = useState<
        string | undefined
    >(undefined);
    useEffect(() => {
        // Check editing state periodically (more reliable than listeners for ReactFlow nodes)
        const checkEditState = () => {
            if (hasPreviewEditState) {
                setIsBeingEdited(previewEditInfo != null);
                setEditInfo(previewEditInfo ?? undefined);
                setRemoteEditorName(undefined);
                return;
            }
            // Check local AI editing first
            const localEditing =
                getIsAiEditing() && isNodeBeingEdited(props.id);
            if (localEditing) {
                setIsBeingEdited(true);
                setEditInfo(getNodeEditInfo(props.id));
                setRemoteEditorName(undefined);
                return;
            }

            // Check remote collaborator AI editing
            const remoteEdit = isNodeBeingEditedByRemote(props.id);
            if (remoteEdit) {
                setIsBeingEdited(true);
                setEditInfo(remoteEdit.info);
                setRemoteEditorName(remoteEdit.userName);
                return;
            }

            // Not being edited
            setIsBeingEdited(false);
            setEditInfo(undefined);
            setRemoteEditorName(undefined);
        };
        checkEditState();
        const interval = setInterval(checkEditState, 100);
        return () => clearInterval(interval);
    }, [hasPreviewEditState, previewEditInfo, props.id]);

    // Notify ReactFlow to recalculate handle positions and edges when dimensions change
    // Continuously update during CSS transition so edges animate smoothly with the node
    useEffect(() => {
        const transitionDuration = 300; // matches CSS transition duration
        const startTime = performance.now();
        let rafId: number;

        const updateDuringTransition = () => {
            updateNodeInternals(props.id);
            const elapsed = performance.now() - startTime;
            if (elapsed < transitionDuration) {
                rafId = requestAnimationFrame(updateDuringTransition);
            }
        };

        rafId = requestAnimationFrame(updateDuringTransition);

        // Final update after transition completes
        const timer = setTimeout(() => {
            updateNodeInternals(props.id);
        }, transitionDuration + 20);

        return () => {
            cancelAnimationFrame(rafId);
            clearTimeout(timer);
        };
    }, [isBeingEdited, props.id, updateNodeInternals]);

    // Get status text for editing view (includes remote editor name if applicable)
    const getStatusText = () => {
        const prefix = remoteEditorName ? `${remoteEditorName}: ` : '';
        if (!editInfo) return `${prefix}Processing...`;
        if (editInfo.status === 'complete') {
            const action =
                editInfo.action === 'added'
                    ? 'Added'
                    : editInfo.action === 'removed'
                      ? 'Removed'
                      : 'Updated';
            return `${prefix}${action}`;
        }
        const action =
            editInfo.action === 'added'
                ? 'Adding...'
                : editInfo.action === 'removed'
                  ? 'Removing...'
                  : 'Updating...';
        return `${prefix}${action}`;
    };

    // Calculate dimensions based on editing state
    // Note: Labels are rendered by withCollaborativeBorder HOC via NodeToolbar, not here
    const EXPANDED_WIDTH = 260;
    const NORMAL_WIDTH = 200;
    const NORMAL_HEIGHT = 140;
    const currentWidth = isBeingEdited ? EXPANDED_WIDTH : NORMAL_WIDTH;
    const currentHeight = NORMAL_HEIGHT;

    // Route node-data writes through FlowCanvas's broadcasting handler (the
    // same channel NodeLabel uses for inline label edits) instead of a raw
    // useReactFlow().setNodes. A bare setNodes only mutates the local canvas
    // and never calls broadcastNodeUpdate, so on-node edits (model, chat
    // toggle) would silently fail to reach live collaborators.
    const updateNodeData = useCallback(
        (data: Record<string, any>) => {
            document.dispatchEvent(
                new CustomEvent('noclick:node:update-data', {
                    detail: { nodeId: props.id, data },
                })
            );
        },
        [props.id]
    );

    // Canvas "Chat" pill on the agent node. Enables show_in_interface so
    // the AgentChatBlock will be derived on the Interface tab, then asks
    // FlowCanvas to switch tabs and make this agent's block the active
    // sub-tab. The dispatcher pattern keeps the per-node component free of
    // direct FlowCanvas refs.
    const handleOpenChat = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            const isEnabled =
                config.show_in_interface === 'true' ||
                config.show_in_interface === true;
            if (!isEnabled) {
                updateNodeData({ config: { show_in_interface: 'true' } });
            }
            document.dispatchEvent(
                new CustomEvent('noclick:open-agent-chat', {
                    detail: { nodeId: props.id },
                })
            );
        },
        [config.show_in_interface, props.id, updateNodeData]
    );

    const handleModelChange = useCallback(
        (modelId: string) => {
            console.log(
                `Changing model for agent node ${props.id} to ${modelId}`
            );

            // Write the `model__label` sidecar alongside `model` so NodeConfig's
            // DynamicOptionsField doesn't keep displaying a stale label from a
            // prior in-config selection until that dropdown is reopened.
            const label = getModelById(modelId)?.name || modelId;
            // Seed the wrapper harness's default sub-model so the credential form +
            // sub-model picker resolve a concrete provider instead of the bare
            // wrapper id (no-op for regular models / already-set sub-models). Read
            // the guard value from the stable `data` prop, not the render-computed
            // `config` object, so this callback isn't recreated every render.
            updateNodeData({
                config: {
                    model: modelId,
                    model__label: label,
                    ...seedWrapperSubmodel(
                        modelId,
                        data?.config as Record<string, unknown> | undefined
                    ),
                },
            });
        },
        [updateNodeData, getModelById, data, props.id]
    );

    return (
        <div
            className="relative group"
            style={{
                width: currentWidth,
                height: currentHeight,
                transition: isRunning
                    ? 'none'
                    : 'width 300ms ease-out, height 300ms ease-out',
            }}
        >
            {/* Canvas chat pill — appears on hover above the node. Enables
                show_in_interface and deep-links into the Interface tab.
                Styling mirrors the wrapper's RunFromHerePill (same 25-high
                track, popover fill + border outline) so the cluster
                reads as one tightly-coupled set of affordances; label is
                always visible (the agent node has room for it). */}
            {!isBeingEdited && !isDisabled && !isReadOnly && (
                <button
                    onClick={handleOpenChat}
                    data-testid="agent-node-chat-button"
                    className="absolute z-20 flex items-center gap-1.5 h-[25px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-200 nodrag border border-border dark:border-zinc-700/60 bg-popover"
                    style={{
                        top: -28,
                        // Sits to the right of the wrapper-level "Run from here"
                        // pill (25×25 at left:4) with a 4px gap.
                        left: 33,
                        paddingLeft: 8,
                        paddingRight: 10,
                    }}
                    title="Chat with this agent"
                >
                    <MessageSquare className="w-3 h-3 text-foreground/80 shrink-0" />
                    <span className="text-xs font-medium text-foreground/80 whitespace-nowrap">
                        Chat
                    </span>
                </button>
            )}

            {/* Left Input Handle - centered on visual node height */}
            <Handle
                id="left"
                type="target"
                position={Position.Left}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Right Output Handle - centered on visual node height */}
            <Handle
                id="right"
                type="source"
                position={Position.Right}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Bottom Input Handle - accepts multiple inputs */}
            <Handle
                id="bottom"
                type="target"
                position={Position.Bottom}
                className="!w-4 !h-4 !bg-zinc-300 dark:!bg-zinc-400 !border-2 !border-zinc-400 dark:!border-zinc-500 hover:!bg-zinc-300 hover:!border-zinc-300 dark:!border-zinc-400 transition-all opacity-70 hover:opacity-100"
                style={{ zIndex: 10 }}
            />

            {/* Config Status Badge - only show if not disabled */}
            {!isDisabled && !configValid && (
                <NodeStatusBadge variant="incomplete" />
            )}

            {/* Drop a palette node on the body to wire it in as a tool provider.
                Sibling of the main container (not a child) so the ring isn't
                clipped by its overflow-hidden and can lay ON the real border via
                -inset-px; it mirrors the container's selected-state scale so the
                two boxes stay in register. pointer-events stay off so it never
                eats clicks or the node's own drag — dnd-kit hit-tests the
                measured rect, not the pointer target.

                `accepts` is the same predicate dispatchSmartDrop enforces on drop,
                so the ring only ever promises wiring that will actually happen. */}
            {!isReadOnly && (
                <CanvasDropTarget
                    id={`agent-tools-drop-${id}`}
                    kind="agent-tools-drop"
                    payload={{ agentNodeId: id }}
                    accepts={canFeedAgentBottom}
                    className="absolute inset-0 pointer-events-none"
                    style={{ zIndex: 15 }}
                >
                    {({ isOver }) =>
                        isOver ? (
                            // The selected-state scale lives on the RING, never on
                            // the droppable above: dnd-kit measures droppables
                            // transform-agnostically, so a transform there is
                            // stripped and the hit box stops matching what's drawn.
                            <div
                                className={`absolute -inset-px flex items-end justify-center rounded-2xl border-2 border-dashed border-primary dark:border-foreground bg-primary/10 pb-1.5 dark:bg-foreground/10 ${selected ? 'scale-105' : ''}`}
                            >
                                <span className="rounded-full border border-border bg-popover px-1.5 py-0.5 text-[10px] font-medium leading-none text-primary dark:text-foreground">
                                    Add as tool
                                </span>
                            </div>
                        ) : null
                    }
                </CanvasDropTarget>
            )}

            {/* Main Container - fixed height, label sits below */}
            <div
                className={`
                    group relative w-full rounded-2xl overflow-hidden
                    ${isBeingEdited ? '' : 'flex flex-col items-center justify-center p-4'}
                    ${isRunning || shouldOptimize ? 'transition-none' : 'transition-all duration-300 ease-out'}
                    bg-card dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]
                    ${
                        isBeingEdited
                            ? 'border border-border dark:border-white/[0.08] shadow-lg'
                            : selected
                              ? `border-2 border-primary dark:border-foreground shadow-2xl shadow-primary/20 dark:shadow-foreground/20 ${isReadOnly ? '' : 'scale-105'}`
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
                    height: NORMAL_HEIGHT,
                    // Lower opacity when using mock data
                    opacity: hasMockedOutput && !isBeingEdited ? 0.65 : 1,
                }}
            >
                {/* Live local-agent indicator. Presence is set before the CLI
                    process starts and cleared when its turn exits. */}
                {agentCount > 0 && (
                    <TooltipProvider delayDuration={150}>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <div
                                    data-testid={`agent-presence-${id}`}
                                    data-agent-presence-count={agentCount}
                                    className="absolute top-1.5 left-1.5 z-20 flex items-center gap-1 rounded-full border border-foreground/40 bg-foreground/15 px-1.5 py-0.5 backdrop-blur-sm"
                                >
                                    <span className="inline-flex h-1.5 w-1.5 rounded-full bg-foreground" />
                                    <span className="text-[10px] font-semibold leading-none text-foreground">
                                        {agentCount}
                                    </span>
                                </div>
                            </TooltipTrigger>
                            <TooltipContent
                                side="top"
                                className="max-w-[220px] border-border dark:border-zinc-700 bg-card text-center text-foreground shadow-xl shadow-black/40"
                            >
                                {agentCount} active agent process
                                {agentCount === 1 ? '' : 'es'}
                                {agentBusy ? ' · running now' : ''}
                                <span className="mt-0.5 block text-[11px] text-zinc-400">
                                    One entry per live conversation for this node.
                                </span>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                )}
                {/* Non-editing state: normal view with icon, dropdown, chat button */}
                {!isBeingEdited && (
                    <>
                        {/* Animated background gradient mesh */}
                        <div
                            className={`absolute inset-0 opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-60' : 'group-hover:opacity-50'}`}
                            style={{
                                background:
                                    'radial-gradient(circle at 70% 70%, rgba(120, 113, 108, 0.15), transparent 50%)',
                            }}
                        />

                        {/* Glass overlay with noise texture */}
                        <div
                            className={`absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.08] via-transparent to-transparent pointer-events-none ${shouldOptimize ? '' : 'backdrop-blur-[2px]'}`}
                        />

                        {/* Inner soft glow */}
                        <div
                            className={`absolute inset-[1px] rounded-2xl bg-gradient-radial from-white/[0.03] to-transparent ${shouldOptimize ? '' : 'transition-opacity duration-500'} ${selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-70'}`}
                        />

                        {/* Multi-layer shimmer effect - subtle and elegant */}
                        <div className="absolute inset-0 rounded-2xl overflow-hidden pointer-events-none">
                            {/* Primary shimmer sweep */}
                            <div
                                className={`absolute inset-0 opacity-0 group-hover:opacity-70 ${shouldOptimize ? '' : 'transition-opacity duration-500'}`}
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
                                className={`absolute inset-0 opacity-0 group-hover:opacity-40 ${shouldOptimize ? '' : 'transition-opacity duration-500'}`}
                                style={{
                                    background:
                                        'radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.04) 0%, transparent 70%)',
                                }}
                            />
                        </div>

                        {/* Content - Icon and Model Dropdown */}
                        <div className="relative flex flex-col items-center gap-3 w-full">
                            {/* Agent Icon, Label, and MOCK text - scales down slightly when mocked */}
                            <div
                                className={`flex flex-col items-center ${shouldOptimize ? '' : 'transition-all duration-300'}`}
                                style={{
                                    transform:
                                        hasMockedOutput && !isRunning
                                            ? 'scale(0.85)'
                                            : 'scale(1)',
                                }}
                            >
                                <NodeSpinner
                                    isLoading={isRunning}
                                    spinnerRadius={40}
                                >
                                    <div className="flex flex-col items-center gap-2">
                                        <AgentModelIcon
                                            model={model}
                                            variant="normal"
                                            disabled={isDisabled}
                                            stateClassName={`${shouldOptimize ? '' : 'transition-all duration-500'} ${selected ? 'scale-115 brightness-110' : 'group-hover:scale-110 group-hover:brightness-105'}`}
                                        />
                                        {/* Model Selection Label - hidden when mocked */}
                                        {!hasMockedOutput && (
                                            <div
                                                className={`text-xs text-muted-foreground font-medium ${isDisabled ? 'opacity-20' : ''}`}
                                            >
                                                Agent Model
                                            </div>
                                        )}
                                    </div>
                                </NodeSpinner>
                                {/* MOCK label - replaces "Agent Model" when mocked */}
                                {hasMockedOutput && (
                                    <div className="text-[20px] font-bold tracking-widest text-foreground mt-1 dark:[text-shadow:0_2px_6px_rgba(0,0,0,0.9)]">
                                        MOCK
                                    </div>
                                )}
                            </div>

                            {/* Model picker trigger — opens the centered ModelPickerModal */}
                            <div
                                className={`relative w-full flex justify-center ${isDisabled ? 'opacity-20 pointer-events-none' : ''}`}
                            >
                                <button
                                    onClick={() => setShowModelPicker(true)}
                                    data-testid="agent-node-model-trigger"
                                    className="flex items-center gap-1 px-1 py-0.5 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 transition-colors nodrag"
                                    title="Change model"
                                >
                                    {(() => {
                                        const selectedModel = models?.find(
                                            (m) => m.id === model
                                        );
                                        const icon = isHermes ? (
                                            <img
                                                src={HERMES_MARKER_ICON_SRC}
                                                alt="Hermes"
                                                style={{
                                                    width: 20,
                                                    height: 20,
                                                    objectFit: 'contain',
                                                }}
                                            />
                                        ) : isOpenClaw ? (
                                            <img
                                                src={OPENCLAW_MARKER_ICON_SRC}
                                                alt="OpenClaw"
                                                style={{
                                                    width: 22,
                                                    height: 22,
                                                }}
                                            />
                                        ) : selectedModel ? (
                                            getProviderMetadata(
                                                selectedModel.provider
                                            )?.icon
                                        ) : null;
                                        return icon ? (
                                            <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                                                <div
                                                    className="grayscale opacity-80"
                                                    style={{
                                                        transform: `scale(${bumpedIconScale(selectedModel?.provider, 0.45)})`,
                                                    }}
                                                >
                                                    {icon}
                                                </div>
                                            </div>
                                        ) : null;
                                    })()}
                                    <span>{modelShortName(model)}</span>
                                    <ChevronDown className="w-3 h-3" />
                                </button>
                            </div>
                        </div>

                        {/* Disabled Overlay - centered over the node */}
                        {isDisabled && (
                            <div className="absolute inset-0 flex items-center justify-center z-20 pointer-events-none">
                                <Ban
                                    className="text-muted-foreground dark:text-zinc-500 opacity-50"
                                    style={{
                                        width: 46,
                                        height: 46,
                                    }}
                                />
                            </div>
                        )}
                    </>
                )}

                {/* Editing state: expanded with icon on left, status on right */}
                {isBeingEdited && (
                    <div className="flex h-full">
                        {/* Icon section - left side */}
                        <div
                            className="shrink-0 flex items-center justify-center border-r border-border dark:border-white/[0.06] overflow-hidden"
                            style={{
                                width: 70,
                                // The card is still resizing when this mounts;
                                // capping the compartment at the card's own
                                // width keeps the mark inside it the whole way.
                                maxWidth: '100%',
                                background:
                                    'radial-gradient(circle at 50% 50%, hsl(var(--accent) / 0.6), transparent)',
                            }}
                        >
                            <AgentModelIcon model={model} variant="compact" />
                        </div>

                        {/* Content section - right side */}
                        <div className="flex-1 flex flex-col justify-center px-3 py-2 min-w-0">
                            {/* Status row */}
                            <div className="flex items-center gap-2">
                                {editInfo?.status === 'processing' ? (
                                    <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-white/50 animate-spin shrink-0" />
                                ) : (
                                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500/80 shrink-0" />
                                )}
                                <span className="text-[11px] font-medium text-foreground/70 uppercase tracking-wide">
                                    {getStatusText()}
                                </span>
                            </div>

                            {/* Operation */}
                            {editInfo?.operation && (
                                <div className="mt-1.5 flex items-center gap-1.5">
                                    <span className="text-[10px] text-muted-foreground/80 dark:text-white/40 uppercase tracking-wider">
                                        Action:
                                    </span>
                                    <span className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400 truncate">
                                        {editInfo.operation}
                                    </span>
                                </div>
                            )}

                            {/* Config preview */}
                            {editInfo?.config &&
                                Object.keys(editInfo.config).length > 0 && (
                                    <div className="mt-1 font-mono text-[9px] text-muted-foreground/80 dark:text-white/40 space-y-0.5 max-h-[48px] overflow-hidden">
                                        {Object.entries(editInfo.config)
                                            .slice(0, 3)
                                            .map(([key, value]) => (
                                                <div
                                                    key={key}
                                                    className="flex gap-1 truncate"
                                                >
                                                    <span className="text-muted-foreground/70 dark:text-white/50">
                                                        {key}:
                                                    </span>
                                                    <span className="text-muted-foreground dark:text-white/50 truncate">
                                                        {value === null
                                                            ? 'null'
                                                            : typeof value ===
                                                                'object'
                                                              ? '...'
                                                              : String(
                                                                    value
                                                                ).slice(0, 25)}
                                                    </span>
                                                </div>
                                            ))}
                                        {Object.keys(editInfo.config).length >
                                            3 && (
                                            <span className="text-muted-foreground/70 dark:text-white/50">
                                                +
                                                {Object.keys(editInfo.config)
                                                    .length - 3}{' '}
                                                more
                                            </span>
                                        )}
                                    </div>
                                )}
                        </div>
                    </div>
                )}
            </div>

            {/* Centered model picker (portals to body, so canvas transforms don't affect it) */}
            <ModelPickerModal
                open={showModelPicker}
                onClose={() => setShowModelPicker(false)}
                onModelSelect={handleModelChange}
                selectedModelId={model}
                models={models || []}
                priorityModelIds={AGENT_NODE_PRIORITY_MODELS}
            />
        </div>
    );
};

// Output display component for AI Agent nodes
// Handles both streaming messages and final completed output
const AIAgentOutputDisplay = ({ output }: OutputPanelContentProps) => {
    const outputRecord =
        output !== null && typeof output === 'object' && !Array.isArray(output)
            ? output
            : null;

    // Final agent output (completed execution) - show as JSON for downstream connectivity
    if (outputRecord?.type === 'agent' && outputRecord.status === 'completed') {
        const { images, videos } = agentOutputMedia(outputRecord);
        return (
            <div className="space-y-4">
                <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-foreground font-medium">
                        Agent Output
                    </div>
                    <div className="text-[10px] text-green-600 dark:text-green-400">
                        Completed
                    </div>
                </div>
                {(images.length > 0 || videos.length > 0) && (
                    <div className="space-y-2">
                        {images.map((url, i) => (
                            <img
                                key={`img-${i}`}
                                src={url}
                                alt={`Generated image ${i + 1}`}
                                className="w-full rounded-lg border border-border dark:border-zinc-700/50 object-contain max-h-96"
                            />
                        ))}
                        {videos.map((url, i) => (
                            <video
                                key={`vid-${i}`}
                                src={url}
                                controls
                                className="w-full rounded-lg border border-zinc-700/50 object-contain max-h-96 bg-black"
                            />
                        ))}
                    </div>
                )}
                {outputRecord.response != null && (
                    <div className="bg-muted/50 dark:bg-black/20 border border-border/50 dark:border-zinc-800/50 rounded-lg p-3">
                        <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words">
                            {String(outputRecord.response)}
                        </pre>
                    </div>
                )}
                <IODataDisplay data={output} label="JSON Output" />
            </div>
        );
    }

    // Streaming agent messages (during execution)
    if (outputRecord?.type === 'chat_message') {
        const isStreaming = outputRecord.finished === false;
        return (
            <div className="space-y-4">
                <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-foreground font-medium">
                        Agent Response
                    </div>
                    {isStreaming && (
                        <div className="text-[10px] text-blue-600 dark:text-blue-400 animate-pulse">
                            Streaming...
                        </div>
                    )}
                </div>
                <div className="bg-muted/50 dark:bg-black/20 border border-border/50 dark:border-zinc-800/50 rounded-lg p-3">
                    <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words">
                        {outputRecord.message == null
                            ? 'Processing...'
                            : String(outputRecord.message)}
                    </pre>
                </div>
            </div>
        );
    }

    // Fallback for other output types (shouldn't happen but handle gracefully)
    return <IODataDisplay data={output} label="Output" />;
};

const agentDisplayStrategy = {
    OutputPanelContent: AIAgentOutputDisplay,
    buildSuggestionsFromConfig: (
        _nodeData: Record<string, unknown>,
        nodeId: string
    ): ReferenceSuggestion[] => [
        {
            reference: `${nodeId}.response`,
            label: 'response: Agent final response',
            nodeId,
            path: 'response',
            valueType: 'string',
            value: 'Agent final response',
            depth: 1,
        },
        {
            reference: `${nodeId}.status`,
            label: 'status: completed',
            nodeId,
            path: 'status',
            valueType: 'string',
            value: 'completed',
            depth: 1,
        },
        {
            reference: `${nodeId}.model`,
            label: 'model: model id',
            nodeId,
            path: 'model',
            valueType: 'string',
            value: 'model id',
            depth: 1,
        },
        {
            reference: `${nodeId}.images`,
            label: 'images [generated images]',
            nodeId,
            path: 'images',
            valueType: 'array',
            value: [],
            depth: 1,
        },
    ],
};

export const AIAgentNode: NodeDefinition = {
    type: 'agent',
    label: 'AI Agent',
    description: 'Add an AI agent',
    Icon: Bot,
    iconColor: 'text-purple-600 dark:text-purple-400',
    dimensions: { width: 200, height: 140, iconSize: 56 },
    component: memo(AIAgentNodeComponent, (prev, next) => {
        const prevConfig = prev.data?.config as Record<string, any> | undefined;
        const nextConfig = next.data?.config as Record<string, any> | undefined;
        return (
            prevConfig?.model === nextConfig?.model &&
            prev.selected === next.selected &&
            prev.data?.executionState === next.data?.executionState &&
            prev.data?.configValid === next.data?.configValid &&
            prev.data?.disabled === next.data?.disabled &&
            prev.data?.mockedOutput === next.data?.mockedOutput &&
            prev.data?.label === next.data?.label &&
            prev.data?._previewEditInfo === next.data?._previewEditInfo
        );
    }),
    displayStrategy: agentDisplayStrategy,
};
