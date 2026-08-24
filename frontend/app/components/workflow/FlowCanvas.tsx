// Main workflow editor canvas — renders the node graph via ReactFlow, handles drag-and-drop,
// autosave, collaborative presence, node execution, and all keyboard shortcuts.
//
// ─── Where to find things ────────────────────────────────────────────────────
// This file orchestrates the canvas; domain-specific concerns live in helpers:
//
//   Extracted components (all under ./canvas/):
//     CanvasTopBar         — top navbar: tab buttons + right-side action menu
//     CanvasDialogs        — Share, Settings, MinBalance, Publish, Confetti, MobileErrorBanner
//     CanvasOverlays       — HoverExecutionGlow, CanvasExternalLinkPill
//     MobileCanvasChrome   — MobileRunPill, MobileResourcesPill, MobileErrorBanner
//
//   Extracted hooks (all under ~/hooks/):
//     useCanvasViewport              — viewport restore + auto-fit + persist
//     useClickToAddNode              — node "+" hint → picker → create-connected-node
//     useNodeConfigValidation        — debounced per-node configValid computation
//     useWelcomeFlow                 — first-time-user confetti + expansion gate
//     useWorkflowExecutionTracking   — activeExecutions Map, logs, socket listeners
//
//   Extracted libs (pure functions under ~/lib/):
//     workflowIO       — JSON import/export serialization
//     viewportCache    — per-workflow viewport cache (memory + localStorage)
//     applyNodeUpdate  — node mutation helpers + by-id list utilities
//
// ─── Caching architecture ────────────────────────────────────────────────────
//   - Viewport:        localStorage (sync, cold-start) + in-memory Map (fastest) + IndexedDB via useWorkflowDisplayMetadata (persistent)
//   - Nodes/edges:     IndexedDB via valtioCache ('workflow-canvas:{id}') — instant render before workflow:get
//   - UI state:        IndexedDB via useWorkflowDisplayMetadata — selected node, tabs, FlowHelper state
//   - Interface grid:  IndexedDB via useCachedValtioState — block positions
//   - Autosave guard:  hasLoadedWorkflowRef blocks workflow:update until workflow:get completes (prevents stale cache overwrites)

import {
    ReactFlow as ReactFlowComponent,
    ReactFlowProvider,
    Node,
    Edge,
    applyNodeChanges,
    applyEdgeChanges,
    NodeChange,
    NodeDimensionChange,
    EdgeChange,
    addEdge,
    Connection,
    Position,
    useReactFlow,
    useUpdateNodeInternals,
    type FinalConnectionState,
} from '@xyflow/react';
import { resolveBodyDropConnection } from './edges/connectionDropSnap';
import { requestTestRun } from '~/components/design/rehearsal/testRunHandoff';
import { rehydrateRehearsalAuthoring } from '~/components/design/rehearsal/useRehearsalAuthoring';
import { getLocalComponentValtio } from '~/state';
import { CanvasBackground } from '~/components/workflow/canvasBackground';
import { scaled } from '~/lib/constants';
import { isTextEntryTarget, isModalOpen } from '~/lib/keyboard';
import { setAddNodeShortcutActive } from '~/lib/shortcuts';
import {
    BASE_PREVIEW_SIZE,
    NodePreviewIcon,
} from './flowHelper/NodesTabContent';
import { ForkCanvas, type ForkCanvasRef } from './forkflow/ForkCanvas';
import { loadNodeDefsFor } from './nodeRegistryLazy';
// NodeDefinition is already imported below from './nodes/nodeRegistry' — reuse that one.
import { toast } from 'sonner';
import {
    WorkflowProvider,
    getPendingNodeSelection,
    clearPendingNodeSelection,
    consumePointerDrivenDelete,
    setEditingNodeIds,
    setIsAiEditing,
    setRemoteAiEditing,
    updateRemoteAiEditingInfo,
    clearRemoteAiEditing,
} from './WorkflowContext';
import React, {
    useCallback,
    useState,
    useEffect,
    useRef,
    useMemo,
} from 'react';
import { useSearchParams } from 'react-router';
import { useDroppable, DragStartEvent, DragEndEvent } from '@dnd-kit/core';
import '@xyflow/react/dist/style.css';
import { useValtioState } from '~/hooks/useValtioState';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useCredentialVariables } from '~/hooks/useCredentialVariables';
import { useWorkflowVariables, type WorkflowVariableDefinition } from '~/hooks/useWorkflowVariables';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { track } from '~/lib/telemetry';
import { CredentialVariablesContext } from '~/contexts/CredentialVariablesContext';
import { FormSubmitContext } from '~/contexts/FormSubmitContext';
import { useWorkflowDisplayMetadata } from '~/hooks/useWorkflowDisplayMetadata';
import { useWorkflowNodeOutputs } from '~/hooks/useWorkflowNodeOutputs';
import { workflowTestHarness } from '~/lib/workflowTestHarness';
import { describeNodeError } from '~/lib/describeNodeError';
import {
    WorkflowExecutionLogs,
    WorkflowExecutionLog,
} from './WorkflowExecutionLogs';
import { WorkflowResources } from './WorkflowResources';
import { FlowHelperView } from './FlowHelperView';
import { CANVAS_DROP_KINDS } from '~/lib/canvasDropKinds';
import { FlowCanvasEmptyState } from './FlowCanvasEmptyState';
import { AnimatePresence } from 'framer-motion';

const WorkflowInterface = React.lazy(() =>
    import('~/components/interface/WorkflowInterface').then((m) => ({
        default: m.WorkflowInterface,
    }))
);
import type {
    WorkflowInterfaceHandle,
    InterfaceGridState,
} from '~/components/interface/WorkflowInterface';
import { getBlockTypeForNodeType } from '~/components/interface/blockRegistry';
import {
    agentShowsInInterface,
    hiddenAgentToRevealForTestRun,
} from '~/utils/interfaceBlocks';
import {
    BlockPreviewCard,
    getBlockPreviewWidth,
} from '~/components/interface/BlockPreviewCard';
import { ErrorNodeNavigator } from './ErrorNodeNavigator';
import { IncompleteNodeNavigator } from './IncompleteNodeNavigator';
import { CanvasNavigatorPills } from './canvas/CanvasNavigatorPills';
import { WorkflowSetupView } from './setup/WorkflowSetupView';
import { useWelcomeFlow } from '~/hooks/useWelcomeFlow';
import { useCanvasViewport } from '~/hooks/useCanvasViewport';
import { useClickToAddNode } from '~/hooks/useClickToAddNode';
import { useNodeConfigValidation } from '~/hooks/useNodeConfigValidation';
import {
    MobileResourcesPill,
    MobileRunPill,
    MobileBuilderStatusPill,
} from './canvas/MobileCanvasChrome';
import { CanvasDialogs } from './canvas/CanvasDialogs';
import { CanvasTopBar } from './canvas/CanvasTopBar';
import { TriggerInfoDialog } from './TriggerInfoDialog';
import { IncompleteRunDialog } from './IncompleteRunDialog';
import { RunResultsDialog, type NodeRunResult } from './RunResultsDialog';
import { RunHistoryPill } from './canvas/RunHistoryPill';
import {
    getTriggerRunPrompt,
    type WorkflowTrigger,
} from '~/utils/workflowTriggers';
import {
    CREDENTIALS_KEY,
    describeStepsForIds,
    getIncompleteRunPrompt,
    describeRunPath,
    getRunStartPaths,
    toolProviderTitles,
    OPERATION_KEY,
    TOOL_OPERATIONS_KEY,
    type RunPath,
} from '~/utils/incompleteRunPrompt';
import { credentialsPulseKey, requestPulse } from '~/lib/pulseHighlight';
import { applyCredentialSelection } from '~/lib/applyCredentialSelection';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { useSeenOnce } from '~/hooks/useSeenOnce';
import {
    CanvasExternalLinkPill,
    HoverExecutionGlow,
} from './canvas/CanvasOverlays';
import { useWorkflowExecutionTracking } from '~/hooks/useWorkflowExecutionTracking';
import {
    Link2,
    Loader2,
    Braces,
    Paintbrush,
    Plus,
    History,
    Wrench,
    X,
    UserPlus,
} from 'lucide-react';
import { createPortal } from 'react-dom';
import { cn } from '~/lib/utils';
import {
    ReplayToolCallsPanel,
    toReplayToolCalls,
    type ReplayToolCall,
} from './ReplayToolCallsPanel';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '~/components/ui/tooltip';
import { KeyHint } from '~/components/shared/KeyHint';
import {
    Popover,
    PopoverTrigger,
    PopoverContent,
} from '~/components/ui/popover';
import {
    GuidedTourHighlight,
    type TourStep,
} from '~/components/ui/GuidedTourHighlight';
import { InviteCard } from '~/components/chat/InviteCard';
import { InviteWalkthroughArt } from '~/components/chat/InviteWalkthroughArt';
import { AgentChatWalkthroughArt } from '~/components/chat/AgentChatWalkthroughArt';
import { INVITE_WALKTHROUGH_EVENT } from '~/lib/inviteWalkthrough';
import {
    computeImportOffset,
    exportWorkflowToFile,
    readWorkflowFile,
    repositionImportedNodes,
} from '~/lib/workflowIO';
import { useStickyNoteNode } from '~/hooks/nodes/useStickyNoteNode';
import {
    buildReactFlowNodeTypes,
    NodeDefinition,
    getNodeMetadata,
    CONNECTIONLESS_TYPES,
} from './nodes/nodeRegistry';
import { EXTERNAL_LINK_CONFIG } from '~/utils/externalNodeLinks';
import { MiniStickyNotePreview } from './nodes/MiniStickyNotePreview';
import { fromHintHandleId } from './nodes/base/NextStepHint';
import AnimatedWorkflowEdge from './edges/AnimatedWorkflowEdge';
import { CustomConnectionLine } from './edges/CustomConnectionLine';
import { DndProvider } from '~/providers/DndProvider';
import {
    sendEvent,
    WorkflowExecuteRequest,
    sendEventWithCallback,
    sendEventAsync,
} from '~/lib/socket-sender';
import {
    getGuaranteedReachableNodes,
    getReachableFromHandle,
    getAllDownstreamNodes,
    runScopeForRoots,
    withAncestors,
    withWiredToolProviders,
} from '~/lib/getGuaranteedReachableNodes';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import { useDebounce } from '~/hooks/useDebounce';
import { useWorkflowUndoRedo } from '~/hooks/useWorkflowUndoRedo';
import { useWorkflowCopyPaste } from '~/hooks/useWorkflowCopyPaste';
import { useCanvasContextMenu } from '~/hooks/useCanvasContextMenu';
import { useWorkflowKeyboardShortcuts } from '~/hooks/useWorkflowKeyboardShortcuts';
import { useIsMobile } from '~/hooks/useIsMobile';
import { useCtrlPan } from '~/hooks/useCtrlPan';
import { useWorkflowMCPHandler } from '~/hooks/useWorkflowMCPHandler';
import { useMCPBuilderEvents } from '~/hooks/useMCPBuilderEvents';
import { useWorkflowPan } from '~/hooks/useWorkflowPan';
import { WorkflowGetRequest } from '~/types/socket-events.generated';
import {
    ResourceListRequest,
    CredentialDisplayInfoRequest,
} from '~/types/socket-events.generated';
import type { JsonFieldDragData } from './DraggableJsonField';
import {
    createReferenceString,
    getInsertReferenceForField,
} from './DroppableTextField';
import {
    dispatchJsonFieldDragStart,
    dispatchJsonFieldDragEnd,
} from '~/lib/jsonFieldDragBridge';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import {
    getAgentToolProviders,
    getAgentTriggerSources,
    getTriggerlessAgents,
    canFeedAgentBottom,
    isAgentToolProviderType,
    isTriggerSource,
    type AgentTriggerSource,
    type AgentWiredTool,
} from '~/utils/nodeSchemas';
import {
    hasUnconnectedCredentials,
    providerCredentialsMissing,
} from './NodeCredentials';
import {
    computeWiredProviderIdsKey,
    contextFromWiringKey,
} from '~/utils/workflowNodeValidation';
import {
    autoSelectCredentialsForNewNode,
    prefetchCredentials,
    upsertCredentialsIntoCache,
    removeCredentialsFromCache,
    setActiveCredentialWorkflow,
    authorizeCredentialsForWorkflow,
    type CredentialDisplayMeta,
} from '~/utils/credentialAutoSelect';
import {
    detectUpstreamReferences,
    prepareNodeExecution,
    serializeGraphForExecution,
} from '~/utils/workflowNodeExecution';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';
import {
    appendIfUnique,
    applyNodeUpdate,
    createWorkflowNode,
    ensureNodePosition,
    hasValidPosition,
    normalizeNodeUpdatePayload,
    patchById,
    removeById,
    updateNodeInList,
    mergeServerNodes,
    mergeServerEdges,
    dropStaleCacheEntries,
    applyNodeStatuses,
    RUN_STATUS_FIELDS,
    type NodeStatusInfo,
} from '~/lib/applyNodeUpdate';
import { reportInvariant } from '~/lib/telemetry-errors';
import {
    buildAgentChatRunOverride,
    buildAgentChatConfigPatch,
    DEFAULT_INTERFACE_CONV_KEY,
    type AgentChatAttachment,
} from '~/lib/agentChat';
import {
    parseListReference,
    parseWholeReference,
    splitAtFirstIndex,
    rewriteListRefsForIteration,
    getValueAtPath,
    clipSampleItem,
} from '~/lib/listReferences';
import {
    applyEdgeStyle,
    createStyledEdge,
    dedupeEdges,
} from '~/utils/workflowLayout';
import { queueAgentChatSend } from '~/lib/pendingAgentSendStore';
import { valtioCache } from '~/lib/indexeddb';
import { valtioSessionCache } from '~/lib/session-cache';
import { autolayout } from '~/utils/autolayout';
import { perfState } from '~/lib/perf-state';
import { workflowDebugStore } from '~/lib/workflow-debug-store';
import { useCollaborativePresence } from '~/hooks/useCollaborativePresence';
import { useCanvasWorkflowEdit } from '~/hooks/useCanvasWorkflowEdit';
import { extractN8nWorkflowFromClipboard } from '~/utils/n8n-converter';
import { onSocketEvent } from '~/lib/socket-receiver';
import { updateBuilderContext } from '~/lib/builder-context';
import {
    recordGraphSnapshot,
    recordDeletedNodes,
    recordRemoteDeletedNodes,
    setGraphLoaded,
    setGraphVersion,
    setGraphDragging,
    setCanvasMounted,
    flushGraphNow,
    markGraphDirty,
    hasLiveGraphState,
    getPendingDeletedNodeIds,
    seedSaveBaseline,
} from '~/lib/liveGraphStore';
import { useLiveGraph } from '~/hooks/useLiveGraph';
import {
    CollaborativeProvider,
    CollaboratorCursorNode,
    CollaborativeCursors,
    isCursorNode,
} from './collaboration';
import type { Collaborator } from '~/lib/collaboration';
import { getWorkflowPresenceService } from '~/lib/collaboration';

// Type declaration for global function
// This is used to decide where to drop a dragged component in the flow canvas
declare global {
    interface Window {
        screenToFlowPosition?: (
            screenX: number,
            screenY: number
        ) => { x: number; y: number };
    }
}

const proOptions = { hideAttribution: true };

// NodeTypes will be defined inside component with useMemo

// Drag-overlay dimensions matching MiniNodePreview — same scaled height as
// the source tile so the cursor stays anchored to the visual centre.
const calculateOverlayDimensions = (node: NodeDefinition) => {
    const targetHeight = scaled(BASE_PREVIEW_SIZE);
    const aspectRatio = node.dimensions.width / node.dimensions.height;
    const scaleFactor = targetHeight / node.dimensions.height;
    return {
        width: targetHeight * aspectRatio,
        height: targetHeight,
        iconSize: node.dimensions.iconSize * scaleFactor,
    };
};

// Empty initial state - workflows start empty or load from backend
const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];

// The set of node ids a run from `startId` will (re-)execute: the start node plus
// everything downstream of it. Used to scope run-state resets.
function runResetIds(edges: Edge[], startId: string): Set<string> {
    return new Set([startId, ...getAllDownstreamNodes(edges, startId)]);
}

type NodeSetters = {
    setNodes?: (setter: (prevNodes: Node[]) => Node[]) => void;
    setEdges?: (setter: (prevEdges: Edge[]) => Edge[]) => void;
    getNodes?: () => Node[];
    // Callbacks to open config view after node creation
    onNodeCreated?: (nodeId: string) => void;
    // Broadcast new node to collaborators
    broadcastNodeAdd?: (node: Node) => void;
    // Broadcast a new edge to collaborators (e.g. the auto-paired Split Out -> Iteration edge)
    broadcastEdgeAdd?: (edge: Edge) => void;
    // Reverse auto-sync: add a block to the interface grid when an interface node is dropped on canvas
    addInterfaceBlock?: (blockId: string, blockType: string) => void;
    // Marks a node as just dropped onto the canvas — Config tab opens in Edit view
    setFreshlyDroppedNodeId?: (nodeId: string | null) => void;
};

/**
 * Source descriptor for FlowCanvas. When kind === 'skill' the canvas loads/saves
 * via skill:get_workflow / skill:update_workflow instead of the regular workflow:*
 * events, and disables features that don't apply to skills (collab presence,
 * publish status, conversation events). Defaults to { kind: 'workflow' } when omitted.
 */
export type FlowCanvasSource =
    | { kind: 'workflow'; id?: string }
    | { kind: 'skill'; id: string };

interface FlowCanvasProps {
    workflowTitle?: string;
    workflowId?: string;
    onBack?: () => void;
    onDelete?: (workflowId: string) => void;
    onTitleChange?: (newTitle: string) => void;
    onNavigateToWorkflow?: (workflowId: string) => void;
    nodeSettersRef?: React.MutableRefObject<NodeSetters>;
    source?: FlowCanvasSource;
}

// Inner component that uses ReactFlow hooks
// One-step "find the link later" walkthrough: spotlights the canvas invite
// button after the user first closes the inline invite banner.
const INVITE_WALKTHROUGH_STEPS: TourStep[] = [
    {
        target: '[data-tour-target="invite-button"]',
        title: 'Your invite link lives here',
        description:
            'Open this anytime to copy the link and invite people to build this flow with you, live.',
        buttonText: 'Got it',
        placement: 'left',
        padding: 6,
        media: <InviteWalkthroughArt />,
    },
];

/**
 * Combine two `config_overrides` maps, merging the per-node objects rather than
 * replacing them.
 *
 * A shallow spread is keyed by NODE ID, so when both sides target the same node
 * the second one's object wins whole and the first one's keys vanish — which is
 * how the Run popup's opening message would have silently dropped the fields a
 * caller (the SDK bridge, an interface form) had already set on that agent.
 */
function mergeConfigOverrides(
    base: Record<string, Record<string, unknown>> | undefined,
    extra: Record<string, Record<string, unknown>> | undefined
): Record<string, Record<string, unknown>> | undefined {
    if (!base) return extra;
    if (!extra) return base;
    const merged = { ...base };
    for (const [nodeId, values] of Object.entries(extra)) {
        merged[nodeId] = { ...merged[nodeId], ...values };
    }
    return merged;
}

/** A run narrowed to chosen entry points, with per-node one-shot config. */
interface RunSelection {
    pathIds?: string[];
    configOverrides?: Record<string, Record<string, unknown>>;
}

const FlowCanvasInner = ({
    workflowTitle,
    workflowId,
    onBack,
    onDelete,
    onTitleChange,
    onNavigateToWorkflow,
    nodeSettersRef,
    source,
}: FlowCanvasProps) => {
    // Skill-mode flag — derived once and used to gate collab and to route persistence.
    const isSkill = source?.kind === 'skill';
    const { logActivity } = useAnalytics();
    const {
        screenToFlowPosition,
        setViewport: setReactFlowViewport,
        fitView,
        getViewport,
        setCenter,
        getInternalNode,
    } = useReactFlow();
    const updateNodeInternals = useUpdateNodeInternals();
    const [searchParams, setSearchParams] = useSearchParams();
    // Ref to avoid setSearchParams in useEffect deps (Remix recreates it on URL changes, causing effect re-runs)
    const setSearchParamsRef = useRef(setSearchParams);
    setSearchParamsRef.current = setSearchParams;
    // ForkCanvas swap: enabled automatically on mobile (xyflow can't carry our
    // workflow content on iPhone — see docs/mobile/canvas-tile-cache.md), or via
    // ?canvas=fork on desktop for testing. ForkCanvas is the from-scratch
    // xyflow-free renderer with controlled onNodesChange + imperative fitView.
    // Mobile detection uses the same 768px breakpoint as the rest of the app.
    const useForkCanvasMobile = useIsMobile(768);
    const useForkCanvas =
        useForkCanvasMobile || searchParams.get('canvas') === 'fork';
    const [forkNodeDefs, setForkNodeDefs] = useState<
        Record<string, NodeDefinition | null>
    >({});
    // Ref to ForkCanvas's imperative API. We call .fitView() in parallel with
    // xyflow's fitView so the canvas auto-frames AI-affected nodes when ?canvas=fork.
    const forkCanvasRef = useRef<ForkCanvasRef | null>(null);
    // The legacy min_required_balance pre-flight check was removed in Phase 2.1.
    // Workflow runs are now gated by the unified credit pool (per-node
    // check_credit_balance + the AI builder cap); a partial run that hits the
    // monthly cap mid-execution fails gracefully on the node level. The
    // workflow setting `min_required_balance` is now vestigial and ignored.
    const [isReactFlowReady, setIsReactFlowReady] = useState(false);
    const hasLoadedWorkflowRef = useRef(false);
    // Ids the IndexedDB cache-restore injected into the canvas this mount.
    // Consumed by the workflow:get callback: a cache-restored node/edge the
    // server response doesn't contain was deleted after the cache was
    // written — merge must drop it, not union it back in (else the next
    // autosave re-persists the deleted node and it "resurrects").
    const cacheRestoredNodeIdsRef = useRef<Set<string>>(new Set());
    const cacheRestoredEdgeIdsRef = useRef<Set<string>>(new Set());
    // True until workflow:get completes — blocks autosave and user edits while showing cached data.
    // Only enabled for real workflows (not demo/temp) that need backend fetching.
    const isRealWorkflow = !!(
        workflowId &&
        !workflowId.startsWith('workflow_demo') &&
        !workflowId.startsWith('temp-') &&
        !workflowId.startsWith('00000000')
    );
    const [isSyncing, setIsSyncing] = useState(isRealWorkflow);
    const isSyncingRef = useRef(isRealWorkflow);
    isSyncingRef.current = isSyncing;
    // State to trigger viewport effect when workflow loads (refs don't trigger re-renders)
    const [workflowLoadedTrigger, setWorkflowLoadedTrigger] = useState(0);
    const [workflowLoadError, setWorkflowLoadError] = useState<string | null>(
        null
    );

    const canvasDivRef = useRef<HTMLDivElement | null>(null);
    const panActivationKeyCode = useCtrlPan(canvasDivRef);

    // Check URL params for navigation context
    const isNewWorkflow = searchParams.get('new') === 'true';

    // Welcome experience for freshly-created workflows: confetti +
    // ?new=true cleanup + FlowHelperView expansion gate
    const { confettiTrigger, expansionBlocked } = useWelcomeFlow({
        isNewWorkflow,
        setSearchParamsRef,
    });

    // Display metadata hook - manages viewport, selected node, FlowHelperView state, etc.
    const {
        displayMetadata,
        displayMetadataRef,
        activeTab,
        viewport,
        flowHelperHeight,
        isFlowHelperFullScreen,
        isConfigViewExpanded: rawIsConfigViewExpanded,
        flowHelperActiveTab,
        flowHelperSearchQuery,
        setActiveTab,
        setViewport,
        setFlowHelperHeight,
        setIsFlowHelperFullScreen,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setFlowHelperSearchQuery,
        setSelectedNodeId,
        hasLocalCache,
        restoreFromBackend,
    } = useWorkflowDisplayMetadata({
        workflowId: workflowId || '',
        hasLoadedWorkflow: hasLoadedWorkflowRef.current,
    });

    // Hook for programmatic pan/zoom to nodes - handles FlowHelperView offset and animation flags
    const { panToNode, panToEdge, pendingAnimationRef } = useWorkflowPan({
        flowHelperHeight,
        // The persisted height lingers when the panel is closed; only offset/
        // zoom for it when the panel is actually open.
        isPanelOpen: !expansionBlocked && rawIsConfigViewExpanded,
        setViewport,
    });

    // Block FlowHelper for first-time users until welcome completes; returning users are unblocked immediately
    const isConfigViewExpanded = !expansionBlocked && rawIsConfigViewExpanded;

    // Skip the FlowHelper slide-up only when opened via the "F" key (clicks keep
    // their animation). Set by the F toggle; cleared whenever the view closes so
    // the next mouse-open animates again.
    const [flowHelperNoAnim, setFlowHelperNoAnim] = useState(false);
    useEffect(() => {
        if (!isConfigViewExpanded) setFlowHelperNoAnim(false);
    }, [isConfigViewExpanded]);

    // Ephemeral "this height change is instant" flag for keyboard resizes (Enter
    // expands to ~70%, Escape shrinks). Kept separate from flowHelperNoAnim
    // (which suppresses the mount slide for a whole session) and reset on the
    // next frame so the height applies with transition:none for that one commit,
    // then mouse-driven resizes (auto-shrink on deselect) animate again.
    const [flowHelperInstantHeight, setFlowHelperInstantHeight] =
        useState(false);
    useEffect(() => {
        if (!flowHelperInstantHeight) return;
        const id = requestAnimationFrame(() =>
            setFlowHelperInstantHeight(false)
        );
        return () => cancelAnimationFrame(id);
    }, [flowHelperInstantHeight]);

    // Whether the config's operation picker may grab focus when it opens. Set
    // false during arrow node-traversal so an operation-less node's picker
    // doesn't steal focus and trap navigation; true on deliberate edit intent
    // (click a node, Enter), where focusing the picker to type is wanted.
    const [autoFocusPickerOnOpen, setAutoFocusPickerOnOpen] = useState(true);

    // In-memory cache for real-time streaming of large outputs during execution
    const {
        saveNodeOutput: saveLargeOutputIfNeeded,
        localOutputsRef: largeOutputsRef,
    } = useWorkflowNodeOutputs({
        workflowId: workflowId || '',
    });

    // selectedNode is kept as full Node object, but we sync the ID to cached metadata
    // Also sync to workflowDebugStore so workflow diagnostics can show phase 2/3 info for selected node
    const [selectedNode, setSelectedNodeInternal] = useState<Node | null>(null);

    // Mirroring refs so the click handlers below can read current FlowHelperView
    // dimensions without rebuilding the callbacks on every height tick. isMobile is
    // mirrored too because ReactFlow's onNodeClick/onPaneClick fire on mobile (the
    // canvas renders there too) but FlowHelperView itself does not — without the
    // guard we'd churn flowHelperHeight state for nothing.
    const flowHelperHeightRef = useRef(0);
    const isFlowHelperFullScreenRef = useRef(false);
    const isConfigViewExpandedRef = useRef(false);
    const isMobileRef = useRef(false);
    useEffect(() => {
        flowHelperHeightRef.current = flowHelperHeight;
    }, [flowHelperHeight]);
    useEffect(() => {
        isFlowHelperFullScreenRef.current = isFlowHelperFullScreen;
    }, [isFlowHelperFullScreen]);
    useEffect(() => {
        isConfigViewExpandedRef.current = isConfigViewExpanded;
    }, [isConfigViewExpanded]);

    const setSelectedNode = useCallback(
        (node: Node | null) => {
            setSelectedNodeInternal(node);
            setSelectedNodeId(node?.id || null);
            workflowDebugStore.setSelectedNodeId(node?.id || null);
        },
        [setSelectedNodeId]
    );

    // Close FlowHelperView on canvas click (deselect). Wired to onPaneClick rather
    // than onSelectionChange because that fires only for real clicks — dragging a
    // node also fires selectionChange and we don't want the drag-start to slam the
    // panel shut.
    const closeFlowHelperOnDeselect = useCallback(() => {
        if (isMobileRef.current || !isConfigViewExpandedRef.current) return;
        setIsConfigViewExpanded(false);
        setSelectedNode(null);
        setIsFlowHelperFullScreen(false);
    }, [setIsConfigViewExpanded, setSelectedNode, setIsFlowHelperFullScreen]);

    const [isShareDialogOpen, setIsShareDialogOpen] = useState(false);
    const [isSettingsDialogOpen, setIsSettingsDialogOpen] = useState(false);
    // Which section the settings dialog opens on — the Variables FAB deep-links
    // straight to Variables; the navbar opener starts on General.
    const [settingsInitialSection, setSettingsInitialSection] = useState<'general' | 'variables'>('general');
    const [workflowSettings, setWorkflowSettings] = useState<
        Record<string, unknown>
    >({});
    // Gates the FlowHelperView wrapper's height transition — true mid-drag so the
    // drag handler's direct DOM mutations don't trigger a 280ms interpolation each
    // tick. Reset on resize-end so subsequent programmatic resizes (auto-shrink on
    // deselect, restore on re-select) ease in/out.
    const [isFlowHelperResizing, setIsFlowHelperResizing] = useState(false);
    // Set when a node is dropped onto the canvas via drag-and-drop. Tells
    // FlowHelperView's Config tab to default to the Edit view for that node;
    // ConfigTabContent clears it after consuming.
    const [freshlyDroppedNodeId, setFreshlyDroppedNodeId] = useState<
        string | null
    >(null);
    // Counter — bumped when the helper is opened with the intent to search.
    // FlowHelperView consumes this to autofocus the NodeSearchBar input so
    // the user can type immediately without an extra click.
    const [searchFocusSignal, setSearchFocusSignal] = useState(0);
    const bumpSearchFocus = useCallback(
        () => setSearchFocusSignal((c) => c + 1),
        []
    );
    const [resourceCount, setResourceCount] = useState(0);

    // Ref to container for direct DOM manipulation during resize (avoids re-renders)
    const flowHelperContainerRef = useRef<HTMLDivElement>(null);
    const workflowInterfaceRef = useRef<WorkflowInterfaceHandle>(null);
    // Persist interface grid state across WorkflowInterface remounts (tab switches)
    // Cached in IndexedDB so it loads instantly on subsequent visits (same as display metadata)
    const [interfaceGridState, setInterfaceGridState] =
        useCachedValtioState<InterfaceGridState | null>(
            workflowId ? `/workflow/${workflowId}` : '/workflow/default',
            'interfaceGridState',
            null,
            true // skipRedisSync - only cache locally in IndexedDB
        );
    // Ref mirror for non-reactive reads (auto-save, copy/paste, MCP handlers)
    const interfaceGridStateRef = useRef(interfaceGridState);
    interfaceGridStateRef.current = interfaceGridState;
    const [interfaceLayoutVersion, setInterfaceLayoutVersion] = useState(0);
    const debouncedInterfaceVersion = useDebounce(interfaceLayoutVersion, 2000);
    const handleInterfaceStateChange = useCallback(
        (state: InterfaceGridState) => {
            const prev = interfaceGridStateRef.current;
            // Don't cache empty layouts that result from mounting before nodes have loaded —
            // they would overwrite the correct saved positions in the cache.
            if (state.layout.length === 0 && prev && prev.layout.length > 0)
                return;
            setInterfaceGridState(state);
            // Trigger auto-save if layout OR tabOrder changed (skip mount/re-mount echoes
            // where WorkflowInterface fires onStateChange with the same savedState we gave it)
            const changed =
                !prev ||
                JSON.stringify(prev.layout) !== JSON.stringify(state.layout) ||
                JSON.stringify(prev.tabOrder ?? []) !==
                    JSON.stringify(state.tabOrder ?? []);
            if (changed && state.layout.length > 0) {
                setInterfaceLayoutVersion((v) => v + 1);
            }
        },
        [setInterfaceGridState]
    );
    // Ref to store handleNodeDataUpdate callback so event listener can access latest version
    const handleNodeDataUpdateRef = useRef<
        (nodeId: string, newData: Record<string, any>) => void
    >(() => {});

    // Ref for file input for workflow import
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Full mobile mode below 768px. Navbar tab/action compaction is now driven
    // by the bar's own measured width inside CanvasTopBar (the bar is narrower
    // than the viewport when side panels are open), not a viewport breakpoint.
    const isMobile = useIsMobile(768);
    useEffect(() => {
        isMobileRef.current = isMobile;
    }, [isMobile]);

    // Mobile error notification queue — shows one at a time with 4s progress bar
    const [mobileErrors, setMobileErrors] = useState<
        Array<{ id: string; title: string; description: string }>
    >([]);
    const enqueueMobileError = useCallback(
        (title: string, description: string) => {
            setMobileErrors((prev) => [
                ...prev,
                { id: `${Date.now()}-${Math.random()}`, title, description },
            ]);
        },
        []
    );
    // Auto-dismiss the front error after 4s; restarts only when the front item changes
    useEffect(() => {
        if (mobileErrors.length === 0) return;
        const timer = setTimeout(
            () => setMobileErrors((prev) => prev.slice(1)),
            4000
        );
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mobileErrors[0]?.id]);

    // Ref to hold current nodes for the guided tour callback (nodes defined later in component)
    const nodesRefForTour = useRef<Node[]>([]);

    // Guided Tour for checklist items
    // Find-the-link walkthrough: armed when the inline invite banner is first
    // closed (InviteBanner dispatches this once per browser).
    const [inviteWalkthroughActive, setInviteWalkthroughActive] =
        useState(false);
    // Server-backed, cross-device "seen" flag for the find-the-link tour. Held in
    // refs so the document listener + tour-end callback (registered once) read the
    // live value rather than a stale closure.
    const [inviteWalkthroughSeen, markInviteWalkthroughSeen] =
        useSeenOnce('invite_walkthrough');
    const inviteWalkthroughSeenRef = useRef(inviteWalkthroughSeen);
    inviteWalkthroughSeenRef.current = inviteWalkthroughSeen;
    const markInviteWalkthroughSeenRef = useRef(markInviteWalkthroughSeen);
    markInviteWalkthroughSeenRef.current = markInviteWalkthroughSeen;
    useEffect(() => {
        // Re-guard at the listener too: the "seen" flag is the single source of
        // truth, so even a stray dispatch can't re-show an already-seen tour.
        const onShow = () => {
            // Skip on mobile and leave the tour unseen — the spotlight UX is poor on a
            // phone, so wait until the user is on desktop to show it (seen is only written
            // when the tour actually completes, so deferring here doesn't burn it).
            if (isMobileRef.current) return;
            if (inviteWalkthroughSeenRef.current) return;
            setInviteWalkthroughActive(true);
            logActivity(EVENTS.INVITE_WALKTHROUGH_SHOWN, {
                workflow_id: workflowId,
            });
        };
        document.addEventListener(INVITE_WALKTHROUGH_EVENT, onShow);
        return () =>
            document.removeEventListener(INVITE_WALKTHROUGH_EVENT, onShow);
    }, [logActivity, workflowId]);
    // Persist "seen" (server-backed, cross-device) only when the tour actually
    // ENDS (shown then closed/completed). GuidedTourHighlight does not call these
    // if the target never renders, so the one-time walkthrough is never burned on
    // a screen that can't show it (e.g. mobile, where the invite button is hidden).
    const finishInviteWalkthrough = () => {
        markInviteWalkthroughSeenRef.current();
        setInviteWalkthroughActive(false);
        logActivity(EVENTS.INVITE_WALKTHROUGH_COMPLETED, {
            workflow_id: workflowId,
        });
    };

    // Chat-with-your-agent walkthrough: after the AI builder finishes a workflow
    // whose agent has no triggers wired in, that agent is chat-driven — so we
    // spotlight the Interface tab once so the user knows where to go and chat.
    // Armed from the builder-complete effect further down (where the live
    // node/edge refs are in scope). Seen only when it completes, so it isn't
    // burned on a screen that can't show it (e.g. mobile).
    const [agentChatWalkthroughActive, setAgentChatWalkthroughActive] =
        useState(false);
    const [agentChatWalkthroughNodeId, setAgentChatWalkthroughNodeId] =
        useState<string | null>(null);
    const [agentChatWalkthroughSeen, markAgentChatWalkthroughSeen] =
        useSeenOnce('agent_chat_walkthrough');
    const agentChatWalkthroughSeenRef = useRef(agentChatWalkthroughSeen);
    agentChatWalkthroughSeenRef.current = agentChatWalkthroughSeen;
    const markAgentChatWalkthroughSeenRef = useRef(
        markAgentChatWalkthroughSeen
    );
    markAgentChatWalkthroughSeenRef.current = markAgentChatWalkthroughSeen;
    const finishAgentChatWalkthrough = () => {
        markAgentChatWalkthroughSeenRef.current();
        setAgentChatWalkthroughActive(false);
        logActivity(EVENTS.AGENT_CHAT_WALKTHROUGH_COMPLETED, {
            workflow_id: workflowId,
        });
    };
    const agentChatWalkthroughSteps = useMemo<TourStep[]>(
        () => [
            {
                target: '[data-tour-target="interface-tab"]',
                title: 'Chat with your new agent',
                description:
                    'Your agent is ready. Open the Interface tab to start chatting with it.',
                buttonText: 'Open the chat',
                placement: 'bottom' as const,
                padding: 3,
                advanceOnTargetClick: true,
                media: <AgentChatWalkthroughArt />,
                // Switch to the Interface tab and open this agent's chat sub-tab.
                action: () => {
                    if (agentChatWalkthroughNodeId) {
                        document.dispatchEvent(
                            new CustomEvent('noclick:open-agent-chat', {
                                detail: { nodeId: agentChatWalkthroughNodeId },
                            })
                        );
                    }
                },
            },
        ],
        [agentChatWalkthroughNodeId]
    );

    // Tracks whether we've checked the sessionStorage flag for opening the setup tab on first node load
    const hasSetInitialTabRef = useRef(false);
    // Full-viewport Setup presentation (template-fork onboarding). z-40:
    // above the in-flow workspace chrome, below portaled selects/popovers
    // (z-50) and dialogs (z-[70]) so every picker inside setup still works.
    const [setupFullscreen, setSetupFullscreen] = useState(false);

    // Mirror useClickToAddNode's listener for the same event so we can also
    // bump the search-focus signal — the hook owns the open/tab logic, but we
    // own the focus signal and don't want to weave it into the hook's API.
    useEffect(() => {
        const handler = () => bumpSearchFocus();
        document.addEventListener(
            'noclick:open-flow-helper-from-node',
            handler
        );
        return () =>
            document.removeEventListener(
                'noclick:open-flow-helper-from-node',
                handler
            );
    }, [bumpSearchFocus]);

    // Phase 2: nodes/edges now live in liveGraphStore (module-level
    // Valtio proxy). useLiveGraph subscribes this component to the
    // record for `workflowId`, returning the same { nodes, edges,
    // setNodes, setEdges } shape we used to assemble manually from
    // local/valtio state. Mutations write straight into the store, so
    // remote-edit applications via presenceManager and agentic mutations
    // via setNodes/setEdges all converge on the same source of truth.
    //
    // initialNodes/initialEdges still seed the record on first mount
    // for hot-reload / cache-restore paths; subsequent workflow:get
    // replaces with the authoritative state from the BE.
    const liveGraph = useLiveGraph(workflowId || '__noop__', isSkill, {
        initialNodes,
        initialEdges,
    });
    const { nodes, edges, setNodes, setEdges } = liveGraph;

    // Live mirror of the controlled nodes/edges, read by the canvas key handlers
    // (arrow-nav, etc.) so they see current selection without re-binding their
    // listeners on every node move.
    const graphSelectionRef = useRef({ nodes, edges });
    graphSelectionRef.current = { nodes, edges };

    // Escape on the canvas: first defocus a text input (node search, empty-state
    // prompt, config field); otherwise, if the flow helper is expanded big (e.g.
    // the ~70% Enter-to-config view), shrink it back to its smaller height,
    // instantly. Capture phase so it fires before inputs that stopPropagation;
    // bails when a modal is open (palette/dialog own Escape there).
    // STACKING: whenever this handler ACTS it consumes the event, so lower
    // layers (Dashboard's Escape-closes-chat-sidebar) only fire when nothing
    // here was left to collapse — one Escape, one layer.
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== 'Escape') return;
            if (replayActiveRef.current) return;
            if (isModalOpen()) return;
            const consume = () => {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
            };
            if (isTextEntryTarget(document.activeElement)) {
                (document.activeElement as HTMLElement).blur();
                consume();
                return;
            }
            // Full screen → drop straight back to the smaller height (instant),
            // so Escape exits without needing F or the close button.
            if (isFlowHelperFullScreenRef.current) {
                setFlowHelperInstantHeight(true);
                setIsFlowHelperFullScreen(false);
                setFlowHelperHeight(Math.round(window.innerHeight * 0.3));
                consume();
                return;
            }
            if (
                isConfigViewExpandedRef.current &&
                flowHelperHeightRef.current > window.innerHeight * 0.5
            ) {
                setFlowHelperInstantHeight(true);
                setFlowHelperHeight(Math.round(window.innerHeight * 0.3));
                consume();
            }
        };
        document.addEventListener('keydown', onKeyDown, true);
        return () => document.removeEventListener('keydown', onKeyDown, true);
    }, [setFlowHelperHeight, setIsFlowHelperFullScreen]);

    // Single-key view switches, active on any editor tab so you can hop between
    // views: W=flow, I=interface, L=logs, S=setup, V=version history. Bare keys,
    // ignored while typing or under a modal. Leader sequences (G W, N W, …) are
    // consumed in the capture phase, so they never reach these.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            if (isModalOpen()) return;
            switch (e.key.toLowerCase()) {
                // Top-level tab navigation — safe in replay (the user might press
                // L to jump back to Logs and pick a different run). Don't gate.
                case 'w':
                    e.preventDefault();
                    setActiveTab('canvas');
                    break;
                case 'i':
                    e.preventDefault();
                    setActiveTab('interface');
                    break;
                case 'l':
                    e.preventDefault();
                    setActiveTab('logs');
                    break;
                case 's':
                    e.preventDefault();
                    setActiveTab('setup');
                    break;
                case 'v':
                    e.preventDefault();
                    window.dispatchEvent(
                        new CustomEvent('noclick:open-version-history')
                    );
                    break;
                case 'n': {
                    // Open the node search to ADD a node — mutating, so skip in
                    // replay where the displayed graph is a frozen snapshot.
                    if (replayActiveRef.current) break;
                    // With a node selected, prime it as the source so the new
                    // node lands connected after it (same path as a node's "+"
                    // hint); otherwise standalone.
                    e.preventDefault();
                    setFlowHelperNoAnim(true);
                    const sel = graphSelectionRef.current.nodes.find(
                        (n) => n.selected && n.type !== 'stickyNote'
                    );
                    if (sel) {
                        document.dispatchEvent(
                            new CustomEvent(
                                'noclick:open-flow-helper-from-node',
                                {
                                    detail: { nodeId: sel.id },
                                }
                            )
                        );
                    } else {
                        setFlowHelperActiveTab('home');
                        setIsConfigViewExpanded(true);
                    }
                    bumpSearchFocus();
                    break;
                }
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [
        setActiveTab,
        setFlowHelperActiveTab,
        setIsConfigViewExpanded,
        bumpSearchFocus,
    ]);

    // While the canvas is mounted, "N" adds a node — tell useLeaderShortcuts to
    // yield the key (instead of arming the new-X leader).
    useEffect(() => {
        setAddNodeShortcutActive(true);
        return () => setAddNodeShortcutActive(false);
    }, []);

    // Arrow keys traverse nodes spatially (nearest node in the pressed direction);
    // Enter opens the config view for the selected node. Canvas tab only, ignored
    // while typing or under a modal. Selection highlights + pans but doesn't open
    // the config (that's Enter) — only onNodeClick opens it.
    useEffect(() => {
        if (activeTab !== 'canvas') return;
        const onKey = (e: KeyboardEvent) => {
            if (replayActiveRef.current) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            // Runs in the CAPTURE phase (see addEventListener below) so the "am I
            // typing?" check is reliable. In the bubble phase the chat's Enter handler
            // has already run inputRef.clear() (innerHTML=''), which both detaches
            // e.target and blurs the field — so a bubble-phase check of e.target /
            // activeElement would miss it and Enter would wrongly expand the selected
            // node. Capture fires before React's bubble handlers, while e.target is
            // still the focused input. Same capture-phase reasoning as the Escape
            // handler above.
            if (
                isTextEntryTarget(e.target) ||
                isTextEntryTarget(document.activeElement)
            )
                return;
            if (isModalOpen()) return;
            const all = graphSelectionRef.current.nodes.filter(
                (n) => n.type !== 'stickyNote'
            );
            if (all.length === 0) return;
            const current = all.find((n) => n.selected) ?? null;

            if (e.key === 'Enter') {
                if (!current) return;
                e.preventDefault();
                // Expand to ~70% in config view, instantly, so there's room to edit.
                setFlowHelperNoAnim(true);
                setFlowHelperInstantHeight(true);
                setIsConfigViewExpanded(true);
                setFlowHelperActiveTab('config');
                setFlowHelperHeight(Math.round(window.innerHeight * 0.7));
                // Enter = edit intent: let the operation picker focus on open so
                // the user can type/arrow to pick. If the config was already open
                // (same node, no remount), focus it directly since the on-open
                // effect won't re-fire.
                setAutoFocusPickerOnOpen(true);
                setTimeout(() => {
                    (
                        document.querySelector(
                            '[data-operation-search]'
                        ) as HTMLElement | null
                    )?.focus();
                }, 60);
                return;
            }

            const dir = {
                ArrowRight: 1,
                ArrowLeft: 1,
                ArrowUp: 1,
                ArrowDown: 1,
            }[e.key];
            if (!dir) return;
            e.preventDefault();

            let target: Node | null = null;
            if (!current) {
                // No selection yet → start at the top-left-most node.
                target = all.reduce((a, b) =>
                    b.position.x + b.position.y < a.position.x + a.position.y
                        ? b
                        : a
                );
            } else {
                const { x: cx, y: cy } = current.position;
                let best = Infinity;
                for (const n of all) {
                    if (n.id === current.id) continue;
                    const dx = n.position.x - cx;
                    const dy = n.position.y - cy;
                    let score = Infinity;
                    if (e.key === 'ArrowRight' && dx > 0)
                        score = dx + 2 * Math.abs(dy);
                    else if (e.key === 'ArrowLeft' && dx < 0)
                        score = -dx + 2 * Math.abs(dy);
                    else if (e.key === 'ArrowDown' && dy > 0)
                        score = dy + 2 * Math.abs(dx);
                    else if (e.key === 'ArrowUp' && dy < 0)
                        score = -dy + 2 * Math.abs(dx);
                    if (score < best) {
                        best = score;
                        target = n;
                    }
                }
                if (!target) {
                    // Nothing in the pressed direction → wrap to the far edge on
                    // the opposite side so traversal cycles instead of dead-ending
                    // (right of the rightmost → leftmost, and so on).
                    const others = all.filter((n) => n.id !== current.id);
                    if (e.key === 'ArrowRight')
                        target = others.reduce(
                            (a, b) => (b.position.x < a.position.x ? b : a),
                            others[0]
                        );
                    else if (e.key === 'ArrowLeft')
                        target = others.reduce(
                            (a, b) => (b.position.x > a.position.x ? b : a),
                            others[0]
                        );
                    else if (e.key === 'ArrowDown')
                        target = others.reduce(
                            (a, b) => (b.position.y < a.position.y ? b : a),
                            others[0]
                        );
                    else if (e.key === 'ArrowUp')
                        target = others.reduce(
                            (a, b) => (b.position.y > a.position.y ? b : a),
                            others[0]
                        );
                }
            }
            if (!target) return;
            const targetId = target.id;
            // Navigating, not editing — don't let the next node's operation
            // picker grab focus (would trap further arrow traversal).
            setAutoFocusPickerOnOpen(false);
            setNodes((ns) =>
                ns.map((n) =>
                    n.selected === (n.id === targetId)
                        ? n
                        : { ...n, selected: n.id === targetId }
                )
            );
            panToNode(targetId);
        };
        // Capture phase: must see the focused input before the chat's bubble-phase
        // Enter handler clears (and blurs) it — see the typing guard in onKey.
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    }, [
        activeTab,
        setNodes,
        panToNode,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setFlowHelperHeight,
    ]);

    // Raw variables loaded from the workflow blob (setup completion writes here;
    // non-setup runs also persist via workflow_execution_handler). Consumers should
    // read the merged view from `workflowVariables` below, not this state.
    const [persistedVariables, setPersistedVariables] = useState<
        Record<string, any>
    >({});

    // ForkCanvas branch: lazy-load NodeDefinitions for whichever types are currently
    // in the workflow, so generic cards render with the same branded Icon component
    // the desktop FlatReadOnlyCard uses. Re-runs when the set of distinct types
    // changes (e.g. AI adds a new node type to the workflow). Uses the new liveGraph
    // nodes (post-rebase) as the source of truth.
    const distinctNodeTypes = useMemo(
        () =>
            Array.from(
                new Set(nodes.map((n) => n.type).filter(Boolean) as string[])
            )
                .sort()
                .join(','),
        [nodes]
    );
    useEffect(() => {
        if (!useForkCanvas) return;
        let cancelled = false;
        const types = distinctNodeTypes ? distinctNodeTypes.split(',') : [];
        loadNodeDefsFor(types).then((defs) => {
            if (!cancelled) setForkNodeDefs((curr) => ({ ...curr, ...defs }));
        });
        return () => {
            cancelled = true;
        };
    }, [useForkCanvas, distinctNodeTypes]);

    // Credential variables from set-variable nodes — provided via context to the interface tab
    const credentialVariables = useCredentialVariables(nodes);

    // Author-declared variables (Variables tab): definitions live in
    // workflows.settings so the graph autosave can never clobber them.
    const variableDefinitions = useMemo(
        () =>
            (Array.isArray(workflowSettings?.variable_definitions)
                ? workflowSettings.variable_definitions
                : []) as WorkflowVariableDefinition[],
        [workflowSettings]
    );
    const handleVariableDefinitionsChange = useCallback(
        (definitions: WorkflowVariableDefinition[]) => {
            setWorkflowSettings((prev) => ({ ...prev, variable_definitions: definitions }));
            if (!workflowId) return;
            void sendEventAsync({
                event_name: 'workflow:update',
                workflow_id: workflowId,
                settings: { variable_definitions: definitions },
            } as any).catch((e) =>
                console.error('[FlowCanvas] Failed to save variable definitions:', e)
            );
        },
        [workflowId]
    );

    // Merged view of workflow variables (definitions + persisted + live
    // set-variable outputs). All {{vars.X}} resolution on the canvas should
    // read from `workflowVariables`.
    const { resolved: workflowVariables, declared: declaredVariableNames } =
        useWorkflowVariables(nodes, persistedVariables, variableDefinitions);

    // A bound config field's editor writes THROUGH its variable (upserting a
    // definition for runtime-only vars), keeping the {{vars.x}} binding.
    const handleVariableValueChange = useCallback(
        (name: string, value: string) => {
            const defs = variableDefinitions.some((d) => d.name === name)
                ? variableDefinitions.map((d) => (d.name === name ? { ...d, value } : d))
                : [...variableDefinitions, { name, value }];
            handleVariableDefinitionsChange(defs);
        },
        [variableDefinitions, handleVariableDefinitionsChange]
    );

    // External link pill - derive URL from selected node's config (e.g. Google Sheets spreadsheet_id)
    const externalLink = useMemo(() => {
        if (!selectedNode?.type || !selectedNode.data) return null;
        const config = EXTERNAL_LINK_CONFIG[selectedNode.type];
        if (!config) return null;
        const selectedConfig = selectedNode.data.config;
        if (
            !selectedConfig ||
            typeof selectedConfig !== 'object' ||
            Array.isArray(selectedConfig)
        ) {
            return null;
        }
        const rawFieldValue = (selectedConfig as Record<string, unknown>)[
            config.field
        ];
        if (typeof rawFieldValue !== 'string') return null;
        let fieldValue: string = rawFieldValue;
        if (!fieldValue?.trim()) return null;
        if (fieldValue.includes('{{vars.')) {
            let unresolved = false;
            fieldValue = fieldValue.replace(
                /\{\{vars\.([^}]+)\}\}/g,
                (_, key) => {
                    const val = workflowVariables[key];
                    if (
                        val === undefined ||
                        val === null ||
                        String(val).trim() === ''
                    ) {
                        unresolved = true;
                        return '';
                    }
                    return String(val);
                }
            );
            if (unresolved || !fieldValue.trim() || fieldValue.includes('{{'))
                return null;
        }
        const metadata = getNodeMetadata(selectedNode.type);
        return {
            url: config.urlTemplate(fieldValue),
            label: config.label,
            bgColor: config.bgColor,
            Icon: metadata?.Icon,
        };
    }, [selectedNode?.type, selectedNode?.data, workflowVariables]);

    // Refs to access latest nodes/edges without adding to effect dependencies
    // This prevents event listener effects from re-running on every node position change
    const nodesRef = useRef(nodes);
    const edgesRef = useRef(edges);
    const workflowVariablesRef = useRef(workflowVariables);
    nodesRef.current = nodes;
    edgesRef.current = edges;
    workflowVariablesRef.current = workflowVariables;

    // Execution tracking: activeExecutions Map, logs, loadingBlockIds, plus
    // the workflow:started/complete socket listeners and relay state recovery.
    // Returns raw state + setters; the parent keeps direct write access for
    // the ~20 callsites that mutate during runWorkflow/stopWorkflow/runSingleNode.
    const {
        activeExecutions,
        isWorkflowRunning,
        hoveredExecutionId,
        loadingBlockIds,
        logs,
        setActiveExecutions,
        setHoveredExecutionId,
        setLoadingBlockIds,
        setLogs,
        activeExecutionsRef,
        completedExecutionIdsRef,
        backgroundExecutionIdsRef,
        runStartTimeRef,
        addPendingExecution,
    } = useWorkflowExecutionTracking({
        workflowId,
        nodesRef,
        setNodes,
        isMobile,
        enqueueMobileError,
    });

    // Per-node output selections from history carousel (survives panel collapse).
    // Used at execution time so single-node runs / run-from-here use the displayed output.
    const nodeOutputSelectionsRef = useRef<
        Record<string, { historyIndex: number; output: unknown }>
    >({});
    const setNodeOutputSelection = useCallback(
        (nodeId: string, historyIndex: number, output: unknown | undefined) => {
            if (output === undefined || historyIndex === 0) {
                delete nodeOutputSelectionsRef.current[nodeId];
            } else {
                nodeOutputSelectionsRef.current[nodeId] = {
                    historyIndex,
                    output,
                };
            }
        },
        []
    );

    // Track if a node is currently being dragged (ref for logic, state for rendering)
    // Declared early so validation effect can skip during drag
    const isDraggingRef = useRef(false);

    // Stable nodes reference for FlowHelperView — freezes during drag to prevent
    // expensive re-renders of the config/output panel (which renders full node data
    // including potentially large state objects). Updates on drag end.
    const stableNodesForPanel = useRef(nodes);
    // Stable nodes for navigator components — same freeze pattern to avoid O(n) scans per frame
    const stableNodesForNav = useRef(nodes);
    if (!isDraggingRef.current) {
        stableNodesForPanel.current = nodes;
        stableNodesForNav.current = nodes;
    }

    // Wiring context for edge-dependent validation (agent tool-provider
    // mode). Two-step memo: the string key is cheap to recompute on every
    // edges-identity change (xyflow rewrites the array on selection), and
    // identical content yields an identical key — so the context OBJECT'S
    // identity is stable and selection churn never retriggers validation.
    const wiredProviderIdsKey = useMemo(
        () => computeWiredProviderIdsKey(nodes, edges),
        [nodes, edges]
    );
    const validationContext = useMemo(
        () => contextFromWiringKey(wiredProviderIdsKey),
        [wiredProviderIdsKey]
    );

    // Debounced per-node config validation — drives the yellow "incomplete"
    // border and the configValid flag consumers read on `node.data`.
    useNodeConfigValidation({
        nodes,
        validationContext,
        setNodes,
        isDraggingRef,
    });

    // Keep nodesRefForTour in sync with nodes for guided tour callback
    useEffect(() => {
        nodesRefForTour.current = nodes;
    }, [nodes]);

    // Tracks the in-flight n8n import so the effect below can emit a matching
    // :end event when the edit finishes (and re-emit :start on session resume).
    const n8nImportNodeCountRef = useRef<number | null>(null);

    // Refs for AI editing and node/edge broadcast functions (populated by useCollaborativePresence below)
    // Using refs allows useCanvasWorkflowEdit to access these functions even though it's called first
    const broadcastAiEditingStartRef = useRef<
        ((nodeIds: string[]) => void) | undefined
    >(undefined);
    const broadcastAiEditingUpdateRef = useRef<
        ((nodeId: string, info: any) => void) | undefined
    >(undefined);
    const broadcastAiEditingEndRef = useRef<(() => void) | undefined>(
        undefined
    );
    const broadcastNodeAddRef = useRef<((node: Node) => void) | undefined>(
        undefined
    );
    const broadcastNodeRemoveRef = useRef<
        ((nodeId: string) => void) | undefined
    >(undefined);
    const broadcastEdgeAddRef = useRef<((edge: Edge) => void) | undefined>(
        undefined
    );
    const broadcastEdgeRemoveRef = useRef<
        ((edgeId: string) => void) | undefined
    >(undefined);
    const broadcastNodeDragRef = useRef<
        | ((nodeId: string, position: { x: number; y: number }) => void)
        | undefined
    >(undefined);

    // AI-powered workflow editing from sidebar (via NoClick)
    const {
        state: canvasEditState,
        autofillStatus: canvasAutofillStatus,
        startEdit: startCanvasEdit,
        startAutofill: startCanvasAutofill,
    } = useCanvasWorkflowEdit({
        workflowId,
        currentNodes: nodes,
        currentEdges: edges,
        onNodesChange: setNodes,
        onEdgesChange: setEdges,
        onEditComplete: () => {},
        onError: (error) => {
            console.error('[FlowCanvas] AI edit error:', error);
        },
        // Broadcast AI editing state to collaborators via refs (populated after useCollaborativePresence)
        broadcastAiEditingStart: (nodeIds) =>
            broadcastAiEditingStartRef.current?.(nodeIds),
        broadcastAiEditingUpdate: (nodeId, info) =>
            broadcastAiEditingUpdateRef.current?.(nodeId, info),
        broadcastAiEditingEnd: () => broadcastAiEditingEndRef.current?.(),
        // Broadcast node/edge changes to collaborators via refs (populated after useCollaborativePresence)
        broadcastNodeAdd: (node) => broadcastNodeAddRef.current?.(node),
        broadcastNodeRemove: (nodeId) =>
            broadcastNodeRemoveRef.current?.(nodeId),
        broadcastEdgeAdd: (edge) => broadcastEdgeAddRef.current?.(edge),
        broadcastEdgeRemove: (edgeId) =>
            broadcastEdgeRemoveRef.current?.(edgeId),
        broadcastNodeDrag: (nodeId, position) =>
            broadcastNodeDragRef.current?.(nodeId, position),
    });

    // Sync editing state with WorkflowContext for node animations
    useEffect(() => {
        setIsAiEditing(canvasEditState.isEditing);
        setEditingNodeIds(canvasEditState.affectedNodeIds);
    }, [canvasEditState.isEditing, canvasEditState.affectedNodeIds]);

    // Read by the workflow:complete listener (a memoized callback): a FAILED
    // run's results popup is suppressed while the AI builder is actively
    // editing this workflow — mid-build configs routinely fail (phantom
    // trigger runs, half-filled nodes) and the popup fights the edit stream.
    // Successful runs always pop; failures outside AI editing always pop.
    const aiEditingRef = useRef(false);
    useEffect(() => {
        aiEditingRef.current = canvasEditState.isEditing;
    }, [canvasEditState.isEditing]);

    // Close out any in-flight n8n import the moment editing stops, so the
    // badge disappears as soon as the translated graph lands (complete or
    // error — either way the import session is over).
    useEffect(() => {
        if (
            !canvasEditState.isEditing &&
            n8nImportNodeCountRef.current !== null
        ) {
            n8nImportNodeCountRef.current = null;
            document.dispatchEvent(new CustomEvent('noclick:n8n:import:end'));
        }
    }, [canvasEditState.isEditing]);

    // Auto-fit the viewport to keep the whole graph in view while the builder
    // streams nodes in. The user can take back control by panning/zooming at
    // any point — their gesture flips `autoFitEnabledRef` and we stop fitting
    // for the rest of this edit run.
    //
    // Suppress auto-fit during single-node autofills — the user is mid-edit on
    // a specific node and has the panel open at a deliberate zoom; pulling the
    // viewport out from under them feels like a bug.
    const autoFitEnabledRef = useRef(true);
    const autoFitTimerRef = useRef<number | null>(null);
    const isAutofillRun = canvasAutofillStatus.nodeId !== null;
    useEffect(() => {
        // Edit just started — re-enable auto-fit (but not for autofills).
        if (canvasEditState.isEditing && !isAutofillRun) {
            autoFitEnabledRef.current = true;
        }
    }, [canvasEditState.isEditing, isAutofillRun]);
    useEffect(() => {
        if (!canvasEditState.isEditing) return;
        if (isAutofillRun) return;
        if (!autoFitEnabledRef.current) return;
        // Debounce so we only fit once after autolayout settles (autolayout runs
        // in requestAnimationFrame after each node_added, so 80ms gives it time
        // to apply the new positions before we compute the bounding box).
        if (autoFitTimerRef.current != null) {
            clearTimeout(autoFitTimerRef.current);
        }
        autoFitTimerRef.current = window.setTimeout(() => {
            if (!autoFitEnabledRef.current) return;
            try {
                fitView({ duration: 500, padding: 0.22, maxZoom: 1.0 });
            } catch {}
            // Mirror the fit on ForkCanvas (no-op when it's not mounted). When the
            // AI builder is editing specific nodes, focus the camera on just those.
            try {
                const targets =
                    canvasEditState.affectedNodeIds.size > 0
                        ? Array.from(canvasEditState.affectedNodeIds).map(
                              (id) => ({ id })
                          )
                        : undefined;
                forkCanvasRef.current?.fitView({
                    padding: 0.22,
                    maxZoom: 1.0,
                    nodes: targets,
                });
            } catch {}
        }, 80);
        return () => {
            if (autoFitTimerRef.current != null) {
                clearTimeout(autoFitTimerRef.current);
                autoFitTimerRef.current = null;
            }
        };
    }, [
        nodes.length,
        edges.length,
        canvasEditState.isEditing,
        isAutofillRun,
        fitView,
    ]);
    // Called by <ReactFlow onMoveStart>. A non-null event means a real user
    // pan/zoom/drag (mouse wheel, touch, trackpad); null means the move is
    // programmatic (our own fitView). Only the real ones disable auto-fit.
    const handleMoveStartForAutoFit = useCallback(
        (event: MouseEvent | TouchEvent | null) => {
            if (event && canvasEditState.isEditing) {
                autoFitEnabledRef.current = false;
            }
            // Disable iframe pointer events for the duration of a real user pan/zoom so a
            // drag that crosses an interface-html-react node's iframe isn't swallowed
            // mid-gesture. Skipped for programmatic moves (event === null).
            if (event)
                canvasDivRef.current?.classList.add('nc-canvas-interacting');
        },
        [canvasEditState.isEditing]
    );

    // Feed canvas state to builder context (mount/unmount, inner tab, selected node)
    useEffect(() => {
        updateBuilderContext({ isCanvasMounted: true, innerTab: activeTab });
        return () => {
            updateBuilderContext({
                isCanvasMounted: false,
                selectedNodeId: null,
            });
        };
    }, []);
    useEffect(() => {
        updateBuilderContext({ innerTab: activeTab });
    }, [activeTab]);
    useEffect(() => {
        updateBuilderContext({ selectedNodeId: selectedNode?.id || null });
    }, [selectedNode?.id]);

    // Listen for workflow edit events from NoClick sidebar
    useEffect(() => {
        const handleWorkflowEditEvent = (
            event: CustomEvent<{
                workflowId: string;
                prompt: string;
                conversationId?: string;
                scope?: { type: 'node'; nodeId: string };
            }>
        ) => {
            const {
                workflowId: eventWorkflowId,
                prompt,
                conversationId,
                scope,
            } = event.detail;
            // Only handle events for this workflow
            if (eventWorkflowId === workflowId) {
                // Scoped edits override the canvas selection so the brain edits
                // the explicit node from the Edit panel even if the user has
                // since clicked elsewhere.
                const targetNodeId = scope?.nodeId ?? selectedNode?.id;
                startCanvasEdit(
                    prompt,
                    targetNodeId,
                    conversationId,
                    undefined,
                    scope
                );
            }
        };
        document.addEventListener(
            'noclick:workflow:edit',
            handleWorkflowEditEvent as EventListener
        );
        return () => {
            document.removeEventListener(
                'noclick:workflow:edit',
                handleWorkflowEditEvent as EventListener
            );
        };
    }, [workflowId, startCanvasEdit, selectedNode?.id]);

    // Listen for the background-generated workflow name from the first edit
    // on an empty workflow. Updates the title in place without a refetch.
    useEffect(() => {
        if (!workflowId) return;
        const unsubscribe = onSocketEvent(
            'workflow:name_generated',
            (data: {
                workflow_id: string;
                name: string;
                description?: string;
            }) => {
                if (data.workflow_id !== workflowId) return;
                onTitleChange?.(data.name);
            }
        );
        return unsubscribe;
    }, [workflowId, onTitleChange]);

    // Listen for node selection events from chat (when user clicks completed edit card)
    // Uses nodesRef.current to avoid re-subscribing on every node position change
    useEffect(() => {
        const handleSelectNode = (
            event: CustomEvent<{
                workflowId: string;
                nodeId: string;
                /** Which helper tab to land on. Defaults to config; the Run
                 *  popup's Connect button asks for credentials. */
                tab?: 'config' | 'credentials';
            }>
        ) => {
            const {
                workflowId: eventWorkflowId,
                nodeId,
                tab = 'config',
            } = event.detail;
            // Only handle events for this workflow
            if (eventWorkflowId !== workflowId) return;

            // Find the node using ref to avoid stale closure
            const node = nodesRef.current.find((n) => n.id === nodeId);
            if (!node) {
                console.warn('[FlowCanvas] Node not found:', nodeId);
                return;
            }

            // Switch to canvas view if currently in interface/other tab
            setActiveTab('canvas');

            // Select the node and update the selected property for ReactFlow visual highlight
            setSelectedNode(node);
            setNodes((currentNodes) =>
                currentNodes.map((n) => ({
                    ...n,
                    selected: n.id === nodeId,
                }))
            );

            // Open FlowHelperView and switch to the requested tab
            // But preserve collapsed state (null) if user manually collapsed the tabs
            setIsConfigViewExpanded(true);
            const currentTab =
                displayMetadataRef.current.flowHelperView.activeTab;
            if (currentTab !== null) {
                setFlowHelperActiveTab(tab);
            }

            // Pan to the node using the shared hook (ReactFlow path; no-op on mobile fork).
            panToNode(nodeId);
            // ForkCanvas (mobile): panToNode can't drive it. Defer one beat so the mobile
            // chat→dashboard view switch (Dashboard handles the same select-node event) has
            // revealed the canvas and ForkCanvas has real dimensions, then fit to the node.
            // No-op when the fork canvas isn't mounted (ref null on the desktop ReactFlow path).
            setTimeout(() => {
                try {
                    forkCanvasRef.current?.fitView({
                        nodes: [{ id: nodeId }],
                        padding: 0.4,
                        maxZoom: 1.5,
                        duration: 400,
                    });
                } catch {
                    /* fork canvas not mounted */
                }
            }, 150);
        };

        document.addEventListener(
            'noclick:workflow:select-node',
            handleSelectNode as EventListener
        );
        return () => {
            document.removeEventListener(
                'noclick:workflow:select-node',
                handleSelectNode as EventListener
            );
        };
    }, [
        workflowId,
        setSelectedNode,
        setActiveTab,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setNodes,
        panToNode,
    ]);

    // Listen for edge selection events from chat (when user clicks edge card)
    useEffect(() => {
        const handleSelectEdge = (
            event: CustomEvent<{
                workflowId: string;
                edgeId: string;
                sourceNodeId?: string;
                targetNodeId?: string;
            }>
        ) => {
            const {
                workflowId: eventWorkflowId,
                sourceNodeId,
                targetNodeId,
            } = event.detail;
            // Only handle events for this workflow
            if (eventWorkflowId !== workflowId) return;

            if (!sourceNodeId && !targetNodeId) {
                console.warn(
                    '[FlowCanvas] Neither source nor target node ID provided for edge'
                );
                return;
            }

            // Pan to edge using the shared hook
            panToEdge(
                sourceNodeId || targetNodeId!,
                targetNodeId || sourceNodeId!
            );
        };

        document.addEventListener(
            'noclick:workflow:select-edge',
            handleSelectEdge as EventListener
        );
        return () => {
            document.removeEventListener(
                'noclick:workflow:select-edge',
                handleSelectEdge as EventListener
            );
        };
    }, [workflowId, panToEdge]);

    // Listen for node data update events from inline editing (e.g., label editing via NodeToolbar)
    // Uses ref to access latest handleNodeDataUpdate callback with captureState and broadcastNodeUpdate
    useEffect(() => {
        const handler = (
            event: CustomEvent<{ nodeId: string; data: Record<string, any> }>
        ) => {
            const { nodeId, data: newData } = event.detail;
            handleNodeDataUpdateRef.current(nodeId, newData);
        };

        document.addEventListener(
            'noclick:node:update-data',
            handler as EventListener
        );
        return () => {
            document.removeEventListener(
                'noclick:node:update-data',
                handler as EventListener
            );
        };
    }, []);

    // Extract nodes with positions and dimensions for collaborative presence mock simulation
    // Dimensions are needed to center cursors on nodes (node.position is top-left corner)
    // Frozen during drag — collaborative presence doesn't need real-time position updates
    const nodesWithPositionsCacheRef = useRef<
        {
            id: string;
            position: { x: number; y: number };
            width: number;
            height: number;
        }[]
    >([]);
    const nodesWithPositions = useMemo(() => {
        if (isDraggingRef.current) return nodesWithPositionsCacheRef.current;
        const result = nodes.map((n) => ({
            id: n.id,
            position: n.position,
            width: n.width || 240, // ReactFlow default
            height: n.height || 200, // ReactFlow default
        }));
        nodesWithPositionsCacheRef.current = result;
        return result;
    }, [nodes]);

    // Remote-user mutation handlers — all delegate to the generic by-id list
    // helpers in applyNodeUpdate so the intent is one-line clear.
    const handleCollaborativeNodeDrag = useCallback(
        (nodeId: string, position: { x: number; y: number }) =>
            setNodes((prev) => patchById(prev, nodeId, { position })),
        [setNodes]
    );
    const handleCollaborativeNodeAdd = useCallback(
        (node: Node) => {
            // Wire payloads are unvalidated peer state — the ONLY node-entry
            // path without a shape guard. An id-less node has no addressable
            // identity (drop it); a position-less one is healed loudly
            // (ensureNodePosition reports the minting path to Honeycomb).
            if (!node?.id) {
                reportInvariant('collab node:add without id — dropped');
                return;
            }
            const safe = ensureNodePosition(node, 'collab node:add');
            setNodes((prev) => appendIfUnique(prev, safe));
        },
        [setNodes]
    );
    const handleCollaborativeNodeRemove = useCallback(
        (nodeId: string) => {
            if (!workflowId) return;
            // Tombstone the collaborator's delete so a CAS-conflict rebase
            // can't re-add the node while their save is still in flight.
            recordRemoteDeletedNodes(workflowId, [nodeId]);
            setNodes((prev) => removeById(prev, nodeId));
        },
        [setNodes, workflowId]
    );
    const handleCollaborativeEdgeAdd = useCallback(
        (edge: Edge) => setEdges((prev) => appendIfUnique(prev, edge)),
        [setEdges]
    );
    const handleCollaborativeEdgeRemove = useCallback(
        (edgeId: string) => setEdges((prev) => removeById(prev, edgeId)),
        [setEdges]
    );

    // Handler for when a collaborator updates a node's data
    const handleCollaborativeNodeUpdate = useCallback(
        (nodeId: string, data: Record<string, unknown>) => {
            // Remote resize: dimensions ride the node:update channel as a transport
            // hint (like _credentialMeta below) because they live at node.width /
            // node.height — OUTSIDE node.data — and the workflow relay only relays
            // known message types. Patch the top-level fields directly;
            // normalizeNodeUpdatePayload has no slot for them and would misroute
            // them into data.*. Resize messages carry only this hint, so apply and stop.
            const dims = (data as Record<string, unknown>)._dimensions as
                | { width?: number; height?: number }
                | undefined;
            if (dims) {
                setNodes((prev) =>
                    patchById(prev, nodeId, {
                        width: dims.width,
                        height: dims.height,
                    })
                );
                return;
            }
            // Instant credential display: a collaborator's credential selection carries a
            // display-only descriptor (_credentialMeta), and a deletion carries the removed
            // id(s) (_credentialRemoved). Apply both to the shared cache so an open
            // NodeCredentials resolves/drops the credential on the next render (no refetch),
            // then strip them so they never land on node.data (pure transport hints; the
            // durable share/delete on the backend is the source of truth).
            const meta = (data as Record<string, unknown>)._credentialMeta as
                | Record<string, CredentialDisplayMeta>
                | undefined;
            const removed = (data as Record<string, unknown>)
                ._credentialRemoved as string[] | undefined;
            if (meta && typeof meta === 'object')
                upsertCredentialsIntoCache(Object.values(meta));
            if (Array.isArray(removed) && removed.length)
                removeCredentialsFromCache(removed);
            if (meta || removed) {
                data = { ...data };
                delete (data as Record<string, unknown>)._credentialMeta;
                delete (data as Record<string, unknown>)._credentialRemoved;
            }
            const update = normalizeNodeUpdatePayload(
                data as Record<string, any>
            );
            setNodes((prevNodes) =>
                updateNodeInList(prevNodes, nodeId, update)
            );
        },
        [setNodes]
    );

    // Stable key for the set of credential ids referenced by this workflow's nodes —
    // recomputed only when `nodes` change, so the display_info effect below doesn't
    // re-run its scan on every unrelated node mutation. Includes workflowId so
    // switching to another workflow with the same cred ids still re-fetches.
    const referencedCredKey = useMemo(() => {
        const credIds = new Set<string>();
        for (const n of nodes) {
            const data = (n.data || {}) as Record<string, unknown>;
            const maps = [
                data.credentialIds,
                (data.config as Record<string, unknown> | undefined)
                    ?.credentialIds,
            ];
            for (const m of maps) {
                if (m && typeof m === 'object') {
                    for (const [k, v] of Object.entries(
                        m as Record<string, unknown>
                    )) {
                        if (
                            k !== 'credential_type' &&
                            typeof v === 'string' &&
                            v &&
                            !v.includes('{{')
                        )
                            credIds.add(v);
                    }
                }
            }
        }
        return credIds.size === 0 ? '' : [...credIds].sort().join(',');
    }, [nodes]);

    // Fetch display-only info (name + owner) for credentials referenced by this
    // workflow's nodes and merge it into the credential cache. Credentials are
    // resolved as the workflow OWNER at execution and are NOT shared into a
    // collaborator's account, so a collaborator's own credential:list won't include
    // the owner's creds — this lets them still SEE the name + an "owned by" tag.
    const lastCredDisplayKeyRef = useRef<string>('');
    useEffect(() => {
        if (!workflowId || !referencedCredKey) return;
        const key = workflowId + ':' + referencedCredKey;
        if (key === lastCredDisplayKeyRef.current) return;
        lastCredDisplayKeyRef.current = key;
        // Guard the in-flight response against this effect's own teardown (deps
        // change OR unmount on a workflow switch). Without this, a response that
        // lands AFTER the workflow-change clear would re-inject this workflow's
        // owner credentials into the global display cache and bleed into the next.
        let cancelled = false;
        sendEventAsync(
            CredentialDisplayInfoRequest.create({ workflow_id: workflowId })
        )
            .then((res) => {
                if (cancelled) return;
                const creds = (res as { credentials?: CredentialDisplayMeta[] })
                    ?.credentials;
                if (creds?.length) upsertCredentialsIntoCache(creds);
            })
            .catch((err) => {
                if (!cancelled)
                    console.warn(
                        '[FlowCanvas] credential:display_info failed:',
                        err
                    );
            });
        return () => {
            cancelled = true;
        };
    }, [referencedCredKey, workflowId]);

    // Scope run-as-owner display descriptors to the open workflow. We TAG them with
    // the active workflow rather than clearing on leave, so returning to a workflow
    // restores its descriptors instantly (no dependency on a display_info re-fetch),
    // while another workflow only ever shows its own (no cross-workflow bleed).
    useEffect(() => {
        setActiveCredentialWorkflow(workflowId || null);
        return () => setActiveCredentialWorkflow(null);
    }, [workflowId]);

    // IDs of all nodes in the setup subgraph (BFS from setup nodes).
    // Used to exclude setup-only interface nodes and to visually dim completed setup subgraphs.
    // Stabilize: only recompute when graph topology changes (node IDs/types + edge connections),
    // NOT on every position/data change, to avoid triggering the dimming effect in a loop.
    const topologyKeyCacheRef = useRef('');
    const topologyKey = useMemo(() => {
        if (isDraggingRef.current) return topologyKeyCacheRef.current;
        const nodeKeys = nodes
            .map((n) => `${n.id}:${n.type}`)
            .sort()
            .join(',');
        const edgeKeys = edges
            .map((e) => `${e.source}->${e.target}`)
            .sort()
            .join(',');
        const result = nodeKeys + '|' + edgeKeys;
        topologyKeyCacheRef.current = result;
        return result;
    }, [nodes, edges]);

    // Derive initial interface blocks.
    // Frozen during drag — interface blocks don't change when nodes are repositioned.
    const interfaceInitialBlocksCacheRef = useRef<
        {
            id: string;
            blockType: string;
            nodeData: Record<string, unknown> | undefined;
        }[]
    >([]);
    const interfaceInitialBlocks = useMemo(() => {
        if (isDraggingRef.current)
            return interfaceInitialBlocksCacheRef.current;
        const result = nodes
            .filter((n) => {
                if (n.type?.startsWith('interface-')) return true;
                // Agents show a fullscreen chat tab by default — unless show_in_interface is off.
                if (n.type === 'agent') {
                    const cfg = (
                        n.data as
                            | { config?: Record<string, unknown> }
                            | undefined
                    )?.config;
                    return agentShowsInInterface(cfg?.show_in_interface);
                }
                return false;
            })
            .map((n) => ({
                id: n.id,
                blockType:
                    getBlockTypeForNodeType(n.type!) ??
                    n.type!.replace('interface-', ''),
                nodeData: n.data as Record<string, unknown> | undefined,
            }));
        interfaceInitialBlocksCacheRef.current = result;
        return result;
    }, [nodes]);

    // Trigger/tool wiring per interface-shown agent — drives the Triggers and
    // Tools sections in the agent chat sidebar (AgentChatBlock). Computed here
    // because the interface tree never sees raw nodes/edges.
    const agentWiring = useMemo(() => {
        const map: Record<
            string,
            { triggers: AgentTriggerSource[]; tools: AgentWiredTool[] }
        > = {};
        for (const n of nodes) {
            if (n.type !== 'agent') continue;
            const cfg = (
                n.data as { config?: Record<string, unknown> } | undefined
            )?.config;
            if (!agentShowsInInterface(cfg?.show_in_interface)) continue;
            map[n.id] = {
                triggers: getAgentTriggerSources(n.id, nodes, edges),
                tools: getAgentToolProviders(
                    n.id,
                    nodes,
                    edges,
                    providerCredentialsMissing
                ),
            };
        }
        return map;
    }, [nodes, edges]);


    // Auto-sync: when a block is added in the Interface grid, create a corresponding ReactFlow node
    const handleInterfaceBlockAdded = useCallback(
        (blockId: string, nodeType: string) => {
            setNodes((prevNodes) => {
                // Find a non-overlapping position for the new node
                const NODE_W = 240;
                const NODE_H = 80;
                const GAP = 60;
                let pos = { x: 100, y: 100 };
                const occupied = prevNodes.map((n) => n.position);
                while (
                    occupied.some(
                        (p) =>
                            Math.abs(p.x - pos.x) < NODE_W + GAP &&
                            Math.abs(p.y - pos.y) < NODE_H + GAP
                    )
                ) {
                    pos = { x: pos.x, y: pos.y + NODE_H + GAP };
                }
                const newNode = createWorkflowNode(blockId, nodeType, pos, {});
                // Set initial dimensions for resizable interface nodes
                const nodeDef = getNodeMetadata(nodeType);
                newNode.style = {
                    width: nodeDef?.dimensions.width ?? 350,
                    height: nodeDef?.dimensions.height ?? 200,
                };
                return [...prevNodes, newNode];
            });
            logActivity(EVENTS.NODE_ADDED, {
                node_id: blockId,
                node_type: nodeType,
                workflow_id: workflowId,
                source: 'interface_block',
            });
        },
        [setNodes, logActivity, workflowId]
    );

    // Auto-sync: when a block is removed from the Interface grid, remove the corresponding ReactFlow node
    const handleInterfaceBlockRemoved = useCallback(
        (blockId: string) => {
            setNodes((prevNodes) => prevNodes.filter((n) => n.id !== blockId));
        },
        [setNodes]
    );

    // Auto-sync: when a block's config changes in the Interface grid, update the corresponding ReactFlow node
    const handleInterfaceBlockConfigChanged = useCallback(
        (blockId: string, config: Record<string, unknown>) => {
            setNodes((prevNodes) =>
                updateNodeInList(prevNodes, blockId, { config })
            );
        },
        [setNodes]
    );

    // Handler for collaborative reconnection - CRITICAL: refetch workflow to avoid stale state.
    // Skills don't use collab in v1, so this branch is dead for them — but we keep it
    // routed correctly so the function stays consistent if collab is enabled later.
    const handleCollaborativeReconnect = useCallback(() => {
        if (!workflowId) return;

        const reconnectEvent = isSkill
            ? ({
                  event_name: 'skill:get_workflow',
                  skill_id: workflowId,
              } as any)
            : WorkflowGetRequest.create({
                  workflow_id: workflowId,
              });

        sendEventWithCallback(reconnectEvent, (rawResponse: any) => {
            const response =
                isSkill && !rawResponse?.error
                    ? {
                          workflow: {
                              workflow_data: rawResponse?.body_workflow ?? {
                                  nodes: [],
                                  edges: [],
                              },
                          },
                      }
                    : rawResponse;
            if (response.error) {
                console.error(
                    '[FlowCanvas] Failed to refetch workflow on reconnect:',
                    response.error
                );
                return;
            }

            if (response.workflow?.workflow_data) {
                const workflowData = response.workflow.workflow_data;
                // Reconnect refetch is a full authoritative load: adopt the
                // server's CAS version so the next save doesn't conflict on
                // saves we missed while disconnected.
                setGraphVersion(
                    workflowId,
                    response.workflow.graph_version ?? null
                );
                // A delete made here whose save hasn't been acked (e.g. the
                // socket flapped inside the debounce window) is still in the
                // server copy — drop it before the union merge or the
                // reconnect resurrects the deletion.
                const pendingDeletes = getPendingDeletedNodeIds(workflowId);

                if (workflowData.nodes && Array.isArray(workflowData.nodes)) {
                    const loadedNodes = parseRawNodes(
                        workflowData.nodes
                    ).filter((n) => !pendingDeletes.has(n.id));
                    // Re-apply per-node last-run status on reconnect too — otherwise the
                    // refetch (mergeServerNodes, which drops _lastRunStatus) wipes the
                    // status chips/aurora when the collab socket reconnects (e.g. after
                    // backgrounding the tab and coming back to the flow).
                    const nodeStatuses = response.node_statuses as
                        | Record<string, NodeStatusInfo>
                        | undefined;
                    setNodes((prev) =>
                        applyNodeStatuses(
                            mergeServerNodes(loadedNodes, prev),
                            nodeStatuses
                        )
                    );
                }
                if (workflowData.edges && Array.isArray(workflowData.edges)) {
                    const loadedEdges = dedupeEdges(
                        workflowData.edges
                            .filter(
                                (edge: { source: string; target: string }) =>
                                    !pendingDeletes.has(edge.source) &&
                                    !pendingDeletes.has(edge.target)
                            )
                            .map((edge: any) =>
                                applyEdgeStyle({
                                    id: edge.id,
                                    source: edge.source,
                                    target: edge.target,
                                    sourceHandle: edge.sourceHandle,
                                    targetHandle: edge.targetHandle,
                                })
                            )
                    );
                    setEdges((prev) => mergeServerEdges(loadedEdges, prev));
                }

                // Reload workflow variables
                if (
                    workflowData.variables &&
                    typeof workflowData.variables === 'object'
                ) {
                    setPersistedVariables(workflowData.variables);
                }
            }
        });
    }, [workflowId, isSkill, setNodes, setEdges]);

    // Ref to hold collaborators for use in callbacks that can't directly access the hook return value
    const collaboratorsRef = useRef<Collaborator[]>([]);

    // Collaborative presence - tracks other users' cursors and selections
    const {
        collaborators,
        nodeSelections,
        updateLocalCursor,
        updateLocalSelection,
        broadcastNodeDrag,
        broadcastNodeAdd,
        broadcastNodeRemove,
        broadcastNodeUpdate,
        broadcastEdgeAdd,
        broadcastEdgeRemove,
        broadcastAiEditingStart,
        broadcastAiEditingUpdate,
        broadcastAiEditingEnd,
    } = useCollaborativePresence({
        workflowId: workflowId || '',
        nodes: nodesWithPositions,
        // Skills don't share a YJS room, so we keep collab off for them in v1.
        enabled: !!workflowId && !isSkill,
        onNodeDrag: handleCollaborativeNodeDrag,
        onNodeAdd: handleCollaborativeNodeAdd,
        onNodeRemove: handleCollaborativeNodeRemove,
        onNodeUpdate: handleCollaborativeNodeUpdate,
        onEdgeAdd: handleCollaborativeEdgeAdd,
        onEdgeRemove: handleCollaborativeEdgeRemove,
        onReconnect: handleCollaborativeReconnect,
        // Remote AI editing callbacks - update WorkflowContext so nodes can display remote editing animations
        onRemoteAiEditingStart: (userId, nodeIds) => {
            // Find collaborator name from collaborators list (use ref to access latest value)
            const collaborator = collaboratorsRef.current.find(
                (c) => c.id === userId
            );
            setRemoteAiEditing(userId, nodeIds, collaborator?.name);
        },
        onRemoteAiEditingUpdate: (userId, nodeId, info) => {
            updateRemoteAiEditingInfo(userId, nodeId, info);
        },
        onRemoteAiEditingEnd: (userId) => {
            clearRemoteAiEditing(userId);
        },
    });

    // Keep collaboratorsRef in sync with collaborators state
    useEffect(() => {
        collaboratorsRef.current = collaborators;
    }, [collaborators]);

    // Populate AI editing and node/edge broadcast refs (used by useCanvasWorkflowEdit which is called before useCollaborativePresence)
    useEffect(() => {
        broadcastAiEditingStartRef.current = broadcastAiEditingStart;
        broadcastAiEditingUpdateRef.current = broadcastAiEditingUpdate;
        broadcastAiEditingEndRef.current = broadcastAiEditingEnd;
        broadcastNodeAddRef.current = broadcastNodeAdd;
        broadcastNodeRemoveRef.current = broadcastNodeRemove;
        broadcastEdgeAddRef.current = broadcastEdgeAdd;
        broadcastEdgeRemoveRef.current = broadcastEdgeRemove;
        broadcastNodeDragRef.current = broadcastNodeDrag;
    }, [
        broadcastAiEditingStart,
        broadcastAiEditingUpdate,
        broadcastAiEditingEnd,
        broadcastNodeAdd,
        broadcastNodeRemove,
        broadcastEdgeAdd,
        broadcastEdgeRemove,
        broadcastNodeDrag,
    ]);

    // Click-to-add pipeline: clicking a node/block preview creates it (standalone
    // in the visible canvas, or connected to a primed source from a node "+"
    // hint). Owns its own source ref and listens for the add-node event.
    useClickToAddNode({
        nodesRef,
        setNodes,
        setEdges,
        setSelectedNode,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        isConfigViewExpanded,
        setFreshlyDroppedNodeId,
        broadcastNodeAdd,
        broadcastEdgeAdd,
        broadcastEdgeRemove,
        workflowInterfaceRef,
        flowHelperHeightRef,
        panToNode,
        broadcastNodeDrag: useCallback(
            (nodeId: string, position: { x: number; y: number }) =>
                broadcastNodeDragRef.current?.(nodeId, position),
            []
        ),
        logActivity,
        workflowId,
    });

    // Throttle cursor updates to ~30fps to avoid overwhelming the network
    const lastCursorUpdateRef = useRef(0);
    const CURSOR_THROTTLE_MS = 33; // ~30fps

    // Handle mouse movement over the canvas
    const handleCanvasMouseMove = useCallback(
        (event: React.MouseEvent) => {
            const now = Date.now();
            if (now - lastCursorUpdateRef.current < CURSOR_THROTTLE_MS) return;
            lastCursorUpdateRef.current = now;

            if (screenToFlowPosition) {
                const position = screenToFlowPosition({
                    x: event.clientX,
                    y: event.clientY,
                });
                updateLocalCursor(position);
            }
        },
        [screenToFlowPosition, updateLocalCursor]
    );

    // Handle mouse leaving the canvas
    const handleCanvasMouseLeave = useCallback(() => {
        updateLocalCursor(null);
    }, [updateLocalCursor]);

    // Handle drag start - update cursor position immediately
    const handleNodeDragStart = useCallback(
        (event: React.MouseEvent) => {
            if (screenToFlowPosition) {
                const position = screenToFlowPosition({
                    x: event.clientX,
                    y: event.clientY,
                });
                updateLocalCursor(position);
            }
        },
        [screenToFlowPosition, updateLocalCursor]
    );

    // Handle continuous drag - update cursor during node drag (with throttling)
    const handleNodeDrag = useCallback(
        (event: React.MouseEvent) => {
            const now = Date.now();
            if (now - lastCursorUpdateRef.current < CURSOR_THROTTLE_MS) return;
            lastCursorUpdateRef.current = now;

            if (screenToFlowPosition) {
                const position = screenToFlowPosition({
                    x: event.clientX,
                    y: event.clientY,
                });
                updateLocalCursor(position);
            }
        },
        [screenToFlowPosition, updateLocalCursor]
    );

    // Handle drag end - restore cursor position (onMouseMove may not fire until mouse actually moves)
    const handleNodeDragStop = useCallback(
        (event: React.MouseEvent) => {
            if (screenToFlowPosition) {
                const position = screenToFlowPosition({
                    x: event.clientX,
                    y: event.clientY,
                });
                updateLocalCursor(position);
            }
        },
        [screenToFlowPosition, updateLocalCursor]
    );

    // Note: Cursor rendering is handled by the CollaborativeCursors overlay component
    // which uses flowToScreenPosition for reliable position updates during drag operations

    // Store latest callbacks in refs to avoid stale closures in the persistent listener
    const screenToFlowPositionRef = useRef(screenToFlowPosition);
    const updateLocalCursorRef = useRef(updateLocalCursor);
    useEffect(() => {
        screenToFlowPositionRef.current = screenToFlowPosition;
        updateLocalCursorRef.current = updateLocalCursor;
    }, [screenToFlowPosition, updateLocalCursor]);

    // Persistent pointer event listener that updates cursor during drag
    // Using a ref-based check avoids useEffect timing issues
    useEffect(() => {
        const handlePointerMove = (event: PointerEvent) => {
            // Only process during drag (check ref, not state, for immediate response)
            if (!isDraggingRef.current) return;

            const now = Date.now();
            if (now - lastCursorUpdateRef.current < CURSOR_THROTTLE_MS) return;
            lastCursorUpdateRef.current = now;

            if (screenToFlowPositionRef.current) {
                const position = screenToFlowPositionRef.current({
                    x: event.clientX,
                    y: event.clientY,
                });
                updateLocalCursorRef.current(position);
            }
        };

        document.addEventListener('pointermove', handlePointerMove);
        return () =>
            document.removeEventListener('pointermove', handlePointerMove);
    }, []); // Empty deps - persistent listener

    // Track deleted node IDs since last save (for cron schedule cleanup)
    const deletedNodeIdsRef = useRef<Set<string>>(new Set());

    // Undo/Redo functionality with keyboard shortcuts
    const {
        undo,
        redo,
        canUndo,
        canRedo,
        captureState,
        startBatch,
        endBatch,
        resetBaseline: resetUndoBaseline,
    } = useWorkflowUndoRedo(initialNodes, initialEdges, {
            historyLimit: 50,
            onNodesChange: setNodes,
            onEdgesChange: setEdges,
            // Collaboration callbacks for undo/redo changes
            onNodeAdded: broadcastNodeAdd,
            onNodeRemoved: broadcastNodeRemove,
            onEdgeAdded: broadcastEdgeAdd,
            onEdgeRemoved: broadcastEdgeRemove,
            onNodePositionChange: broadcastNodeDrag,
        });

    // Agent chat sidebar wiring: add a trigger (dataflow edge into the agent)
    // or a tool provider (top→bottom edge) without leaving the Interface tab.
    // Direct state manipulation is the interface-mode pattern (the ReactFlow
    // instance isn't mounted there) — same as handleInterfaceBlockAdded.
    const handleAgentWiringAdd = useCallback(
        (
            agentNodeId: string,
            nodeType: string,
            role: 'trigger' | 'tool',
            operation?: string
        ): string | void => {
            const agent = nodesRef.current.find((n) => n.id === agentNodeId);
            if (!agent) return;
            const newId = generateNodeId(nodeType);
            const siblingCount = edgesRef.current.filter(
                (e) =>
                    e.target === agentNodeId &&
                    (role === 'tool'
                        ? e.targetHandle === 'bottom'
                        : e.targetHandle !== 'bottom')
            ).length;
            // Triggers stack to the LEFT of the agent, providers BELOW — matching
            // the autolayout conventions for both roles.
            const position =
                role === 'tool'
                    ? {
                          x: agent.position.x - 60 + siblingCount * 180,
                          y: agent.position.y + 270,
                      }
                    : {
                          x: agent.position.x - 300,
                          y: agent.position.y + siblingCount * 150,
                      };
            const newNode = createWorkflowNode(
                newId,
                nodeType,
                position,
                {},
                operation ? { operation } : {}
            );
            setNodes((prev) => [...prev, newNode]);
            broadcastNodeAddRef.current?.(newNode);
            autoSelectCredentialsForNewNode(
                newNode,
                setNodes,
                workflowId ?? null
            );
            const edge = applyEdgeStyle(
                createStyledEdge(
                    role === 'tool'
                        ? {
                              source: newId,
                              target: agentNodeId,
                              sourceHandle: 'top',
                              targetHandle: 'bottom',
                          }
                        : { source: newId, target: agentNodeId }
                )
            );
            setEdges((prev) => [...prev, edge]);
            broadcastEdgeAddRef.current?.(edge);
            setTimeout(
                () => captureState(nodesRef.current, edgesRef.current),
                0
            );
            logActivity(EVENTS.NODE_ADDED, {
                node_id: newId,
                node_type: nodeType,
                workflow_id: workflowId,
                source: `agent_chat_sidebar_${role}`,
            });
            // The palette's tool flow continues into the in-modal allowlist
            // config step for the node it just created.
            return newId;
        },
        [setNodes, setEdges, captureState, workflowId, logActivity]
    );

    // Remove a wired trigger/tool from the sidebar: drop the edge, and the
    // node too when nothing else connects to it — interface users can't see
    // the canvas to clean up orphans.
    const handleAgentWiringRemove = useCallback(
        (edgeId: string, nodeId: string) => {
            setEdges((prev) => removeById(prev, edgeId));
            broadcastEdgeRemoveRef.current?.(edgeId);
            const hasOtherEdges = edgesRef.current.some(
                (e) =>
                    e.id !== edgeId &&
                    (e.source === nodeId || e.target === nodeId)
            );
            if (!hasOtherEdges) {
                setNodes((prev) => removeById(prev, nodeId));
                broadcastNodeRemoveRef.current?.(nodeId);
                deletedNodeIdsRef.current.add(nodeId);
            }
            setTimeout(
                () => captureState(nodesRef.current, edgesRef.current),
                0
            );
        },
        [setNodes, setEdges, captureState]
    );

    // Patch a WIRED node's config from the sidebar (e.g. a provider's
    // agent_tool_operations allowlist) — not the agent block's own config.
    const handleWiredNodeConfigPatch = useCallback(
        (nodeId: string, config: Record<string, unknown>) => {
            setNodes((prev) => updateNodeInList(prev, nodeId, { config }));
        },
        [setNodes]
    );

    const handleWiredNodeCredentialsChange = useCallback(
        (nodeId: string, credentialIds: Record<string, string>) => {
            setNodes((prev) =>
                updateNodeInList(prev, nodeId, { credentialIds })
            );
            authorizeCredentialsForWorkflow(workflowId, credentialIds);
        },
        [setNodes, workflowId]
    );

    // Live accessor for the palette's config step. Ref-based read is safe:
    // re-renders are driven by the agentWiring memo (new identity on every
    // nodes/edges change), so callers re-invoke this on each change.
    const getWiredNodeData = useCallback((nodeId: string) => {
        const n = nodesRef.current.find((nd) => nd.id === nodeId);
        if (!n) return null;
        const data = (n.data ?? {}) as Record<string, unknown>;
        return {
            nodeData: data,
            config: (data.config ?? {}) as Record<string, unknown>,
            credentialIds: (data.credentialIds ?? {}) as Record<string, string>,
        };
    }, []);

    // Copy/Paste functionality for workflow nodes and edges
    // n8n workflows are routed to backend for AI-powered conversion. Returned
    // imperative API also drives the right-click context menu's Copy/Cut/Paste
    // items so they share the same serialization + clipboard contract.
    const { copySelection, pasteFromClipboard } = useWorkflowCopyPaste({
        nodes,
        edges,
        activeTab,
        setNodes,
        setEdges,
        screenToFlowPosition,
        captureState,
        onN8nWorkflowPaste: (n8nJson: string) => {
            const workflow = extractN8nWorkflowFromClipboard(n8nJson);
            if (!workflow) {
                console.error(
                    '[FlowCanvas] Failed to parse n8n workflow JSON on paste'
                );
                return;
            }
            // Let the prompt input and chat sidebar show the n8n-import badge
            // while the translation is in flight. Matching :end event fires
            // when canvasEditState transitions out of 'editing'.
            n8nImportNodeCountRef.current = workflow.nodes?.length ?? 0;
            // Surface the chat sidebar so the badge bubble is immediately
            // visible, matching the empty-state prompt flow.
            document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
            document.dispatchEvent(
                new CustomEvent('noclick:n8n:import:start', {
                    detail: { nodeCount: n8nImportNodeCountRef.current },
                })
            );
            // Pass the raw workflow via the dedicated n8n_workflow field so the
            // backend brain enters n8n-import mode. The prompt stays short —
            // the source nodes are injected into the system prompt separately.
            startCanvasEdit(
                'Import this n8n workflow into NoClick.',
                undefined,
                undefined,
                workflow as unknown as Record<string, unknown>
            );
        },
        // Broadcast pasted nodes/edges to collaborators for real-time sync
        broadcastNodeAdd,
        broadcastEdgeAdd,
        // Interface layout refs for copy/paste of interface block positions/sizes
        interfaceGridStateRef,
        workflowInterfaceRef,
    });

    // MCP handler for AI agent workflow manipulation
    useWorkflowMCPHandler({
        nodes,
        edges,
        selectedNode,
        workflowId,
        workflowName: workflowTitle,
        isWorkflowRunning,
        setNodes: setNodes,
        setEdges: setEdges,
        captureState,
        interfaceGridStateRef,
        workflowInterfaceRef,
        onRunWorkflow: () => {
            // Trigger the runWorkflow function when MCP requests workflow execution
            // This will be called from the hook's handleRunWorkflow
            if (workflowId) {
                addPendingExecution();
                const runId = `run-${Date.now()}`;
                const runningLog: WorkflowExecutionLog = {
                    id: runId,
                    timestamp: new Date(),
                    status: 'running',
                    message: `Executing workflow with ${nodes.length} nodes...`,
                };
                setLogs((prev) => [runningLog, ...prev]);
                const graph = serializeGraphForExecution(nodes, edges);
                sendEvent(
                    WorkflowExecuteRequest.create({
                        workflow_id: workflowId,
                        nodes: graph.nodes,
                        edges: graph.edges,
                        replay_nodes: graph.nodes,
                        replay_edges: graph.edges,
                    })
                );
            }
        },
        onRunSingleNode: (nodeId: string) => {
            if (!workflowId) {
                return { success: false, error: 'No workflow ID' };
            }

            const result = prepareNodeExecution(
                nodeId,
                nodes,
                edges,
                nodeOutputSelectionsRef.current
            );
            if (!result.success) {
                return { success: false, error: result.error };
            }

            addPendingExecution();
            const runningLog: WorkflowExecutionLog = {
                id: `run-${Date.now()}`,
                timestamp: new Date(),
                status: 'running',
                message: `Executing node ${nodeId}...`,
            };
            setLogs((prev) => [runningLog, ...prev]);
            const replayGraph = serializeGraphForExecution(nodes, edges);
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    nodes: result.nodes,
                    edges: result.edges,
                    replay_nodes: replayGraph.nodes,
                    replay_edges: replayGraph.edges,
                })
            );

            return { success: true };
        },
        onNavigateToWorkflow,
    });

    // MCP builder events for external MCP clients (Claude Code, Cursor).
    // The hook handles node_added/updated/removed/edge_added mutations
    // through setNodes/setEdges; from there they flow through the same
    // recordGraphSnapshot effect any user edit does, so liveGraphStore
    // sees them. The old `lastMCPEventRef` 3s save-skip guard is gone —
    // see recordGraphSnapshot effect for the rationale.
    useMCPBuilderEvents({
        workflowId,
        setNodes: setNodes,
        setEdges: setEdges,
    });

    // Sync selectedNode with updated nodes array when node data changes
    // Skips during drag for performance - position changes don't affect node data
    useEffect(() => {
        // Skip sync during drag - only position changes, not data
        if (isDraggingRef.current) return;

        if (selectedNode) {
            // Find the updated version of the selected node
            const updatedNode = nodes.find((n) => n.id === selectedNode.id);
            const needsSync = updatedNode && updatedNode !== selectedNode;
            const hasOutputBefore = !!selectedNode.data?.output;
            const hasOutputAfter = !!updatedNode?.data?.output;

            if (needsSync) {
                setSelectedNode(updatedNode);
            }
        }
    }, [nodes, selectedNode]);

    // Restore selectedNode from cached selectedNodeId when nodes are loaded
    // This handles the case where local cache loads selectedNodeId before backend response
    // Skips during drag for performance
    useEffect(() => {
        // Skip during drag - restoration not needed while dragging
        if (isDraggingRef.current) return;

        // Skip if there's a pending navigation selection - let that effect handle selection
        if (getPendingNodeSelection()) {
            return;
        }

        const cachedSelectedId = displayMetadata.selectedNodeId;
        if (cachedSelectedId && nodes.length > 0 && !selectedNode) {
            const nodeToSelect = nodes.find((n) => n.id === cachedSelectedId);
            if (nodeToSelect) {
                setSelectedNodeInternal(nodeToSelect);
                // Also update node's selected property for ReactFlow visual highlight
                setNodes((currentNodes) =>
                    currentNodes.map((n) => ({
                        ...n,
                        selected: n.id === cachedSelectedId,
                    }))
                );
            }
        }
    }, [displayMetadata.selectedNodeId, nodes, selectedNode, setNodes]);

    // Apply viewport after it's loaded from backend (onInit fires before backend data arrives)
    // For new/forked workflows with no saved viewport, auto-fit to center the workflow
    // Track if we've already applied viewport to prevent re-applying on subsequent viewport changes
    // Reset the setup-tab latch when workflow changes (the viewport hook owns
    // its own workflow-change reset for the two viewport refs).
    useEffect(() => {
        hasSetInitialTabRef.current = false;
        // A fullscreen onboarding never follows the user to another workflow.
        setSetupFullscreen(false);
    }, [workflowId]);

    // Viewport plumbing: instant restore via module cache, auto-fit on first
    // load, persist on user pan/zoom, shift up to clear the FlowHelperView.
    const { safeViewport, onInit, onMoveEnd } = useCanvasViewport({
        workflowId,
        isReactFlowReady,
        hasLoadedWorkflow: hasLoadedWorkflowRef.current,
        pendingAnimationRef,
        viewport,
        setViewport,
        setReactFlowViewport,
        fitView,
        getViewport,
        workflowLoadedTrigger,
        isConfigViewExpanded,
        isFlowHelperFullScreen,
        flowHelperHeight,
        isMobile,
        nodeCount: nodes.length,
        isSyncing,
        setIsReactFlowReady,
    });

    // Pairs with handleMoveStartForAutoFit — re-enables iframe pointer events once
    // the pan/zoom gesture finishes, then forwards to the viewport-persistence handler.
    const handleMoveEnd = useCallback(
        (event: unknown, vp: unknown) => {
            canvasDivRef.current?.classList.remove('nc-canvas-interacting');
            onMoveEnd(event, vp);
        },
        [onMoveEnd]
    );

    // Populate the node setters ref for the parent component to use
    useEffect(() => {
        if (nodeSettersRef) {
            nodeSettersRef.current = {
                setNodes,
                setEdges,
                getNodes: () => nodesRef.current,
                // Callback to select node and open config view after drag-drop creation
                onNodeCreated: (nodeId: string) => {
                    // Find the newly created node and select it
                    setNodes((currentNodes) => {
                        const createdNode = currentNodes.find(
                            (n) => n.id === nodeId
                        );
                        if (createdNode) {
                            // Update selected node state
                            setSelectedNode(createdNode);
                            // Open FlowHelper and switch to config tab
                            setIsConfigViewExpanded(true);
                            setFlowHelperActiveTab('config');
                        }
                        // Mark this node as selected in ReactFlow
                        return currentNodes.map((n) => ({
                            ...n,
                            selected: n.id === nodeId,
                        }));
                    });
                },
                // Broadcast new node to collaborators
                broadcastNodeAdd,
                broadcastEdgeAdd,
                // Reverse auto-sync: add a block to the interface grid
                addInterfaceBlock: (blockId: string, blockType: string) => {
                    workflowInterfaceRef.current?.addBlock(blockId, blockType);
                },
                setFreshlyDroppedNodeId,
            };
        }
    }, [
        nodeSettersRef,
        setNodes,
        setEdges,
        setSelectedNode,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        broadcastNodeAdd,
        broadcastEdgeAdd,
    ]);

    // Get sticky note renderer and z-index management
    const { stickyNoteRenderer, recalculateZIndex } = useStickyNoteNode({
        setNodes,
    });

    // Build ReactFlow nodeTypes mapping from registry
    // Includes collaborator cursor as a special non-interactive node type
    const nodeTypes = useMemo(
        () =>
            buildReactFlowNodeTypes({
                stickyNote: stickyNoteRenderer,
                collaboratorCursor: CollaboratorCursorNode,
            }),
        [stickyNoteRenderer]
    );

    // Build ReactFlow edgeTypes mapping for custom edges
    const edgeTypes = useMemo(
        () => ({
            animated: AnimatedWorkflowEdge,
        }),
        []
    );

    // Helper to check if workflowId is valid for database operations
    // Excludes demo workflows and temporary IDs (created optimistically before backend responds)
    const isValidWorkflowId =
        workflowId &&
        !workflowId.startsWith('workflow_demo') &&
        !workflowId.startsWith('temp-');

    // Track previous workflowId to detect temp→real swaps
    const prevWorkflowIdRef = useRef<string | undefined>(workflowId);

    // ─── Shared parse helpers for workflow:get and cache restore ──────────
    const parseRawNodes = useCallback((rawNodes: any[]): Node[] => {
        return rawNodes.map((node: any) => {
            if (!node.config) {
                console.error('[FlowCanvas] Node missing config:', node);
                throw new Error(`Node ${node.id} is missing config`);
            }
            const config = node.config;
            // Node outputs live solely in the CAS now — never lifted from the graph
            // JSONB. Strip any legacy embedded output/markers so a pre-cutover
            // workflows.workflow blob can't shadow the fresh CAS output that
            // workflow:get_node_outputs hydrates after load.
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const {
                output: _staleOutput,
                _outputStoredLocally,
                _outputSizeBytes,
                ...cleanConfig
            } = config;
            let outputData: { output?: unknown; outputTimestamp?: number } = {};
            if (node.type === 'state-manager') {
                const stateValue = cleanConfig.state || {};
                outputData = {
                    output: {
                        type: 'state_manager',
                        status: 'preview',
                        state: stateValue,
                    },
                    outputTimestamp: Date.now(),
                };
            }
            const reactFlowNode = createWorkflowNode(
                node.id,
                node.type,
                node.position,
                cleanConfig,
                outputData
            );
            if (node.width || node.height) {
                (reactFlowNode as any).style = {
                    width: node.width,
                    height: node.height,
                };
            } else if (node.type?.startsWith('interface-')) {
                const nodeDef = getNodeMetadata(node.type);
                if (nodeDef) {
                    (reactFlowNode as any).style = {
                        width: nodeDef.dimensions.width,
                        height: nodeDef.dimensions.height,
                    };
                }
            }
            return reactFlowNode;
        });
    }, []);

    const parseRawEdges = useCallback((rawEdges: any[]): Edge[] => {
        return dedupeEdges(
            rawEdges.map((edge: any) =>
                applyEdgeStyle({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    sourceHandle: edge.sourceHandle,
                    targetHandle: edge.targetHandle,
                })
            )
        );
    }, []);

    // ─── Restore cached workflow data from IndexedDB for instant render ───
    // parseRawNodes/parseRawEdges/the setters are all stable (useCallback+[]
    // / useState setters), so listing them in deps doesn't cause re-fires.
    useEffect(() => {
        if (!isValidWorkflowId) return;
        // liveGraphStore outlives canvas mounts: when it already holds this
        // workflow's graph (same-session remount, or agentic/remote edits
        // that landed while unmounted), the proxy is strictly fresher than
        // the IndexedDB snapshot from the last workflow:get. Applying the
        // snapshot over it would resurrect nodes deleted since then.
        if (hasLiveGraphState(workflowId)) return;
        valtioCache
            .get<{
                nodes: any[];
                edges: any[];
                interface?: any;
                variables?: any;
            }>(`workflow-canvas:${workflowId}`)
            .then((cached) => {
                // Only apply if workflow:get hasn't completed yet, and
                // nothing populated the store while the read was in flight.
                if (
                    !cached ||
                    hasLoadedWorkflowRef.current ||
                    hasLiveGraphState(workflowId)
                ) {
                    return;
                }
                if (cached.nodes?.length > 0) {
                    try {
                        const cachedNodes = parseRawNodes(cached.nodes);
                        cacheRestoredNodeIdsRef.current = new Set(
                            cachedNodes.map((n) => n.id)
                        );
                        setNodes(cachedNodes);
                    } catch {
                        /* ignore parse errors from stale cache */
                    }
                }
                if (cached.edges?.length > 0) {
                    try {
                        const cachedEdges = parseRawEdges(cached.edges);
                        cacheRestoredEdgeIdsRef.current = new Set(
                            cachedEdges.map((e) => e.id)
                        );
                        setEdges(cachedEdges);
                    } catch {
                        /* ignore */
                    }
                }
                if (cached.variables) setPersistedVariables(cached.variables);
            });
    }, [
        workflowId,
        isValidWorkflowId,
        parseRawNodes,
        parseRawEdges,
        setNodes,
        setEdges,
        setInterfaceGridState,
        setPersistedVariables,
    ]);

    // Load workflow data from backend when component mounts
    useEffect(() => {
        let cancelWorkflowGet: (() => void) | undefined;
        let cancelled = false;

        const prevId = prevWorkflowIdRef.current;
        prevWorkflowIdRef.current = workflowId;

        // Detect temp→real ID swap (hot-swap scenario)
        const isIdSwap =
            prevId?.startsWith('temp-') &&
            workflowId &&
            !workflowId.startsWith('temp-');
        if (isIdSwap) {
            // Mark as loaded so saves will work, but don't overwrite local changes
            hasLoadedWorkflowRef.current = true;
            setGraphLoaded(workflowId, true);
            return;
        }

        // Only load if we have a valid workflow ID (not demo or temp)
        if (!isValidWorkflowId) {
            return;
        }

        // Skill mode: fetch via skill:get_workflow and adapt the response shape
        // to match what the rest of this effect expects (response.workflow.workflow_data).
        const initialEvent = isSkill
            ? ({
                  event_name: 'skill:get_workflow',
                  skill_id: workflowId,
              } as any)
            : WorkflowGetRequest.create({
                  workflow_id: workflowId,
              });

        cancelWorkflowGet = sendEventWithCallback(
            initialEvent,
            (rawResponse: any) => {
                const response =
                    isSkill && !rawResponse?.error
                        ? {
                              workflow: {
                                  name: 'Skill workflow',
                                  settings: undefined,
                                  workflow_data: rawResponse?.body_workflow ?? {
                                      nodes: [],
                                      edges: [],
                                  },
                              },
                          }
                        : rawResponse;
                if (response.error) {
                    console.error(
                        '[FlowCanvas] Failed to load workflow:',
                        response.error
                    );
                    setIsSyncing(false);
                    const errorMsg =
                        response.error.includes('access denied') ||
                        response.error.includes('not found')
                            ? "You don't have access to this workflow"
                            : 'Failed to load workflow';
                    setWorkflowLoadError(errorMsg);
                    toast.error(errorMsg);
                } else if (response.workflow?.workflow_data) {
                    const workflowData = response.workflow.workflow_data;

                    // Mark that we've loaded the workflow (unblocks autosave)
                    hasLoadedWorkflowRef.current = true;
                    setGraphLoaded(workflowId, true);
                    setGraphVersion(
                        workflowId,
                        response.workflow.graph_version ?? null
                    );
                    setIsSyncing(false);
                    setWorkflowLoadedTrigger((t) => t + 1);

                    // Consume the ids the IndexedDB restore injected: the
                    // server response is authoritative for those, so any it
                    // no longer contains must be dropped from the merge
                    // below instead of union-preserved (see the refs' decl).
                    const staleNodeIds = cacheRestoredNodeIdsRef.current;
                    const staleEdgeIds = cacheRestoredEdgeIdsRef.current;
                    cacheRestoredNodeIdsRef.current = new Set();
                    cacheRestoredEdgeIdsRef.current = new Set();

                    // Cache raw workflow data to IndexedDB for instant restore on next load
                    // Use JSON round-trip to strip any non-cloneable values (functions, etc.)
                    try {
                        const cacheData = JSON.parse(
                            JSON.stringify({
                                nodes: workflowData.nodes,
                                edges: workflowData.edges,
                                interface: workflowData.interface,
                                variables: workflowData.variables,
                            })
                        );
                        valtioCache.set(
                            `workflow-canvas:${workflowId}`,
                            cacheData
                        );
                    } catch (e) {
                        console.warn(
                            '[FlowCanvas] Cache write skipped (serialization error):',
                            e
                        );
                    }

                    // Update parent with actual workflow name (fixes "Loading..." stuck issue)
                    // Only update if we have a callback and the name is different from current title
                    if (
                        onTitleChange &&
                        response.workflow.name &&
                        response.workflow.name !== workflowTitle
                    ) {
                        onTitleChange(response.workflow.name);
                    }

                    // Load workflow settings
                    if (response.workflow.settings) {
                        setWorkflowSettings(response.workflow.settings);
                    }

                    // Load nodes from BE; merge preserves transient FE-only
                    // state (mcpAnimationState from agentic events, output
                    // overlays) and any in-canvas nodes the BE hasn't yet
                    // persisted. See mergeServerNodes for details.
                    // Captured merge results re-anchor the undo baseline
                    // below — undo must never walk beneath the loaded graph.
                    let mergedNodes: Node[] = [];
                    let mergedEdges: Edge[] = [];
                    if (
                        workflowData.nodes &&
                        Array.isArray(workflowData.nodes)
                    ) {
                        // Tombstones: a node deleted here whose save hasn't
                        // been acked yet is still in the server copy — the
                        // union merge below must not resurrect it.
                        const pendingDeletes =
                            getPendingDeletedNodeIds(workflowId);
                        const loadedNodes = parseRawNodes(
                            workflowData.nodes
                        ).filter((n) => !pendingDeletes.has(n.id));
                        // Per-node last-run status rides along with workflow:get, so the
                        // "✓/✗ N ago" chips render in THIS paint with the graph rather than
                        // popping in via a later round-trip. Applied in the same setNodes as
                        // the graph merge. Skip nodes a live run already owns.
                        const nodeStatuses = response.node_statuses as
                            | Record<string, NodeStatusInfo>
                            | undefined;
                        const serverNodeIds = new Set(
                            loadedNodes.map((n) => n.id)
                        );
                        setNodes((prev) => {
                            mergedNodes = applyNodeStatuses(
                                mergeServerNodes(
                                    loadedNodes,
                                    dropStaleCacheEntries(
                                        prev,
                                        staleNodeIds,
                                        serverNodeIds
                                    )
                                ),
                                nodeStatuses
                            );
                            return mergedNodes;
                        });

                        // Fetch outputs from the dedicated server-side table
                        // and merge into nodes. Cold-load only — if the live
                        // workflow:node:output channel has already populated
                        // a node (race when opening an actively-running
                        // workflow), the REST snapshot is older and must not
                        // overwrite it.
                        sendEventWithCallback(
                            {
                                event_name: 'workflow:get_node_outputs',
                                workflow_id: workflowId,
                            } as any,
                            (resp: any) => {
                                // Outputs only — last-run status now arrives with the
                                // graph via workflow:get (see above), not here.
                                const outputs = resp?.outputs;
                                if (
                                    !outputs ||
                                    Object.keys(outputs).length === 0
                                )
                                    return;
                                setNodes((currentNodes) =>
                                    currentNodes.map((n) => {
                                        const serverOutput = outputs[n.id];
                                        if (serverOutput === undefined)
                                            return n;
                                        if (n.data?.output !== undefined)
                                            return n;
                                        return applyNodeUpdate(n, {
                                            extras: {
                                                output: serverOutput,
                                                outputTimestamp: Date.now(),
                                            },
                                        });
                                    })
                                );
                            }
                        );
                    }

                    if (
                        workflowData.edges &&
                        Array.isArray(workflowData.edges)
                    ) {
                        const pendingDeletes =
                            getPendingDeletedNodeIds(workflowId);
                        const loadedEdges = parseRawEdges(
                            workflowData.edges
                        ).filter(
                            (e) =>
                                !pendingDeletes.has(e.source) &&
                                !pendingDeletes.has(e.target)
                        );
                        const serverEdgeIds = new Set(
                            loadedEdges.map((e) => e.id)
                        );
                        setEdges((prev) => {
                            mergedEdges = mergeServerEdges(
                                loadedEdges,
                                dropStaleCacheEntries(
                                    prev,
                                    staleEdgeIds,
                                    serverEdgeIds
                                )
                            );
                            return mergedEdges;
                        });
                    }

                    // Interface layout has two persistence layers:
                    // 1. local-only useCachedValtioState for instant editor reloads;
                    // 2. workflow.workflow.interface for cross-user/template/fork hydration.
                    // Prefer local state when it exists. If this browser has never opened the
                    // workflow, hydrate from the backend copy and mirror it into liveGraphStore
                    // immediately so the first autosave cannot erase the published layout.
                    const backendInterfaceState = workflowData.interface as
                        | InterfaceGridState
                        | undefined;
                    if (backendInterfaceState?.layout?.length) {
                        void (async () => {
                            const interfaceCacheKey = `/workflow/${workflowId}:interfaceGridState`;
                            const [sessionState, idbState] = await Promise.all([
                                valtioSessionCache.get<InterfaceGridState>(
                                    interfaceCacheKey
                                ),
                                valtioCache.get<InterfaceGridState>(
                                    interfaceCacheKey
                                ),
                            ]);
                            const hasLocalInterfaceLayout = [
                                sessionState,
                                idbState,
                                interfaceGridStateRef.current,
                            ].some((state) => (state?.layout?.length ?? 0) > 0);
                            if (cancelled || hasLocalInterfaceLayout) return;
                            interfaceGridStateRef.current =
                                backendInterfaceState;
                            setInterfaceGridState(backendInterfaceState);
                            recordGraphSnapshot(
                                workflowId,
                                isSkill,
                                {
                                    interfaceGridState: backendInterfaceState,
                                    variables: workflowVariablesRef.current,
                                    displayMetadata: displayMetadataRef.current,
                                },
                                /* markDirty */ false
                            );
                        })();
                    }

                    // Load workflow variables (populated by setup flow, used for {{vars.key}} references)
                    if (
                        workflowData.variables &&
                        typeof workflowData.variables === 'object'
                    ) {
                        setPersistedVariables(workflowData.variables);
                        // Push into the store record NOW (the React-state →
                        // effect path lags a render) so the baseline below
                        // snapshots complete content.
                        recordGraphSnapshot(
                            workflowId,
                            isSkill,
                            { variables: workflowData.variables },
                            /* markDirty */ false
                        );
                    }

                    // The setNodes/setEdges merges above wrote the proxy
                    // synchronously — snapshot the just-loaded content as the
                    // save baseline so the post-load dirty-marking doesn't
                    // fire a no-op save (DB write + recency churn) per open.
                    seedSaveBaseline(workflowId);

                    // Undo floor = the loaded graph. The hook mounts with an
                    // empty canvas; without this reset that empty state stays
                    // at the bottom of the undo stack and repeated Cmd+Z can
                    // wipe the whole graph (2026-07-30 incident).
                    resetUndoBaseline(mergedNodes, mergedEdges);

                    // Restore display metadata from backend (only if local cache is empty)
                    // This sets displayMetadata.selectedNodeId, which triggers the useEffect
                    // that handles selected node restoration for all cases
                    restoreFromBackend(response.workflow.display_metadata);
                }
            }
        );
        // Cleanup: cancel pending callback if effect re-runs (React Strict Mode double-mount)
        return () => {
            cancelled = true;
            cancelWorkflowGet?.();
        };
    }, [
        workflowId,
        setNodes,
        setEdges,
        restoreFromBackend,
        setInterfaceGridState,
        isSkill,
        resetUndoBaseline,
    ]);

    // ── Execution logs: paginated list + chip totals ──────────────────────
    // Page 1 + counts on tab mount. Filter/search changes re-fetch page 1.
    // Scroll-near-bottom in WorkflowExecutionLogs fires onLoadMore → next page.
    // Live workflow:started / workflow:complete events bump counts (counts is
    // a single index-only-scan; the cost is cheap).
    type ExecCounts = {
        total: number;
        byStatus: Record<'running' | 'waiting' | 'success' | 'error', number>;
        byTrigger: Partial<
            Record<
                'manual' | 'cron' | 'webhook' | 'email' | 'form' | 'run',
                number
            >
        >;
    };
    const EMPTY_COUNTS: ExecCounts = {
        total: 0,
        byStatus: { running: 0, waiting: 0, success: 0, error: 0 },
        byTrigger: {},
    };
    const [logCounts, setLogCounts] = useState<ExecCounts>(EMPTY_COUNTS);
    const [logsHasMore, setLogsHasMore] = useState(false);
    const [logsLoading, setLogsLoading] = useState(false);
    const logsNextCursorRef = useRef<{ started_at: string; id: string } | null>(
        null
    );
    const logsFiltersRef = useRef<{
        status: 'all' | 'running' | 'waiting' | 'success' | 'error';
        trigger:
            | 'all'
            | 'manual'
            | 'cron'
            | 'webhook'
            | 'email'
            | 'form'
            | 'run';
        query: string;
    }>({ status: 'all', trigger: 'all', query: '' });
    // Each fetch gets a token; the latest fetch wins (older late responses are
    // ignored). Prevents a stale page-1 from clobbering a faster filter change.
    const logsFetchTokenRef = useRef(0);

    const mapExecToLog = useCallback((exec: any): WorkflowExecutionLog => {
        const uiStatus: 'running' | 'waiting' | 'success' | 'error' =
            exec.status === 'completed'
                ? 'success'
                : exec.status === 'error'
                  ? 'error'
                  : exec.status === 'awaiting_delay' ||
                      exec.status === 'awaiting_approval'
                    ? 'waiting'
                    : 'running';
        let duration: number | undefined;
        if (exec.finished_at) {
            duration =
                new Date(exec.finished_at).getTime() -
                new Date(exec.started_at).getTime();
        }
        const ts = exec.trigger_source;
        const trigger =
            ts === 'cron' ||
            ts === 'webhook' ||
            ts === 'manual' ||
            ts === 'email'
                ? ts
                : 'manual';
        return {
            id: exec.id,
            timestamp: new Date(exec.started_at),
            status: uiStatus,
            message:
                exec.error ||
                `Workflow ${uiStatus}. Processed ${exec.nodes_executed} nodes.`,
            duration,
            nodesExecuted: exec.nodes_executed,
            trigger,
        };
    }, []);

    // UI status filter → DB status values; UI 'waiting' covers two DB states.
    const uiStatusToDb = useCallback(
        (
            s: 'all' | 'running' | 'waiting' | 'success' | 'error'
        ): string[] | undefined => {
            if (s === 'all') return undefined;
            if (s === 'success') return ['completed'];
            if (s === 'error') return ['error'];
            if (s === 'running') return ['running'];
            return ['awaiting_delay', 'awaiting_approval']; // waiting
        },
        []
    );

    const fetchLogsPage = useCallback(
        async (cursor: { started_at: string; id: string } | null) => {
            if (!isValidWorkflowId) return;
            const token = ++logsFetchTokenRef.current;
            const filters = logsFiltersRef.current;
            setLogsLoading(true);
            try {
                const resp = (await sendEventAsync({
                    event_name: 'workflow:list_executions',
                    workflow_id: workflowId,
                    limit: 50,
                    status: uiStatusToDb(filters.status),
                    trigger_source:
                        filters.trigger === 'all'
                            ? undefined
                            : [filters.trigger],
                    search: filters.query || undefined,
                    cursor_started_at: cursor?.started_at,
                    cursor_id: cursor?.id,
                } as any)) as any;
                if (token !== logsFetchTokenRef.current) return; // stale
                const newLogs: WorkflowExecutionLog[] = (
                    resp?.executions || []
                ).map(mapExecToLog);
                setLogs((prev) => (cursor ? [...prev, ...newLogs] : newLogs));
                logsNextCursorRef.current =
                    resp?.next_cursor_started_at && resp?.next_cursor_id
                        ? {
                              started_at: resp.next_cursor_started_at,
                              id: resp.next_cursor_id,
                          }
                        : null;
                setLogsHasMore(!!logsNextCursorRef.current);
                return newLogs;
            } catch (e) {
                console.error('[FlowCanvas] Failed to load execution logs:', e);
            } finally {
                if (token === logsFetchTokenRef.current) setLogsLoading(false);
            }
        },
        [isValidWorkflowId, workflowId, setLogs, mapExecToLog, uiStatusToDb]
    );

    const fetchLogCounts = useCallback(async () => {
        if (!isValidWorkflowId) return;
        try {
            const resp = (await sendEventAsync({
                event_name: 'workflow:get_execution_counts',
                workflow_id: workflowId,
            } as any)) as any;
            const byStatusRaw = (resp?.by_status || {}) as Record<
                string,
                number
            >;
            const byTriggerRaw = (resp?.by_trigger || {}) as Record<
                string,
                number
            >;
            // Collapse DB statuses → UI buckets.
            const byStatus = {
                success: byStatusRaw['completed'] || 0,
                error: byStatusRaw['error'] || 0,
                running: byStatusRaw['running'] || 0,
                waiting:
                    (byStatusRaw['awaiting_delay'] || 0) +
                    (byStatusRaw['awaiting_approval'] || 0),
            };
            // Map only the triggers the FE renders chips for; 'mcp'/'api' aren't
            // chip-mapped, so their counts are intentionally dropped here.
            const byTrigger: Partial<
                Record<
                    'manual' | 'cron' | 'webhook' | 'email' | 'form' | 'run',
                    number
                >
            > = {
                manual: byTriggerRaw['manual'] || 0,
                cron: byTriggerRaw['cron'] || 0,
                webhook: byTriggerRaw['webhook'] || 0,
                email: byTriggerRaw['email'] || 0,
            };
            setLogCounts({ total: resp?.total || 0, byStatus, byTrigger });
        } catch (e) {
            console.error('[FlowCanvas] Failed to load execution counts:', e);
        }
    }, [isValidWorkflowId, workflowId]);

    // First page + counts on mount (and whenever workflow changes).
    useEffect(() => {
        if (!isValidWorkflowId) return;
        logsNextCursorRef.current = null;
        logsFiltersRef.current = { status: 'all', trigger: 'all', query: '' };
        fetchLogsPage(null);
        fetchLogCounts();
    }, [workflowId, isValidWorkflowId]); // eslint-disable-line react-hooks/exhaustive-deps

    // Filter / search changes from the component re-fetch page 1 with new
    // filters; the in-memory logs are reset (cursor cleared) so the user sees
    // server-truth for the new filter combo.
    const handleLogsFiltersChange = useCallback(
        (filters: {
            status: 'all' | 'running' | 'waiting' | 'success' | 'error';
            trigger:
                | 'all'
                | 'manual'
                | 'cron'
                | 'webhook'
                | 'email'
                | 'form'
                | 'run';
            query: string;
        }) => {
            const prev = logsFiltersRef.current;
            if (
                prev.status === filters.status &&
                prev.trigger === filters.trigger &&
                prev.query === filters.query
            )
                return;
            logsFiltersRef.current = filters;
            logsNextCursorRef.current = null;
            fetchLogsPage(null);
        },
        [fetchLogsPage]
    );

    const handleLogsLoadMore = useCallback(() => {
        if (logsLoading || !logsNextCursorRef.current) return;
        fetchLogsPage(logsNextCursorRef.current);
    }, [logsLoading, fetchLogsPage]);

    // Live execution lifecycle events stale the counts cache. The list itself
    // is updated by useWorkflowExecutionTracking's prepend; counts refresh in
    // the background via a debounce so a burst of completes coalesces to one
    // count fetch.
    // Refetch the resource-tab visibility flag. A run (e.g. an inbound-email
    // trigger storing attachments) can create workflow resources, so this is
    // re-run on workflow:complete, not just on mount.
    const refreshResourceCount = useCallback(() => {
        if (!isValidWorkflowId) return;
        sendEventAsync(
            ResourceListRequest.create({ workflow_id: workflowId!, limit: 1 })
        )
            .then((res) => setResourceCount(res.resources?.length ?? 0))
            .catch(() => {});
    }, [workflowId, isValidWorkflowId]);

    // Post-run results popup correlation (refs declared before the run-lifecycle
    // listeners that use them; openRunResults itself is defined later and called
    // through openRunResultsRef). The popup auto-opens for every real completion —
    // manual, run-from-here, AND server-triggered (webhook/cron) — so the only
    // thing to track is which runs must NOT pop: silent background interface
    // fetches (data.background) and single-node test runs (suppressNextRunPopupRef,
    // set by runSingleNode — their output already shows inline in the config panel).
    const suppressNextRunPopupRef = useRef(false);
    const noResultsPopupExecIdsRef = useRef<Set<string>>(new Set());
    const openRunResultsRef = useRef<((execId: string) => void) | null>(null);

    const countsRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
        null
    );
    const scheduleCountsRefresh = useCallback(() => {
        if (countsRefreshTimerRef.current)
            clearTimeout(countsRefreshTimerRef.current);
        countsRefreshTimerRef.current = setTimeout(() => {
            fetchLogCounts();
        }, 750);
    }, [fetchLogCounts]);
    useSocketEvent(
        'workflow:started',
        useCallback(
            (data: {
                workflow_id?: string;
                execution_id?: string;
                background?: boolean;
            }) => {
                if (data.workflow_id !== workflowId) return;
                scheduleCountsRefresh();
                refreshResourceCount();
                if (!data.execution_id) return;
                // Tag runs that must NOT auto-open the results popup. Background runs return
                // early so they never consume the single-node suppress flag.
                if (data.background) {
                    noResultsPopupExecIdsRef.current.add(data.execution_id);
                    return;
                }
                if (suppressNextRunPopupRef.current) {
                    noResultsPopupExecIdsRef.current.add(data.execution_id);
                    suppressNextRunPopupRef.current = false;
                }
            },
            [workflowId, scheduleCountsRefresh, refreshResourceCount]
        )
    );
    useSocketEvent(
        'workflow:complete',
        useCallback(
            (data: {
                workflow_id?: string;
                execution_id?: string;
                success?: boolean;
                suspended?: boolean;
            }) => {
                if (data.workflow_id !== workflowId) return;
                scheduleCountsRefresh();
                refreshResourceCount();
                // Auto-open the results popup for any real run that actually finished —
                // manual, run-from-here, or server-triggered (webhook/cron) — so the user
                // always sees node outputs. Skip suppressed runs (background fetches /
                // single-node tests) and suspended (paused) runs. A FAILED run while the
                // AI builder is actively editing is also skipped (mid-build configs
                // routinely fail; node error badges still show) — failures with no AI
                // editing pop as usual. Deferred so the final node:output events land in
                // node data. openRunResults (called via ref, defined later) further
                // gates on mobile / replay / the opt-out preference.
                const execId = data.execution_id;
                if (!execId) return;
                const suppressed =
                    noResultsPopupExecIdsRef.current.delete(execId);
                const failedDuringAiEdit =
                    data.success === false && aiEditingRef.current;
                if (!suppressed && !data.suspended && !failedDuringAiEdit) {
                    setTimeout(() => {
                        // The Interface tab presents outcomes in its own idiom —
                        // the agent chat streams the response the user is
                        // already watching — so auto-popping the canvas results
                        // dialog over it is pure noise. Checked at open time
                        // (inside the timeout) so it reflects where the user IS
                        // when the run lands; results stay reachable via the
                        // run-history pill.
                        if (
                            displayMetadataRef.current.activeTab === 'interface'
                        )
                            return;
                        openRunResultsRef.current?.(execId);
                    }, 150);
                }
            },
            [workflowId, scheduleCountsRefresh, refreshResourceCount]
        )
    );

    // ── Execution replay ───────────────────────────────────────────────────
    // Clicking a log row loads that past run's graph snapshot + per-node state
    // from the CAS read API and renders it through the LIVE FlowCanvas itself
    // — the same ReactFlow, the same FlowHelperView, the same shortcuts —
    // with isReplayMode swapping the displayed nodes/edges and gating every
    // mutation entry point. Live nodes/edges state is frozen (never written)
    // while a replay is mounted, so exiting restores the live workflow as-is.
    type ReplayState = {
        log: WorkflowExecutionLog;
        graph: { nodes: any[]; edges: any[] };
        runtimeByNodeId: Record<
            string,
            {
                executionState?: string;
                error?: string;
                output?: any;
                outputTimestamp?: number;
            }
        >;
        toolCalls: ReplayToolCall[];
    };
    const [replay, setReplay] = useState<ReplayState | null>(null);
    const [showReplayToolCalls, setShowReplayToolCalls] = useState(false);
    const isReplayMode = !!replay;

    // Replay-side nodes/edges, kept in their own state so xyflow's selection
    // updates and the runtime-overlay merge don't touch the live canvas state.
    // Populated when `replay` opens, cleared on close.
    const [replayNodes, setReplayNodes] = useState<Node[]>([]);
    const [replayEdges, setReplayEdges] = useState<Edge[]>([]);

    // Initial replay snapshot → xyflow-shaped nodes/edges. Same processing the
    // node components expect from createWorkflowNode (so visuals are identical
    // to the live canvas) plus isReadOnly:true so they hide edit affordances.
    useEffect(() => {
        if (!replay) {
            setReplayNodes([]);
            setReplayEdges([]);
            setSelectedNode(null); // selection was on a replay node — drop it
            return;
        }
        // Clear any live-side selection that lingered from before this replay
        // opened (and any stale selection from a previous replay target) so
        // FlowHelperView doesn't render the wrong node's config. Re-set below
        // if this run has a failed node worth auto-focusing.
        setSelectedNode(null);
        const processed: Node[] = (replay.graph.nodes || []).map((n: any) => {
            const position = n.position || n.data?.position || { x: 0, y: 0 };
            const config = n.data?.config ?? n.config ?? {};
            const nodeType = n.type || 'default';
            const nodeDef = nodeType.startsWith('interface-')
                ? getNodeMetadata(nodeType)
                : null;
            const width =
                n.width ?? n.style?.width ?? nodeDef?.dimensions.width;
            const height =
                n.height ?? n.style?.height ?? nodeDef?.dimensions.height;
            const parsed = createWorkflowNode(
                n.id,
                nodeType,
                position,
                config,
                { isReadOnly: true, ...(replay.runtimeByNodeId?.[n.id] || {}) }
            );
            return {
                ...parsed,
                ...(width ? { width } : {}),
                ...(height ? { height } : {}),
                draggable: false,
                selectable: true,
                ...(width || height
                    ? {
                          style: {
                              ...(width ? { width } : {}),
                              ...(height ? { height } : {}),
                          },
                      }
                    : {}),
            };
        });
        setReplayNodes(processed);
        setReplayEdges(
            (replay.graph.edges || []).map((e: any) => ({
                ...applyEdgeStyle(e),
                animated: false,
                data: { ...(e.data || {}), isReadOnly: true },
            }))
        );

        // If this run errored on a specific node, auto-select that node so the
        // user lands on Config → NodeExecutionErrorBanner immediately. Clicking
        // a failed log row is almost always "what broke?" — making them hunt
        // the red border across the canvas wastes the signal we already have.
        const failedId = Object.entries(replay.runtimeByNodeId || {}).find(
            ([, rt]) =>
                (rt as { executionState?: string })?.executionState === 'error'
        )?.[0];
        const failedNode = failedId
            ? processed.find((n) => n.id === failedId)
            : undefined;
        if (failedNode) {
            setSelectedNode(failedNode);
            setIsConfigViewExpanded(true);
            setFlowHelperActiveTab('config');
        }
    }, [replay?.log.id]); // eslint-disable-line react-hooks/exhaustive-deps -- only re-init when target replay changes; runtime overlay handled by sibling effect

    // Lazy output fetches (handleReplayNodeSelect) refresh replay.runtimeByNodeId;
    // merge those updates into replayNodes WITHOUT re-deriving from scratch so
    // selection / xyflow-internal node state survives.
    useEffect(() => {
        if (!replay?.runtimeByNodeId) return;
        setReplayNodes((nds) =>
            nds.map((n) => {
                const rt = replay.runtimeByNodeId[n.id];
                return rt ? applyNodeUpdate(n, { extras: rt }) : n;
            })
        );
    }, [replay?.runtimeByNodeId]);

    const openExecutionReplay = useCallback(
        async (log: WorkflowExecutionLog) => {
            try {
                const resp: any = await sendEventAsync({
                    event_name: 'workflow:get_execution_detail',
                    workflow_id: workflowId,
                    execution_id: log.id,
                } as any);
                const runtime: Record<string, any> = {};
                for (const r of resp?.node_results || []) {
                    const st = r.last_run_status;
                    runtime[r.node_id] = {
                        executionState:
                            st === 'completed'
                                ? 'completed'
                                : st === 'error'
                                  ? 'error'
                                  : st === 'skipped'
                                    ? 'skipped'
                                    : undefined,
                        // _lastRunStatus drives NodeAuroraLayers' completed ring + ✓ badge
                        // (and the rehydrated failed ring); without it, executed replay
                        // nodes would look identical to never-ran ones in the overlay.
                        _lastRunStatus:
                            st === 'completed' || st === 'error'
                                ? st
                                : undefined,
                        error: r.last_run_error || undefined,
                    };
                }
                setReplay({
                    log,
                    graph: resp?.graph || { nodes: [], edges: [] },
                    runtimeByNodeId: runtime,
                    toolCalls: resp?.tool_calls || [],
                });
                setShowReplayToolCalls(false);
                setActiveTab('canvas');
            } catch (e) {
                console.error(
                    '[FlowCanvas] Failed to open execution replay:',
                    e
                );
            }
        },
        [workflowId, setActiveTab]
    );

    const closeExecutionReplay = useCallback(() => setReplay(null), []);

    // Ref read by the live canvas's document-level keyboard handlers — they
    // bail in replay mode so mutating shortcuts (Escape→shrink helper,
    // W/I/L/S/V/N tab switches + node search, arrow nav, Enter→config,
    // Shift+R→run) don't write to live state while the user is viewing a past
    // run. xyflow's own keyboard behaviors (drag/connect/delete) are already
    // gated via nodesDraggable/nodesConnectable/deleteKeyCode.
    const replayActiveRef = useRef(false);
    useEffect(() => {
        replayActiveRef.current = !!replay;
    }, [replay]);

    // In-flight tracker for replay output fetches. Without this, clicking the
    // same node twice or selecting two nodes that share an upstream would
    // double-fetch (the cached-output check inside setReplay didn't actually
    // short-circuit the network call). Cleared when the replay target changes.
    const replayFetchInFlightRef = useRef<Set<string>>(new Set());
    useEffect(() => {
        replayFetchInFlightRef.current = new Set();
    }, [replay?.log.id]);

    // Lazily fetch a node's output for the active replay. Idempotent: skips if
    // the output is already cached for this node OR a fetch is in flight.
    const handleReplayNodeSelect = useCallback(
        async (nodeId: string | null) => {
            if (!nodeId) return;
            if (replayFetchInFlightRef.current.has(nodeId)) return;
            if (replay?.runtimeByNodeId[nodeId]?.output !== undefined) return;
            replayFetchInFlightRef.current.add(nodeId);
            try {
                const resp: any = await sendEventAsync({
                    event_name: 'workflow:get_node_output',
                    workflow_id: workflowId,
                    execution_id: replay?.log.id,
                    node_id: nodeId,
                } as any);
                setReplay((prev) =>
                    prev
                        ? {
                              ...prev,
                              runtimeByNodeId: {
                                  ...prev.runtimeByNodeId,
                                  [nodeId]: {
                                      ...prev.runtimeByNodeId[nodeId],
                                      output: resp?.output,
                                      outputTimestamp: Date.now(),
                                  },
                              },
                          }
                        : prev
                );
            } catch (e) {
                console.error(
                    '[FlowCanvas] Failed to fetch replay node output:',
                    e
                );
            } finally {
                replayFetchInFlightRef.current.delete(nodeId);
            }
        },
        [workflowId, replay]
    );

    // When the user selects a replay node, fetch its output AND the outputs of
    // its direct upstream nodes. The Input panel in FlowHelperView reads each
    // upstream node's data.output to render the inputs the selected node ran
    // on; without upstream prefetch the panel would be empty until each input
    // node was also clicked individually. Fetches run in parallel and the
    // in-flight tracker dedupes across overlapping selections.
    useEffect(() => {
        if (!isReplayMode || !selectedNode?.id) return;
        handleReplayNodeSelect(selectedNode.id);
        const upstreamIds = (replay?.graph.edges || [])
            .filter((e: any) => e?.target === selectedNode.id)
            .map((e: any) => e?.source as string | undefined)
            .filter(
                (id): id is string => typeof id === 'string' && id.length > 0
            );
        for (const id of upstreamIds) handleReplayNodeSelect(id);
    }, [
        isReplayMode,
        selectedNode?.id,
        handleReplayNodeSelect,
        replay?.graph.edges,
    ]);

    // Check if workflow has any resources (for conditional tab display)
    useEffect(() => {
        refreshResourceCount();
    }, [refreshResourceCount]);

    // Tell liveGraphStore the canvas is mounted for this workflow.
    // After Phase 2 the store is the source of truth for nodes/edges,
    // so unmount no longer needs to push a snapshot — all setNodes
    // writes have already landed in the proxy. We still capture sidecar
    // refs (interface grid, variables, displayMetadata) which the
    // canvas updates via separate paths, then flush before marking
    // unmounted.
    //
    // Order matters: canSave gates on canvasMounted=true, so flush
    // before flipping the flag.
    useEffect(() => {
        if (!isValidWorkflowId) return;
        setCanvasMounted(workflowId, isSkill, true);
        return () => {
            recordGraphSnapshot(
                workflowId,
                isSkill,
                {
                    interfaceGridState: interfaceGridStateRef.current ?? null,
                    variables: workflowVariablesRef.current,
                    displayMetadata: displayMetadataRef.current,
                },
                /* markDirty */ false
            );
            const deletedNodeIds = Array.from(deletedNodeIdsRef.current);
            if (deletedNodeIds.length > 0) {
                deletedNodeIdsRef.current.clear();
                recordDeletedNodes(workflowId, deletedNodeIds);
            }
            flushGraphNow(workflowId);
            setCanvasMounted(workflowId, isSkill, false);
        };
    }, [workflowId, isSkill, isValidWorkflowId]);

    // Phase 2: nodes/edges live in liveGraphStore directly (via
    // useLiveGraph), so this effect no longer needs to push them. It
    // still serves two purposes:
    //   • Push sidecar fields (interface grid, variables, display
    //     metadata) into the store so workflow:update payloads include
    //     them on flush.
    //   • Detect graph changes (via the nodes/edges deps) and trigger
    //     the store's debounced save scheduler — direct writes to the
    //     proxy don't auto-schedule.
    //
    // markGraphDirty just sets dirty=true + schedules the save; passing
    // markDirty=false on the snapshot avoids re-writing nodes/edges
    // (which would feedback through useSnapshot and loop).
    //
    // The first run per (mount, workflowId) is the mount itself, not a
    // change — marking dirty there fired a full no-op save 2s after every
    // open, bumping updated_at (recency reorder) and widening the clobber
    // window. Skip it; genuinely stranded dirty state is picked up by
    // setCanvasMounted(true)'s dirty check in the store.
    const graphChangeBaselineRef = useRef<string | null>(null);
    useEffect(() => {
        if (!isValidWorkflowId) return;
        recordGraphSnapshot(
            workflowId,
            isSkill,
            {
                // Intentionally omit nodes/edges — store already owns them.
                interfaceGridState: interfaceGridStateRef.current ?? null,
                variables: workflowVariablesRef.current,
                displayMetadata: displayMetadataRef.current,
            },
            /* markDirty */ false
        );
        if (graphChangeBaselineRef.current === workflowId) {
            markGraphDirty(workflowId);
        } else {
            graphChangeBaselineRef.current = workflowId;
        }
        const deletedNodeIds = Array.from(deletedNodeIdsRef.current);
        if (deletedNodeIds.length > 0) {
            deletedNodeIdsRef.current.clear();
            recordDeletedNodes(workflowId, deletedNodeIds);
        }
    }, [
        nodes,
        edges,
        debouncedInterfaceVersion,
        workflowId,
        isSkill,
        isValidWorkflowId,
    ]);

    // Alias for the shared pan hook, used by the pending-node-selection effect.
    const panToNodeCallback = panToNode;

    // Navigate to a specific node - selects it, opens config (if not collapsed), and pans to it
    // Uses nodesRef.current to avoid recreating callback on every node position change
    const navigateToErroredNode = useCallback(
        (nodeId: string) => {
            // Find the node to navigate to using ref
            const targetNode = nodesRef.current.find((n) => n.id === nodeId);
            if (!targetNode) return;

            // Select the node
            setSelectedNode(targetNode);

            // Update selected state in ReactFlow for visual highlight
            setNodes((current) =>
                current.map((n) => ({
                    ...n,
                    selected: n.id === nodeId,
                }))
            );

            // Open FlowHelperView and switch to config tab
            // But preserve collapsed state (null) if user manually collapsed the tabs
            setIsConfigViewExpanded(true);
            const currentTab =
                displayMetadataRef.current.flowHelperView.activeTab;
            if (currentTab !== null) {
                setFlowHelperActiveTab('config');
            }

            // Pan to the node using the shared hook
            panToNode(nodeId);
        },
        [
            setNodes,
            setSelectedNode,
            setIsConfigViewExpanded,
            setFlowHelperActiveTab,
            panToNode,
        ]
    );

    // Make the flow canvas a droppable area
    const { setNodeRef } = useDroppable({
        id: 'flow-canvas',
    });

    // Function to handle workflow import from JSON file
    const handleImportWorkflow = useCallback(() => {
        fileInputRef.current?.click();
    }, []);

    // Handle a user-picked workflow file: parse → reposition at viewport centre →
    // merge into state → capture for undo → auto-select credentials for new nodes.
    const handleFileChange = useCallback(
        async (event: React.ChangeEvent<HTMLInputElement>) => {
            const file = event.target.files?.[0];
            if (!file) return;
            // Reset so the same file can be re-imported later
            event.target.value = '';

            try {
                const result = await readWorkflowFile(file);
                if (!result) {
                    alert(
                        'Unsupported workflow format. Please use a valid NoClick workflow JSON file.'
                    );
                    return;
                }

                const { offsetX, offsetY } = computeImportOffset(
                    result.nodes,
                    getViewport()
                );
                const repositionedNodes = repositionImportedNodes(
                    result.nodes,
                    offsetX,
                    offsetY
                );

                let newNodes: Node[] = [];
                let newEdges: Edge[] = [];
                setNodes((existingNodes) => {
                    newNodes = [...existingNodes, ...repositionedNodes];
                    return newNodes;
                });
                setEdges((existingEdges) => {
                    newEdges = [...existingEdges, ...result.edges];
                    return newEdges;
                });

                setTimeout(() => captureState(newNodes, newEdges), 0);

                // Auto-select credentials for imported nodes (the helper authorizes
                // any that already carry credentialIds and auto-selects the rest).
                repositionedNodes.forEach((node) =>
                    autoSelectCredentialsForNewNode(node, setNodes, workflowId)
                );
            } catch (error) {
                console.error('[Import] Error importing workflow file:', error);
                alert(
                    'Error importing workflow. Please check that the file is valid JSON.'
                );
            }
        },
        [setNodes, setEdges, captureState, getViewport, workflowId]
    );

    // Export the current canvas state as a downloadable JSON file.
    const handleExportWorkflow = useCallback(() => {
        try {
            const currentNodes = nodes;
            const currentEdges = edges;
            exportWorkflowToFile(
                currentNodes,
                currentEdges,
                workflowTitle || 'workflow'
            );
        } catch (error) {
            console.error('[Export] Error exporting workflow:', error);
            alert('Error exporting workflow. Please try again.');
        }
    }, [nodes, edges, workflowTitle]);

    // Auto-layout all nodes using Sugiyama-style layered graph drawing, then
    // pan/zoom to frame the whole workflow. The fit waits a frame so ReactFlow
    // has consumed the new node positions before computing the bounding box.
    const handleAutolayout = useCallback(() => {
        const currentNodes = nodesRef.current;
        const currentEdges = edgesRef.current;
        if (currentNodes.length === 0) return;

        const layoutedNodes = autolayout(currentNodes, currentEdges);

        // Did the layout actually move anything? autolayout preserves order, so
        // compare each node against its computed position (sub-pixel epsilon).
        // If nothing moved, the graph is already laid out — skip the spurious
        // save/broadcast and let the user know.
        const moved = layoutedNodes.some((node, i) => {
            const prev = currentNodes[i];
            return (
                Math.abs(node.position.x - prev.position.x) > 0.5 ||
                Math.abs(node.position.y - prev.position.y) > 0.5
            );
        });

        if (moved) {
            startBatch();
            setNodes(layoutedNodes);
            endBatch(layoutedNodes, currentEdges);
        } else {
            toast.info('Already laid out', {
                description: 'Your workflow is already neatly arranged.',
                duration: 3000,
            });
        }

        // Always reframe — the button's other job is to bring the whole
        // workflow into view, even when the layout itself didn't change.
        requestAnimationFrame(() => {
            try {
                fitView({ duration: 500, padding: 0.22, maxZoom: 1.0 });
            } catch {}
            // Mirror on ForkCanvas (no-op when it's not mounted / ?canvas=fork).
            try {
                forkCanvasRef.current?.fitView({ padding: 0.22, maxZoom: 1.0 });
            } catch {}
        });
    }, [setNodes, startBatch, endBatch, fitView]);

    const handleDeleteWorkflow = useCallback(() => {
        if (!workflowId) return;
        onDelete?.(workflowId);
    }, [workflowId, onDelete]);

    // Function to run workflow via backend
    // Uses refs to avoid recreating callback on every node position change
    // Clear stale run-state on the nodes a fresh run is about to (re-)execute, so a
    // downstream node doesn't keep showing a previous run's completed/failed badge +
    // output while it's queued to run again. `targetIds === null` resets every node
    // (full-workflow run). These are all transient/runtime fields (persist:false) so
    // this is a local visual reset — not broadcast to collaborators, not saved.
    const resetNodesRunState = useCallback(
        (targetIds: Set<string> | null) => {
            setNodes((nodes) =>
                nodes.map((n) =>
                    targetIds === null || targetIds.has(n.id)
                        ? applyNodeUpdate(n, {
                              extras: {
                                  executionState: 'idle',
                                  output: undefined,
                                  outputTimestamp: undefined,
                                  progress: undefined,
                                  error: undefined,
                                  ...Object.fromEntries(
                                      RUN_STATUS_FIELDS.map((f) => [
                                          f,
                                          undefined,
                                      ])
                                  ),
                              },
                          })
                        : n
                )
            );
        },
        [setNodes]
    );

    const runWorkflow = useCallback(
        (selection?: RunSelection) => {
            if (!workflowId) {
                console.warn('[FlowCanvas] Cannot run workflow: no workflowId');
                return;
            }

            // Whole workflow re-runs → clear every node's prior run-state. Completion
            // auto-opens the results popup (opt-out model — see the workflow:complete
            // listener); no per-run opt-in needed here.
            resetNodesRunState(null);

            const currentNodes = nodesRef.current;
            const currentEdges = edgesRef.current;

            logActivity(EVENTS.WORKFLOW_RUN_CLICKED, {
                workflow_id: workflowId,
                node_count: currentNodes.length,
                edge_count: currentEdges.length,
            });
            // Honeycomb counterpart of WORKFLOW_RUN_CLICKED. Same trigger,
            // engineering-side view — pairs with workflow.run_acked and
            // workflow.run_completed below for conversion + latency funnels.
            track('workflow.run_started', {
                workflow_id: workflowId,
                node_count: currentNodes.length,
                edge_count: currentEdges.length,
            });

            // Optimistic: add a temporary execution so the button switches to Stop immediately.
            // The real execution_id arrives via workflow:started and replaces this entry.
            addPendingExecution();

            const runId = `run-${Date.now()}`;

            // Add initial running log
            const runningLog: WorkflowExecutionLog = {
                id: runId,
                timestamp: new Date(),
                status: 'running',
                message: `Executing workflow with ${currentNodes.length} nodes...`,
            };

            setLogs((prev) => [runningLog, ...prev]);

            // Send workflow execution request to backend. When the user picked a
            // subset of entry points, the executed graph is narrowed to those
            // branches while replay stays whole — same split "run from here" uses,
            // so the backend can still resolve references against the full graph.
            const graph = serializeGraphForExecution(
                currentNodes,
                currentEdges
            );
            const scope = selection?.pathIds
                ? runScopeForRoots(
                      currentEdges,
                      selection.pathIds,
                      currentNodes
                  )
                : null;
            const executed = scope
                ? {
                      nodes: graph.nodes.filter((n) =>
                          scope.has(n.id as string)
                      ),
                      edges: graph.edges.filter(
                          (e) =>
                              scope.has(e.source as string) &&
                              scope.has(e.target as string)
                      ),
                  }
                : graph;
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    nodes: executed.nodes,
                    edges: executed.edges,
                    replay_nodes: graph.nodes,
                    replay_edges: graph.edges,
                    ...(selection?.configOverrides
                        ? { config_overrides: selection.configOverrides }
                        : {}),
                })
            );
        },
        [workflowId, workflowSettings, logActivity, resetNodesRunState]
    );

    // Trigger explainer popup. Holds the triggers to describe; open flag is
    // separate so the data stays available while the dialog is mounted.
    const [triggerRunPrompt, setTriggerRunPrompt] = useState<WorkflowTrigger[]>(
        []
    );
    const [triggerDialogOpen, setTriggerDialogOpen] = useState(false);

    // Unconfigured-steps popup. Only the step IDS are frozen at Run press —
    // their state is re-derived from the live graph on every edit, so a field
    // filled in the popup immediately marks its step ready. Keeping the id list
    // fixed is what stops a resolved row from vanishing under the pointer.
    const [incompleteStepIds, setIncompleteStepIds] = useState<string[]>([]);
    const [incompleteFieldKeys, setIncompleteFieldKeys] = useState<
        Record<string, string[]>
    >({});
    const [incompleteDialogOpen, setIncompleteDialogOpen] = useState(false);
    // Entry-point selection for the run being configured. Frozen at press like
    // the step list — the graph can change under an open popup.
    const [runPaths, setRunPaths] = useState<RunPath[]>([]);
    const [selectedPathIds, setSelectedPathIds] = useState<Set<string>>(
        new Set()
    );
    // One-shot opening messages, keyed by agent node id. Deliberately NOT
    // written to the node: editing one here is "do this now", not "change what
    // this agent does" (matching how interface chat overrides config.message).
    const [pathMessages, setPathMessages] = useState<Record<string, string>>(
        {}
    );
    // Whether the popup is choosing between the graph's entry points or just
    // collecting the opening message for the node a scoped run starts at.
    const [runPathsScope, setRunPathsScope] = useState<'workflow' | 'node'>(
        'workflow'
    );
    // What "Run anyway" does. Every run entry point routes through the same
    // gate, so the popup has to remember which run it interrupted — the whole
    // workflow, one node, or from a node down.
    const incompletePendingRunRef = useRef<
        | ((configOverrides?: Record<string, Record<string, unknown>>) => void)
        | null
    >(null);
    // Disarms the gate for the duration of ONE synchronous run call. "Run
    // anyway" re-invokes the very call the gate intercepted, and the steps are
    // still incomplete, so without this the gate would catch it again and the
    // popup would never let go. Always go through runWithoutGate — see there.
    const bypassRunGateRef = useRef(false);

    /**
     * Start `proceed` with the gate disarmed, and re-arm it no matter what.
     *
     * The re-arm is the point. Only some run entry points re-enter the gate
     * (run-from-here and single-node do; a whole-workflow run calls runWorkflow
     * directly), so a flag left for "the next gated run to consume" survived
     * the presses that never consult it — and silently disarmed the gate for
     * the user's NEXT press, which then ran with no popup at all. Scoping it to
     * one synchronous call makes that unrepresentable.
     */
    const runWithoutGate = useCallback((proceed: () => void) => {
        bypassRunGateRef.current = true;
        try {
            proceed();
        } finally {
            bypassRunGateRef.current = false;
        }
    }, []);

    /**
     * Raise the unconfigured-steps popup for `candidates`, or run.
     *
     * Shared by all three entry points (Run, a node's own run, run-from-here)
     * so none of them can start a run that stops at a hole the others would
     * have caught. Returns true when it took over.
     */
    const gateRunOnIncompleteSteps = useCallback(
        (
            candidates: Node[],
            proceed: (
                configOverrides?: Record<string, Record<string, unknown>>
            ) => void,
            /** Where this run begins. A whole-workflow run has every graph
             *  entry point to offer; a node-scoped one has exactly the node it
             *  starts from — which still matters, because if that node is an
             *  agent it needs its opening message either way. */
            entry: { wholeWorkflow?: boolean; startNodeId?: string } = {}
        ): boolean => {
            // Mobile has no room for the popup / config — just run.
            if (isMobileRef.current) return false;
            if (bypassRunGateRef.current) {
                bypassRunGateRef.current = false;
                return false;
            }
            const incomplete = getIncompleteRunPrompt(
                candidates,
                validationContext
            );
            // A whole-workflow run offers every entry point in the graph; a
            // node-scoped run has exactly one — the node it starts from. That
            // is not a choice, but it is still where an agent's opening
            // message belongs, which is why it is described at all.
            const startNode = entry.startNodeId
                ? nodesRef.current.find((n) => n.id === entry.startNodeId)
                : undefined;
            const paths = entry.wholeWorkflow
                ? getRunStartPaths(nodesRef.current, edgesRef.current)
                : startNode
                  ? [
                        describeRunPath(
                            startNode,
                            [],
                            // Its tools, so the message screen can name them.
                            // Downstream stays empty: a node-scoped run's
                            // reach is the caller's business, not a summary
                            // this screen should second-guess.
                            toolProviderTitles(
                                startNode.id,
                                nodesRef.current,
                                edgesRef.current
                            )
                        ),
                    ]
                  : [];
            // Worth opening for a choice or an agent's opening message, not
            // just for something broken. A single non-agent entry point is
            // neither, so a simple workflow still runs straight off the button.
            const worthChoosing =
                paths.length > 1 || paths.some((p) => p.isAgent);
            if (!incomplete && !worthChoosing) return false;
            setRunPaths(paths);
            setSelectedPathIds(new Set(paths.map((p) => p.nodeId)));
            setPathMessages(
                Object.fromEntries(
                    paths
                        .filter((p) => p.isAgent)
                        .map((p) => [p.nodeId, p.message])
                )
            );
            track('workflow.incomplete_run_prompt_shown', {
                workflow_id: workflowId,
                step_count: incomplete?.length ?? 0,
                path_count: paths.length,
            });
            setIncompleteStepIds((incomplete ?? []).map((s) => s.nodeId));
            setIncompleteFieldKeys(
                Object.fromEntries(
                    (incomplete ?? []).map((s) => [
                        s.nodeId,
                        [
                            ...s.fields.map((f) => f.key),
                            // The operation picker is sticky on the same terms
                            // as the editors: one selection satisfies the
                            // requirement, and a picker that vanishes on it
                            // cannot be used to allowlist a second action.
                            ...(s.needsToolActions
                                ? [TOOL_OPERATIONS_KEY]
                                : []),
                            ...(s.needsOperation ? [OPERATION_KEY] : []),
                            ...(s.needsCredentials ? [CREDENTIALS_KEY] : []),
                        ],
                    ])
                )
            );
            incompletePendingRunRef.current = proceed;
            setRunPathsScope(entry.wholeWorkflow ? 'workflow' : 'node');
            setIncompleteDialogOpen(true);
            return true;
        },
        [validationContext, workflowId]
    );

    /** The canvas nodes a prepared execution graph will actually run. */
    const nodesForExecutionIds = useCallback(
        (ids: Iterable<string>): Node[] => {
            const wanted = new Set(ids);
            return nodesRef.current.filter((n) => wanted.has(n.id));
        },
        []
    );

    const handleToggleRunPath = useCallback((nodeId: string) => {
        setSelectedPathIds((prev) => {
            const next = new Set(prev);
            if (!next.delete(nodeId)) next.add(nodeId);
            return next;
        });
    }, []);

    const handleToggleAllRunPaths = useCallback(() => {
        setSelectedPathIds((prev) =>
            prev.size > 0 ? new Set() : new Set(runPaths.map((p) => p.nodeId))
        );
    }, [runPaths]);

    const handleRunPathMessageChange = useCallback(
        (nodeId: string, message: string) => {
            setPathMessages((prev) => ({ ...prev, [nodeId]: message }));
        },
        []
    );

    /**
     * The typed opening messages, as a per-node config override.
     *
     * A one-shot instruction for this run, not a rewrite of the node — the same
     * split the Interface chat makes between the agent's standing brief and the
     * user's line. Message and thread only: unlike a chat send nothing here
     * picks a model, and writing an empty one would override the node's.
     */
    const agentMessageOverrides = useCallback(
        (paths: RunPath[]): Record<string, Record<string, unknown>> => {
            const overrides: Record<string, Record<string, unknown>> = {};
            for (const path of paths) {
                if (!path.isAgent) continue;
                const config = (nodesRef.current.find(
                    (n) => n.id === path.nodeId
                )?.data?.config ?? {}) as Record<string, unknown>;
                const ck =
                    typeof config.conversation_key === 'string' &&
                    config.conversation_key.trim();
                overrides[path.nodeId] = {
                    message: pathMessages[path.nodeId] ?? '',
                    conversation_key: ck || DEFAULT_INTERFACE_CONV_KEY,
                };
            }
            return overrides;
        },
        [pathMessages]
    );

    /**
     * Run only the entry points the user ticked in the popup.
     *
     * A lone agent is delivered THROUGH ITS CHAT rather than as a workflow run:
     * we are about to put the user in front of that chat, and a raw
     * workflow:execute leaves no trace there — the backend does not replay
     * chat:message to its sender, so the message the user just typed simply did
     * not appear. Handing it to the block's own submit echoes the bubble and
     * lights the streaming state, and picks up its model resolution and
     * credential pre-flight for free.
     *
     * Every other shape stays a workflow run, where an agent's opening message
     * rides `config_overrides` — a one-shot instruction, the same split the
     * chat uses between the agent's standing brief and the user's line.
     */
    const startSelectedRunPaths = useCallback(() => {
        const chosen = runPaths.filter((p) => selectedPathIds.has(p.nodeId));
        if (chosen.length === 0) return;

        // Only when the agent IS the run. With other branches ticked too, the
        // user stays on the canvas where those outputs land, so there is no
        // chat to deliver into.
        if (chosen.length === 1 && chosen[0].isAgent) {
            const agentId = chosen[0].nodeId;
            queueAgentChatSend(
                workflowId,
                agentId,
                pathMessages[agentId] ?? ''
            );
            // The block has to exist before it can drain the message.
            setNodes((ns) =>
                updateNodeInList(ns, agentId, {
                    config: { show_in_interface: 'true' },
                })
            );
            document.dispatchEvent(
                new CustomEvent('noclick:open-agent-chat', {
                    detail: { nodeId: agentId },
                })
            );
            return;
        }

        const configOverrides = agentMessageOverrides(chosen);

        runWorkflow({
            pathIds: chosen.map((p) => p.nodeId),
            ...(Object.keys(configOverrides).length ? { configOverrides } : {}),
        });
    }, [
        runPaths,
        selectedPathIds,
        pathMessages,
        agentMessageOverrides,
        runWorkflow,
        setNodes,
        workflowId,
    ]);

    // User-facing Run entry point, guarding two ways a plain run would confuse:
    // steps that are not configured yet (the run would stop at the first hole
    // with a runtime error), and a workflow that only starts on automatic
    // triggers (webhook, inbound email, schedule, "new row on Sheets", …) with
    // no manual Run trigger. Both popups are soft gates with a "Run anyway".
    const requestRunWorkflow = useCallback(() => {
        // Mobile has no room for the explainer popup / config — just run.
        if (isMobileRef.current) {
            runWorkflow();
            return;
        }
        const triggers = getTriggerRunPrompt(nodesRef.current);
        // Missing configuration first: it is the blocker the user can act on,
        // and it outranks explaining how the workflow starts. One popup per
        // press — "Run anyway" here runs, it does not fall through to the
        // trigger explainer. Entry points are only offered when there is no
        // trigger explainer to give: "pick what to run" would otherwise
        // silently replace the answer to "how does this even start?".
        if (
            gateRunOnIncompleteSteps(
                nodesRef.current,
                // Adapt signatures: proceed hands per-node config overrides,
                // runWorkflow takes a RunSelection. Passing runWorkflow raw
                // only worked while this path never sent overrides — and would
                // silently drop them the day it does.
                (configOverrides) =>
                    runWorkflow(
                        configOverrides ? { configOverrides } : undefined
                    ),
                { wholeWorkflow: !triggers }
            )
        )
            return;
        if (triggers) {
            track('workflow.trigger_info_shown', {
                workflow_id: workflowId,
                trigger_count: triggers.length,
            });
            setTriggerRunPrompt(triggers);
            setTriggerDialogOpen(true);
            return;
        }
        runWorkflow();
    }, [runWorkflow, workflowId, gateRunOnIncompleteSteps]);

    // "Add a Run step" from the trigger-info popup: drop an unconnected manual
    // Run trigger near the existing triggers and pan to it — the user wires it up.
    const handleAddManualRun = useCallback(() => {
        const triggerNodeIds = new Set(triggerRunPrompt.map((t) => t.nodeId));
        const trigNodes = nodesRef.current.filter((n) =>
            triggerNodeIds.has(n.id)
        );
        const minX = trigNodes.length
            ? Math.min(...trigNodes.map((n) => n.position.x))
            : 100;
        const minY = trigNodes.length
            ? Math.min(...trigNodes.map((n) => n.position.y))
            : 100;

        const runId = generateNodeId('trigger-run');
        const runNode = createWorkflowNode(
            runId,
            'trigger-run',
            { x: minX, y: minY - 180 },
            {}
        );
        setNodes((prev) => [...prev, runNode]);
        broadcastNodeAddRef.current?.(runNode);

        setTriggerDialogOpen(false);
        logActivity(EVENTS.NODE_ADDED, {
            node_id: runId,
            node_type: 'trigger-run',
            workflow_id: workflowId,
            source: 'trigger_info_popup',
        });

        // Pan to the new node with the shared hook — it retries until the node is
        // measured and frames it in the visible canvas (offsetting the
        // FlowHelperView panel). Mirror the select-node path's mobile fallback.
        panToNode(runId);
        setTimeout(() => {
            try {
                forkCanvasRef.current?.fitView({
                    nodes: [{ id: runId }],
                    padding: 0.4,
                    maxZoom: 1.5,
                    duration: 400,
                });
            } catch {
                /* fork canvas not mounted */
            }
            captureState(nodesRef.current, edgesRef.current);
        }, 150);
    }, [
        triggerRunPrompt,
        setNodes,
        panToNode,
        captureState,
        workflowId,
        logActivity,
    ]);

    // Open a trigger's config from the popup: open the FlowHelperView config tab
    // expanded to the autosnap limit (~70vh, just under the fullscreen snap), then
    // select + pan to the node. Two-step on purpose: the expand must render FIRST
    // so panToNode (re-bound via the select-node listener) frames the node in the
    // small strip ABOVE the expanded panel, not in the whole canvas.
    const openNodeConfigExpanded = useCallback(
        (nodeId: string, tab: 'config' | 'credentials' = 'config') => {
            if (!nodesRef.current.some((n) => n.id === nodeId)) return;
            // Instant-height flags match Enter-to-edit so the open animation doesn't
            // override the explicit height.
            setFlowHelperNoAnim(true);
            setFlowHelperInstantHeight(true);
            setFlowHelperActiveTab(tab);
            setIsConfigViewExpanded(true);
            const target = Math.round(window.innerHeight * 0.7);
            setFlowHelperHeight(target);
            setAutoFocusPickerOnOpen(false);
            // Display-metadata state is async, so wait until the expanded height has
            // actually propagated (the ref is updated from the same render whose
            // effects also re-bind panToNode to the new panel height) before selecting
            // + panning via the select-node path. Otherwise panToNode frames the node
            // in the whole canvas and it lands hidden behind the expanded panel.
            const start = performance.now();
            const dispatchWhenExpanded = () => {
                const ready =
                    isConfigViewExpandedRef.current &&
                    flowHelperHeightRef.current >= target - 10;
                if (ready || performance.now() - start > 1200) {
                    document.dispatchEvent(
                        new CustomEvent('noclick:workflow:select-node', {
                            detail: { workflowId, nodeId, tab },
                        })
                    );
                } else {
                    setTimeout(dispatchWhenExpanded, 40);
                }
            };
            setTimeout(dispatchWhenExpanded, 40);
        },
        [
            setFlowHelperNoAnim,
            setFlowHelperInstantHeight,
            setFlowHelperActiveTab,
            setIsConfigViewExpanded,
            setFlowHelperHeight,
            setAutoFocusPickerOnOpen,
            workflowId,
        ]
    );

    const handleOpenTriggerConfig = useCallback(
        (nodeId: string) => {
            setTriggerDialogOpen(false);
            openNodeConfigExpanded(nodeId);
        },
        [openNodeConfigExpanded]
    );

    // Jump from the unconfigured-steps popup into the step's config. The panel's
    // amber banner pulses itself on arrival, so what is missing is visible the
    // moment the popup closes.
    // Straight to the Credentials tab, through the same expand-then-pan path as
    // the config hand-off (and Enter-to-edit): the node stays visible in the
    // strip above the panel, which full screen took away.
    //
    // The pulse is requested here rather than decided over in the tab, so it
    // marks THIS hand-off and not every visit to a node that happens to need an
    // account. The request survives the panel not having rendered yet.
    const handleOpenIncompleteCredentials = useCallback(
        (nodeId: string) => {
            setIncompleteDialogOpen(false);
            requestPulse(credentialsPulseKey(nodeId));
            openNodeConfigExpanded(nodeId, 'credentials');
        },
        [openNodeConfigExpanded]
    );

    // Same hand-off from the execution-error banner's "Open credentials"
    // button, so a provider auth failure lands where the fix is instead of
    // leaving the user to find the credential themselves.
    useEffect(() => {
        const onOpenCredentials = (event: Event) => {
            const nodeId = (event as CustomEvent<{ nodeId?: string }>).detail
                ?.nodeId;
            if (!nodeId) return;
            // The button can be inside the run-results popup, which would
            // otherwise stay up covering the panel it just sent the user to.
            setRunResultsOpen(false);
            handleOpenIncompleteCredentials(nodeId);
        };
        document.addEventListener(
            'noclick:node:open-credentials',
            onOpenCredentials
        );
        return () =>
            document.removeEventListener(
                'noclick:node:open-credentials',
                onOpenCredentials
            );
    }, [handleOpenIncompleteCredentials]);

    const handleOpenIncompleteConfig = useCallback(
        (nodeId: string) => {
            setIncompleteDialogOpen(false);
            openNodeConfigExpanded(nodeId);
        },
        [openNodeConfigExpanded]
    );

    // Live state of the popup's steps. Recomputed from `nodes` so an inline edit
    // re-validates that step on the next render; skipped entirely while closed.
    const incompleteSteps = useMemo(
        () =>
            incompleteDialogOpen
                ? describeStepsForIds(
                      nodes,
                      incompleteStepIds,
                      validationContext,
                      incompleteFieldKeys
                  )
                : [],
        [
            incompleteDialogOpen,
            incompleteStepIds,
            incompleteFieldKeys,
            nodes,
            validationContext,
        ]
    );

    // Edits from the popup take the same path as the config panel's — normalized,
    // undo-captured, broadcast to collaborators, and picked up by the autosave.
    const handleIncompleteFieldChange = useCallback(
        (nodeId: string, fieldKey: string, value: unknown) => {
            const node = nodesRef.current.find((n) => n.id === nodeId);
            if (!node) return;
            const config = (node.data?.config ?? {}) as Record<string, unknown>;
            handleNodeDataUpdateRef.current(nodeId, {
                config: { ...config, [fieldKey]: value },
            });
        },
        []
    );

    // Credential picks from the popup's inline block take the same path as the
    // config panel's — including the run-as-owner authorization, which a plain
    // credentialIds write would silently omit.
    const handleIncompleteCredentialsChange = useCallback(
        (
            nodeId: string,
            credentialIds: Record<string, string>,
            credentialMeta?: Record<string, CredentialDisplayMeta>,
            credentialRemoved?: string[]
        ) => {
            applyCredentialSelection(
                nodeId,
                workflowId,
                credentialIds,
                handleNodeDataUpdateRef.current,
                credentialMeta,
                credentialRemoved
            );
        },
        [workflowId]
    );

    // The action lives top-level on node data, not in config, so it takes the
    // metadata path rather than handleIncompleteFieldChange.
    const handleIncompleteOperationChange = useCallback(
        (nodeId: string, operation: string) => {
            handleNodeDataUpdateRef.current(nodeId, { operation });
        },
        []
    );

    const incompleteStepValues = useCallback(
        (nodeId: string) =>
            (nodesRef.current.find((n) => n.id === nodeId)?.data?.config ??
                {}) as Record<string, unknown>,
        []
    );

    const incompleteStepCredentials = useCallback(
        (nodeId: string) =>
            (nodesRef.current.find((n) => n.id === nodeId)?.data
                ?.credentialIds ?? {}) as Record<string, string>,
        []
    );

    // ── Post-run results popup ──────────────────────────────────────────────
    // When a manual run finishes, show each node's output (the agent first, with
    // its tool calls). Correlated to the run the user started: runWorkflow flags
    // the active run, workflow:started records its execution_id, and
    // workflow:complete builds and opens the results for that id (refs above).
    const [runResults, setRunResults] = useState<NodeRunResult[]>([]);
    const [runResultsOpen, setRunResultsOpen] = useState(false);
    // Which execution the results popup is showing (drives the in-popup run
    // switcher) + whether a switched run's results are still loading.
    const [runResultsExecId, setRunResultsExecId] = useState<string | null>(
        null
    );
    const [runResultsLoading, setRunResultsLoading] = useState(false);
    const [resultsPopupDisabled, markResultsPopupDisabled] = useSeenOnce(
        'run_results_popup_disabled'
    );
    const resultsPopupDisabledRef = useRef(resultsPopupDisabled);
    useEffect(() => {
        resultsPopupDisabledRef.current = resultsPopupDisabled;
    }, [resultsPopupDisabled]);

    const handleOpenResultsConfig = useCallback(
        (nodeId: string) => {
            setRunResultsOpen(false);
            openNodeConfigExpanded(nodeId);
        },
        [openNodeConfigExpanded]
    );

    const openRunResults = useCallback(
        async (execId: string) => {
            if (isMobileRef.current) return; // no room to view outputs/configs on mobile
            if (replayActiveRef.current) return; // don't yank a popup over an open replay
            // executionState is transient (reset to 'idle' once the run settles), so
            // scope to nodes that ran in THIS execution and read the durable
            // _lastRunStatus / output instead.
            const ran = nodesRef.current.filter((n) => {
                const d = n.data || {};
                if (d._executionId !== execId) return false;
                return (
                    d._lastRunStatus === 'completed' ||
                    d._lastRunStatus === 'error' ||
                    (d.output !== undefined && d.output !== null)
                );
            });
            if (ran.length === 0) return;

            // Tool calls aren't in the node output — pull them from the execution detail.
            const toolCallsByAgent: Record<string, ReplayToolCall[]> = {};
            try {
                const resp: any = await sendEventAsync({
                    event_name: 'workflow:get_execution_detail',
                    workflow_id: workflowId,
                    execution_id: execId,
                } as any);
                for (const tc of (resp?.tool_calls || []) as ReplayToolCall[]) {
                    const aid = tc.agent_node_id;
                    if (aid) (toolCallsByAgent[aid] ??= []).push(tc);
                }
            } catch (e) {
                console.warn(
                    '[FlowCanvas] Failed to fetch tool calls for run results:',
                    e
                );
            }

            const results: NodeRunResult[] = ran.map((n) => {
                const meta = getNodeIconMeta(n.type || '');
                const isAgent = n.type === 'agent';
                // Some runtimes attach tool calls to the response package instead of
                // the execution detail. Prefer the package when present.
                const pkgCalls = isAgent
                    ? toReplayToolCalls(n.data?.output)
                    : [];
                return {
                    nodeId: n.id,
                    nodeType: n.type || '',
                    label:
                        (n.data?.label as string | undefined) ||
                        meta?.label ||
                        n.type ||
                        n.id,
                    // The dialog's story derivation recognises the fired
                    // trigger the way the canvas does — by the node's
                    // CURRENT operation.
                    operation: n.data?.operation as string | undefined,
                    iconHtml: meta?.iconHtml,
                    iconColor: meta?.iconColor,
                    status:
                        n.data?._lastRunStatus === 'error'
                            ? 'error'
                            : 'completed',
                    output: n.data?.output,
                    error:
                        (n.data?._lastRunError as string | undefined) ||
                        (n.data?.error as string | undefined),
                    // Set by the live workflow:node:state event, so the popup
                    // that opens right after a run offers the same fix the
                    // config panel's banner does.
                    errorAction: n.data?.errorAction as
                        | NodeRunResult['errorAction']
                        | undefined,
                    isAgent,
                    toolCalls: isAgent
                        ? pkgCalls.length > 0
                            ? pkgCalls
                            : toolCallsByAgent[n.id] || []
                        : [],
                };
            });
            // Agents first, then in execution order (by output timestamp).
            const tsOf = (id: string) =>
                (nodesRef.current.find((n) => n.id === id)?.data
                    ?.outputTimestamp as number | undefined) ?? 0;
            results.sort(
                (a, b) =>
                    Number(b.isAgent) - Number(a.isAgent) ||
                    tsOf(a.nodeId) - tsOf(b.nodeId)
            );

            setRunResults(results);
            setRunResultsExecId(execId); // anchors the in-popup run switcher
            setRunResultsLoading(false);
            // Always keep results available (the top-left pill reopens them); only
            // AUTO-open the popup when the user hasn't opted out in Settings.
            if (!resultsPopupDisabledRef.current) setRunResultsOpen(true);
        },
        [workflowId]
    );
    useEffect(() => {
        openRunResultsRef.current = openRunResults;
    }, [openRunResults]);

    // Open the results popup for ANY past run (the run-history pill path). Unlike
    // openRunResults (which reads this session's live node data), this rebuilds
    // NodeRunResult[] from the CAS: execution detail gives the graph snapshot +
    // per-node status/error + tool calls, and get_node_outputs returns every
    // node's output for that run in one call — so the same dialog renders an
    // arbitrary historical run with its outputs pre-filled.
    const openRunResultsForExecution = useCallback(
        async (log: WorkflowExecutionLog) => {
            if (isMobileRef.current) return; // no room to view outputs on mobile
            // Optimistic "running" entries carry a synthetic id (run-<ts>), not a real
            // execution UUID — there's no persisted run to fetch yet, so don't try.
            if (
                !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                    log.id
                )
            )
                return;
            // Open the popup immediately (showing a loading state) so the pill / run
            // switcher feel instant, then fill in the fetched results.
            setRunResultsExecId(log.id);
            setRunResultsOpen(true);
            setRunResultsLoading(true);
            try {
                const [detail, outputsResp] = (await Promise.all([
                    sendEventAsync({
                        event_name: 'workflow:get_execution_detail',
                        workflow_id: workflowId,
                        execution_id: log.id,
                    } as any),
                    sendEventAsync({
                        event_name: 'workflow:get_node_outputs',
                        workflow_id: workflowId,
                        execution_id: log.id,
                    } as any),
                ])) as [any, any];
                const nodeById = new Map<string, any>(
                    (detail?.graph?.nodes || []).map((n: any) => [n.id, n])
                );
                const outputs: Record<string, unknown> =
                    outputsResp?.outputs || {};
                const toolCallsByAgent: Record<string, ReplayToolCall[]> = {};
                for (const tc of (detail?.tool_calls ||
                    []) as ReplayToolCall[]) {
                    const aid = tc.agent_node_id;
                    if (aid) (toolCallsByAgent[aid] ??= []).push(tc);
                }
                const results: NodeRunResult[] = (detail?.node_results || [])
                    .filter(
                        (r: any) =>
                            ['completed', 'error', 'skipped'].includes(
                                r.last_run_status
                            ) || r.has_output
                    )
                    .map((r: any) => {
                        const gn = nodeById.get(r.node_id);
                        const type = gn?.type || '';
                        const meta = getNodeIconMeta(type);
                        const isAgent = type === 'agent';
                        const status: NodeRunResult['status'] =
                            r.last_run_status === 'error'
                                ? 'error'
                                : r.last_run_status === 'skipped'
                                  ? 'skipped'
                                  : 'completed';
                        const out = outputs[r.node_id];
                        const pkgCalls = isAgent ? toReplayToolCalls(out) : [];
                        return {
                            nodeId: r.node_id,
                            nodeType: type,
                            label:
                                (gn?.data?.label as string | undefined) ||
                                (gn?.config?.label as string | undefined) ||
                                meta?.label ||
                                type ||
                                r.node_id,
                            // The snapshot's node shape varies by how the run
                            // started: FE-initiated runs store ReactFlow nodes
                            // (data.operation), headless webhook/cron/agent
                            // runs store the backend blob (config.operation) —
                            // and headless runs are exactly the trigger-fired
                            // ones, so missing this read dropped the fired
                            // trigger into "Also ran".
                            operation:
                                (gn?.data?.operation as string | undefined) ??
                                (gn?.config?.operation as string | undefined) ??
                                (gn?.data?.config?.operation as
                                    | string
                                    | undefined),
                            iconHtml: meta?.iconHtml,
                            iconColor: meta?.iconColor,
                            status,
                            output: out,
                            error: r.last_run_error || undefined,
                            // Re-derived server-side from the stored message,
                            // so browsing a past run offers the same fix the
                            // live one did.
                            errorAction: r.last_run_error_action || undefined,
                            isAgent,
                            toolCalls: isAgent
                                ? pkgCalls.length > 0
                                    ? pkgCalls
                                    : toolCallsByAgent[r.node_id] || []
                                : [],
                        };
                    });
                results.sort((a, b) => Number(b.isAgent) - Number(a.isAgent)); // agents first
                setRunResults(results); // [] is fine — the popup shows an empty state
            } catch (e) {
                console.error(
                    '[FlowCanvas] Failed to open run results for execution:',
                    e
                );
                setRunResults([]);
            } finally {
                setRunResultsLoading(false);
            }
        },
        [workflowId]
    );

    // Trigger workflow execution from an interface form submission
    const handleFormSubmit = useCallback(
        (formNodeId: string, values: Record<string, unknown>) => {
            if (!workflowId) {
                console.warn('[FlowCanvas] Form submit blocked: no workflowId');
                return;
            }

            logActivity(EVENTS.APP_SESSION_FORM_SUBMITTED, {
                workflow_id: workflowId,
                form_node_id: formNodeId,
                field_count: Object.keys(values).length,
            });

            const currentNodes = nodesRef.current;
            const currentEdges = edgesRef.current;

            // Compute guaranteed-reachable interface nodes for loading states
            runStartTimeRef.current = Date.now();
            const nodeTypes = new Map(
                currentNodes.map((n) => [n.id, n.type ?? ''])
            );
            const reachable = getGuaranteedReachableNodes(
                currentEdges,
                formNodeId,
                nodeTypes
            );
            const interfaceLoadingIds = new Set<string>();
            for (const nodeId of reachable) {
                const nodeType = nodeTypes.get(nodeId) ?? '';
                if (
                    nodeType.startsWith('interface-') &&
                    nodeType !== 'interface-form'
                ) {
                    interfaceLoadingIds.add(nodeId);
                }
            }
            setLoadingBlockIds(interfaceLoadingIds);

            // Form submission re-executes the form node + everything downstream — clear
            // their stale run-state so no prior completed/failed badge lingers.
            resetNodesRunState(runResetIds(currentEdges, formNodeId));

            addPendingExecution();
            const runId = `run-${Date.now()}`;
            setLogs((prev) => [
                {
                    id: runId,
                    timestamp: new Date(),
                    status: 'running',
                    message: `Executing workflow from form submission...`,
                } as WorkflowExecutionLog,
                ...prev,
            ]);

            const graph = serializeGraphForExecution(
                currentNodes,
                currentEdges
            );
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    start_node_id: formNodeId,
                    inputs: values,
                    nodes: graph.nodes,
                    edges: graph.edges,
                    replay_nodes: graph.nodes,
                    replay_edges: graph.edges,
                })
            );
        },
        [workflowId, workflowSettings, logActivity, resetNodesRunState]
    );

    // Runs an agent node with a fresh `message` (and optional model swap) when
    // the user sends from an AgentChatBlock in the Interface tab. Mirrors
    // `handleFormSubmit`: dispatches a WorkflowExecuteRequest starting at the
    // agent node, with a one-shot config override for `message` (so the user's
    // chat input doesn't permanently overwrite the agent's saved message field).
    // The model picked in the chat UI IS persisted to the node config — that's
    // the "set up" half of the feature.
    const handleAgentChatSend = useCallback(
        (
            agentNodeId: string,
            message: string,
            model: string,
            /** The conversation to send into. The chat passes it explicitly
             *  because it may have just minted it — reading it back off the
             *  node config would race the write that put it there. */
            conversationKey?: string,
            /** Files attached to this message (already uploaded to R2) —
             *  ride the one-shot override as `message_attachments`. */
            attachments?: AgentChatAttachment[]
        ) => {
            if (!workflowId) {
                console.warn(
                    '[FlowCanvas] Agent chat send blocked: no workflowId'
                );
                return;
            }

            const currentNodes = nodesRef.current;
            const currentEdges = edgesRef.current;
            const agentNode = currentNodes.find((n) => n.id === agentNodeId);
            if (!agentNode) {
                console.warn(
                    '[FlowCanvas] Agent chat send: node not found',
                    agentNodeId
                );
                return;
            }

            const agentData = agentNode.data as
                | { config?: { model?: string; conversation_key?: string } }
                | undefined;
            const currentModel = agentData?.config?.model;
            const currentConvKey = agentData?.config?.conversation_key;

            // Persist model + conversation_key diff to the agent node's config.
            const configPatch = buildAgentChatConfigPatch({
                currentModel,
                currentConversationKey: currentConvKey,
                selectedModel: model,
            });
            if (configPatch) {
                setNodes((prev) =>
                    updateNodeInList(prev, agentNodeId, { config: configPatch })
                );
            }

            // NB: deliberately NOT calling addPendingExecution() here. Chat sends
            // have their own streaming indicators inside the AgentChatBlock (the
            // inline pulsing dot, and the "Agent stopped: …" banner on terminal
            // states). Registering a pending-* placeholder on the global Run/Stop
            // button means a backend that fails to emit workflow:complete (rate
            // limits, agent crashes, dropped worker emits) leaves the toolbar
            // stuck on "Stop" until the 60s safety-net timeout fires.
            const runId = `run-${Date.now()}`;
            setLogs((prev) => [
                {
                    id: runId,
                    timestamp: new Date(),
                    status: 'running',
                    message: `Agent chat: ${message.slice(0, 60)}${message.length > 60 ? '…' : ''}`,
                } as WorkflowExecutionLog,
                ...prev,
            ]);

            const graph = serializeGraphForExecution(
                currentNodes,
                currentEdges
            );
            const runNodes = graph.nodes.map((n) => {
                if (n.id !== agentNodeId) return n;
                // One-shot override for this run only.
                return {
                    ...n,
                    config: buildAgentChatRunOverride({
                        currentConfig: n.config as Record<string, unknown>,
                        message,
                        model,
                        conversationKey:
                            conversationKey ??
                            (typeof currentConvKey === 'string'
                                ? currentConvKey
                                : undefined),
                        attachments,
                    }),
                };
            });
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    start_node_id: agentNodeId,
                    nodes: runNodes,
                    edges: graph.edges,
                    replay_nodes: runNodes,
                    replay_edges: graph.edges,
                })
            );
        },
        [workflowId, setNodes]
    );

    // Stop a specific execution, or all if no id is given.
    const stopWorkflow = useCallback((executionId?: string) => {
        const execMap = activeExecutionsRef.current;
        if (execMap.size === 0) return;

        const idsToStop = executionId
            ? [executionId].filter((id) => execMap.has(id))
            : [...execMap.keys()];

        if (idsToStop.length === 0) return;

        for (const id of idsToStop) {
            // Only send stop for real executions, not optimistic pending- entries
            if (!id.startsWith('pending-')) {
                if (workflowId)
                    getWorkflowPresenceService(workflowId).sendStopExecution(
                        id
                    );
            }
        }

        // Clear highlight if the hovered execution is being stopped
        setHoveredExecutionId((prev) =>
            prev && idsToStop.includes(prev) ? null : prev
        );

        // Optimistically remove from active set
        setActiveExecutions((prev) => {
            const next = new Map(prev);
            for (const id of idsToStop) next.delete(id);
            return next;
        });
        if (idsToStop.length === execMap.size) {
            // Stopped everything
            setLoadingBlockIds(new Set());
            runStartTimeRef.current = 0;
        }
    }, []);

    // Function to run workflow starting from a specific node and continuing downstream.
    // Detects if downstream nodes reference upstream data — if so, includes predecessors
    // and shows an info toast. Otherwise, runs forward-only.
    // `background` runs are triggered by interface components fetching their own
    // data via the SDK — they execute for real but stay out of the global
    // Run/Stop button and the execution log (per-node states still update).
    const runFromNodeRef = useRef<
        | ((
              nodeId: string,
              configOverrides?: Record<string, Record<string, unknown>>,
              background?: boolean
          ) => void)
        | null
    >(null);
    const runFromNode = useCallback(
        (
            nodeId: string,
            configOverrides?: Record<string, Record<string, unknown>>,
            background = false
        ) => {
            if (!workflowId) return;

            const currentNodes = nodesRef.current;
            const currentEdges = edgesRef.current;

            // Check if any forward-reachable node references upstream data
            const { hasUpstreamRefs, referencedUpstreamNodeIds } =
                detectUpstreamReferences(nodeId, currentNodes, currentEdges);

            // Same gate as the Run button, over the nodes this run will
            // ACTUALLY execute. That is not just the node and its downstream:
            // when something downstream references upstream data the request
            // goes out with forward_only=false and the backend runs the
            // ancestors too, so gating on the forward set alone let a run start
            // with a broken upstream node in it — the case that looked like the
            // pill ignoring the gate entirely.
            //
            // Background interface fetches skip it: nothing is watching, and a
            // popup over a data fetch is worse than the error.
            const willExecute = runResetIds(currentEdges, nodeId);
            if (hasUpstreamRefs) {
                for (const id of withAncestors(
                    currentEdges,
                    referencedUpstreamNodeIds
                )) {
                    willExecute.add(id);
                }
            }
            if (
                !background &&
                gateRunOnIncompleteSteps(
                    nodesForExecutionIds(
                        withWiredToolProviders(currentEdges, willExecute)
                    ),
                    (gateOverrides) =>
                        runFromNodeRef.current?.(
                            nodeId,
                            mergeConfigOverrides(
                                configOverrides,
                                gateOverrides
                            ),
                            background
                        ),
                    { startNodeId: nodeId }
                )
            ) {
                return;
            }
            if (hasUpstreamRefs) {
                toast.info('Including upstream nodes', {
                    description:
                        'Downstream nodes reference data from upstream nodes.',
                    duration: 3000,
                });
            }

            // Clear stale run-state on this node + everything downstream of it (all of
            // which will re-execute). Skipped for background interface-data fetches so
            // they don't visually wipe the canvas. Single-node runs use runSingleNode,
            // which never resets downstream.
            if (!background) {
                resetNodesRunState(runResetIds(currentEdges, nodeId));
            }

            // Skip the optimistic placeholder + running log for background runs —
            // they must not surface in the global Run button or the Logs tab.
            if (!background) {
                addPendingExecution();
                const runningLog: WorkflowExecutionLog = {
                    id: `run-${Date.now()}`,
                    timestamp: new Date(),
                    status: 'running',
                    message: `Executing workflow from node ${nodeId}...`,
                };
                setLogs((prev) => [runningLog, ...prev]);
            }

            const replayGraph = serializeGraphForExecution(
                currentNodes,
                currentEdges
            );
            const executionGraph = serializeGraphForExecution(
                currentNodes,
                currentEdges
            );
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    start_node_id: nodeId,
                    forward_only: !hasUpstreamRefs,
                    background,
                    nodes: executionGraph.nodes.map((n) => {
                        const config = {
                            ...(n.config as Record<string, unknown>),
                        };
                        // Inject carousel-selected output as mockedOutput so backend uses it
                        // Skip the start node — it should execute for real, not use stale output
                        const selection =
                            n.id !== nodeId
                                ? nodeOutputSelectionsRef.current[
                                      n.id as string
                                  ]
                                : undefined;
                        if (selection) config.mockedOutput = selection.output;
                        return {
                            ...n,
                            config,
                        };
                    }),
                    edges: executionGraph.edges,
                    replay_nodes: replayGraph.nodes,
                    replay_edges: replayGraph.edges,
                    ...(configOverrides
                        ? { config_overrides: configOverrides }
                        : {}),
                })
            );
        },
        [
            workflowId,
            resetNodesRunState,
            gateRunOnIncompleteSteps,
            nodesForExecutionIds,
        ]
    );
    runFromNodeRef.current = runFromNode;

    // Listen for "run from node" custom events dispatched by the node hover pill and SDK bridge
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail;
            const nodeId = detail?.nodeId as string | undefined;
            const configOverrides = detail?.configOverrides as
                | Record<string, Record<string, unknown>>
                | undefined;
            const background = detail?.background === true;
            if (nodeId) runFromNode(nodeId, configOverrides, background);
        };
        document.addEventListener('noclick:run-from-node', handler);
        return () =>
            document.removeEventListener('noclick:run-from-node', handler);
    }, [runFromNode]);

    // Listen for the canvas-side "Chat" pill on an agent node — switches to
    // the Interface tab and makes that agent's fullscreen chat block the
    // active sub-tab. The agent node has already set show_in_interface=true
    // before dispatching, so the block will appear in interfaceInitialBlocks
    // on the next render cycle. We defer the sub-tab switch a microtask so
    // the WorkflowInterface has a chance to mount the new block first.
    useEffect(() => {
        const handler = (e: Event) => {
            const nodeId = (e as CustomEvent).detail?.nodeId as
                | string
                | undefined;
            if (!nodeId) return;
            setActiveTab('interface');
            // Two RAF ticks: one for FlowCanvas re-render switching the tab,
            // one for WorkflowInterface to reconcile its initialBlocks with
            // the now-flagged agent node before the sub-tab pick lands.
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    workflowInterfaceRef.current?.setActiveSubTab(nodeId);
                });
            });
        };
        document.addEventListener('noclick:open-agent-chat', handler);
        return () =>
            document.removeEventListener('noclick:open-agent-chat', handler);
    }, [setActiveTab]);

    // The Test Run screen renders inside the agent's interface chat block, so
    // every test-run hand-off must first un-hide an agent whose chat was
    // turned off (show_in_interface='false' — e.g. by the AI builder) or the
    // hand-off flags arm with no consumer. Same write the Chat pill and the
    // Run-popup lone-agent path make. Returns whether an agent chat exists.
    const ensureAgentChatVisible = useCallback((): boolean => {
        const hidden = hiddenAgentToRevealForTestRun(nodesRef.current);
        if (hidden) {
            setNodes((ns) =>
                updateNodeInList(ns, hidden, {
                    config: { show_in_interface: 'true' },
                })
            );
        }
        return nodesRef.current.some((n) => n.type === 'agent');
    }, [setNodes]);

    // Builder-fired <run_test/>: switch to the Interface tab and arm the Test
    // Run screen's auto-start. requestTestRun re-hydrates authored runs (a
    // just-authored slug must resolve) and primes the sticky flags, so the
    // agent block can mount after the event and still pick it up.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail as
                | { workflowId?: string; trigger?: string; run?: string }
                | undefined;
            if (!detail?.workflowId || detail.workflowId !== workflowId) return;
            ensureAgentChatVisible();
            setActiveTab('interface');
            void requestTestRun(detail.workflowId, {
                trigger: detail.trigger,
                run: detail.run,
            });
        };
        document.addEventListener('noclick:run-test', handler);
        return () => document.removeEventListener('noclick:run-test', handler);
    }, [setActiveTab, workflowId, ensureAgentChatVisible]);

    // Readiness cards ("Connect Gmail") anywhere in the workspace deep-link
    // into the Setup tab at that node's credential step — sticky valtio so
    // the Setup view can mount after the flag is set.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail as
                | { workflowId?: string; stepKey?: string }
                | undefined;
            if (!detail?.workflowId || detail.workflowId !== workflowId) return;
            const proxy = getLocalComponentValtio('workflowSetup');
            if (!proxy.state) proxy.state = {};
            proxy.state[`pending-step-${detail.workflowId}`] = detail.stepKey ?? null;
            setActiveTab('setup');
        };
        document.addEventListener('noclick:open-setup-step', handler);
        return () =>
            document.removeEventListener('noclick:open-setup-step', handler);
    }, [setActiveTab, workflowId]);

    // The builder wrote workflows.settings (variables / test-run authoring):
    // re-read so the Variables dialog and Setup tab reflect it — a stale
    // local snapshot would clobber the builder's write on its next save.
    useEffect(() => {
        const handler = (e: Event) => {
            const detail = (e as CustomEvent).detail as
                | { workflowId?: string }
                | undefined;
            if (!detail?.workflowId || detail.workflowId !== workflowId) return;
            void (async () => {
                try {
                    const res: any = await sendEventAsync({
                        event_name: 'workflow:get',
                        workflow_id: detail.workflowId,
                    } as any);
                    if (res?.workflow?.settings) {
                        setWorkflowSettings(res.workflow.settings);
                    }
                } catch {
                    // Next full load re-reads; worst case is a stale dialog.
                }
                void rehydrateRehearsalAuthoring(detail.workflowId!);
            })();
        };
        document.addEventListener('noclick:workflow-settings-updated', handler);
        return () =>
            document.removeEventListener(
                'noclick:workflow-settings-updated',
                handler
            );
    }, [workflowId]);

    // When the AI builder finishes a build, nudge the user toward a chat-driven
    // agent — an agent node with NO triggers wired into its input
    // (getAgentTriggerSources empty), so it runs by chatting rather than by a
    // fired event. New agents already default to showing in the Interface tab
    // (seeded at creation), so we just spotlight the Interface tab once so the
    // user knows where to chat. Fires on the builder's terminal event; a defer
    // lets the builder's final node/edge mutations commit to the refs first.
    useEffect(() => {
        const onEditEvent = (e: Event) => {
            const detail = (e as CustomEvent).detail as
                | { type?: string; cancelled?: boolean }
                | undefined;
            if (detail?.type !== 'complete' || detail.cancelled) return;
            requestAnimationFrame(() => {
                // Spotlight a triggerless agent that will actually render in the
                // Interface tab (shown unless explicitly hidden) — else no chat to open.
                const chatAgent = getTriggerlessAgents(
                    nodesRef.current,
                    edgesRef.current
                ).find((agent) =>
                    agentShowsInInterface(
                        (
                            agent.data?.config as
                                | Record<string, unknown>
                                | undefined
                        )?.show_in_interface
                    )
                );
                if (!chatAgent) return;
                // One-time Interface-tab spotlight (desktop only; seen only on completion).
                if (isMobileRef.current || agentChatWalkthroughSeenRef.current)
                    return;
                setAgentChatWalkthroughNodeId(chatAgent.id);
                setAgentChatWalkthroughActive(true);
                logActivity(EVENTS.AGENT_CHAT_WALKTHROUGH_SHOWN, {
                    workflow_id: workflowId,
                });
            });
        };
        document.addEventListener('noclick:workflow:edit:event', onEditEvent);
        return () =>
            document.removeEventListener(
                'noclick:workflow:edit:event',
                onEditEvent
            );
    }, [logActivity, workflowId]);

    // Listen for "stop workflow" custom events dispatched by SDK bridge (stops all)
    useEffect(() => {
        const handler = () => {
            if (isWorkflowRunning) stopWorkflow();
        };
        document.addEventListener('noclick:stop-workflow', handler);
        return () =>
            document.removeEventListener('noclick:stop-workflow', handler);
    }, [isWorkflowRunning, stopWorkflow]);

    // Shift+R triggers the main Run/Stop button — run the whole workflow, or stop
    // it if already running (mirrors the top-bar button). Ignored while typing or
    // under a modal.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key.toLowerCase() !== 'r' || !e.shiftKey) return;
            if (replayActiveRef.current) return;
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            if (isModalOpen()) return;
            e.preventDefault();
            if (isWorkflowRunning) stopWorkflow();
            else requestRunWorkflow();
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [isWorkflowRunning, requestRunWorkflow, stopWorkflow]);

    // Function to run a single node with previous nodes' outputs as mocked data
    // Returns { success, executionId? } on start, or { success: false, error } if not.
    // executionId is the optimistic `pending-<ts>` placeholder — callers (e.g. the
    // helper's Run→Stop toggle) hold it so they can target Stop at THIS run before
    // workflow:started arrives with the real id.
    // Uses refs to avoid recreating callback on every node position change
    const runSingleNodeRef = useRef<
        | ((
              nodeId: string,
              configOverrides?: Record<string, Record<string, unknown>>
          ) => {
              success: boolean;
              error?: string;
              executionId?: string;
          })
        | null
    >(null);
    const runSingleNode = useCallback(
        (
            nodeId: string,
            configOverrides?: Record<string, Record<string, unknown>>
        ): { success: boolean; error?: string; executionId?: string } => {
            if (!workflowId) {
                return { success: false, error: 'No workflow ID' };
            }

            // Prepare the subset graph for single node execution using refs
            const result = prepareNodeExecution(
                nodeId,
                nodesRef.current,
                edgesRef.current,
                nodeOutputSelectionsRef.current
            );
            if (!result.success) {
                return { success: false, error: result.error };
            }

            // Same gate as the other two entry points, over exactly the nodes
            // this run will execute — the target plus any upstream whose output
            // is being reused. Reports success: nothing failed, the run is
            // waiting on the user, and the caller's Run→Stop toggle must not
            // flip for a run that has not started.
            if (
                gateRunOnIncompleteSteps(
                    nodesForExecutionIds(
                        withWiredToolProviders(
                            edgesRef.current,
                            result.nodes.map((n) => n.id)
                        )
                    ),
                    (gateOverrides) =>
                        runSingleNodeRef.current?.(nodeId, gateOverrides),
                    { startNodeId: nodeId }
                )
            ) {
                return { success: true };
            }

            // Clear this node's prior run state before re-running — every other
            // run entrypoint resets, and without it a failed re-run leaves the
            // previous run's `output` in place (node:output only fires on
            // success), which then shows as this run's result. Reset ONLY this
            // node: `result.nodes` may include upstream nodes whose existing
            // outputs are being reused as inputs.
            resetNodesRunState(new Set([nodeId]));

            const pendingId = addPendingExecution();

            // Single-node test run: its output already shows inline in the config
            // panel, so don't auto-open the results popup over it.
            suppressNextRunPopupRef.current = true;

            // Add initial running log
            const runningLog: WorkflowExecutionLog = {
                id: `run-${Date.now()}`,
                timestamp: new Date(),
                status: 'running',
                message: `Executing node ${nodeId}...`,
            };
            setLogs((prev) => [runningLog, ...prev]);

            const replayGraph = serializeGraphForExecution(
                nodesRef.current,
                edgesRef.current
            );
            sendEvent(
                WorkflowExecuteRequest.create({
                    workflow_id: workflowId,
                    nodes: result.nodes,
                    edges: result.edges,
                    replay_nodes: replayGraph.nodes,
                    replay_edges: replayGraph.edges,
                    ...(configOverrides
                        ? { config_overrides: configOverrides }
                        : {}),
                })
            );

            return { success: true, executionId: pendingId };
        },
        [
            isWorkflowRunning,
            workflowId,
            resetNodesRunState,
            gateRunOnIncompleteSteps,
            nodesForExecutionIds,
        ]
    );
    runSingleNodeRef.current = runSingleNode;

    // Handle checkpoint restore - replaces current nodes/edges with checkpoint data
    // Uses refs to avoid recreating callback on every node position change
    const handleCheckpointRestore = useCallback(
        (restoredNodes: Node[], restoredEdges: Edge[]) => {
            // Capture current state for undo before restoring (using refs)
            captureState(nodesRef.current, edgesRef.current);

            // Update nodes and edges with restored data
            setNodes(restoredNodes);
            setEdges(restoredEdges);

            // Clear selected node since the node might not exist in restored state
            setSelectedNode(null);
        },
        [setNodes, setEdges, captureState, setSelectedNode]
    );

    // Listen for node state changes (running, completed, error)
    useSocketEvent(
        'workflow:node:state',
        useCallback(
            (data) => {
                // Filter events for this workflow only
                if (data.workflow_id && data.workflow_id !== workflowId) return;

                // Track this node in the execution's nodeIds set (for hover-highlight).
                // Creates the entry if it doesn't exist yet (node:state can arrive before workflow:started).
                // Background runs (SDK component data fetches) are excluded — they must
                // not register in activeExecutions or they'd flip the global Run button.
                if (
                    data.execution_id &&
                    data.node_id &&
                    !backgroundExecutionIdsRef.current.has(data.execution_id)
                ) {
                    const executionId = data.execution_id;
                    const nodeId = data.node_id;
                    setActiveExecutions((prev) => {
                        const entry = prev.get(executionId);
                        if (entry?.nodeIds.has(nodeId)) return prev;
                        const next = new Map(prev);
                        const updated = entry
                            ? { ...entry, nodeIds: new Set(entry.nodeIds) }
                            : {
                                  startedAt: Date.now(),
                                  nodeIds: new Set<string>(),
                              };
                        updated.nodeIds.add(nodeId);
                        next.set(executionId, updated);
                        return next;
                    });
                }

                // Update node visual state based on execution state
                setNodes((currentNodes) => {
                    const updatedNodes = currentNodes.map((n) => {
                        if (n.id !== data.node_id) return n;

                        const currentState = n.data?.executionState;
                        const currentExecutionId = n.data?._executionId;

                        // Block stale "running" events within the SAME execution, but only for
                        // truly terminal states (error, skipped). "completed" is NOT blocked because
                        // iteration body nodes cycle through running → completed per iteration.
                        if (
                            (currentState === 'error' ||
                                currentState === 'skipped') &&
                            data.state === 'running' &&
                            data.execution_id &&
                            currentExecutionId === data.execution_id
                        ) {
                            return n;
                        }

                        // Clear stale streaming text from the previous run on
                        // 'running' so the panel doesn't briefly show old bytes
                        // before the new chunks arrive. Other state transitions
                        // leave progress alone — the output handler clears it
                        // when the canonical WorkflowNodeOutputEvent lands.
                        const extras: Record<string, unknown> = {
                            executionState: data.state,
                            error: data.error,
                            // The one thing the user can do about this failure
                            // (backend: provider_errors._action_for). Cleared
                            // on every state change so a stale button can't
                            // outlive the error it belonged to.
                            errorAction: data.error_action,
                            _executionId: data.execution_id,
                        };
                        if (data.state === 'running') {
                            extras.progress = undefined;
                        }
                        // Stamp the persisted "last run" fields on terminal states so the
                        // status chip ("✓/✗ N ago") shows immediately after a live run —
                        // mirroring what the backend writes to the workflow_node_outputs
                        // table for headless runs.
                        if (
                            data.state === 'completed' ||
                            data.state === 'error'
                        ) {
                            extras._lastRunStatus = data.state;
                            extras._lastRunAt = Date.now();
                            extras._lastRunError =
                                data.state === 'error' ? data.error : undefined;
                        }
                        return applyNodeUpdate(n, { extras });
                    });

                    // Surface a node error. Desktop runs no longer hijack the camera
                    // — users navigate to failed nodes manually via the
                    // ErrorNodeNavigator arrows. Mobile still surfaces a queued
                    // banner (FlowHelper is hidden there), and background runs
                    // (SDK component data fetches) show a dismissible toast so the
                    // failure isn't swallowed without disturbing the canvas.
                    const isBackgroundError =
                        !!data.execution_id &&
                        backgroundExecutionIdsRef.current.has(
                            data.execution_id
                        );
                    if (data.state === 'error') {
                        const erroredNode = updatedNodes.find(
                            (n) => n.id === data.node_id
                        );
                        if (erroredNode) {
                            const nodeName =
                                (erroredNode.data?.label as
                                    | string
                                    | undefined) ||
                                getNodeMetadata(erroredNode.type ?? 'default')
                                    ?.label ||
                                erroredNode.type ||
                                'Node';
                            const errorMsg =
                                typeof data.error === 'string'
                                    ? data.error
                                    : 'Node failed to execute';
                            if (isBackgroundError) {
                                // Non-intrusive: a toast keyed by node id so re-runs
                                // replace rather than stack the same failure. The
                                // message is humanized into actionable guidance.
                                const { title, description } =
                                    describeNodeError(nodeName, errorMsg);
                                toast.error(title, {
                                    id: `bg-node-error-${data.node_id}`,
                                    description,
                                    duration: 8000,
                                });
                            } else if (isMobile) {
                                // On mobile: FlowHelper is hidden, so surface the error via the queue
                                enqueueMobileError(
                                    `${nodeName} failed`,
                                    errorMsg
                                );
                            }
                        }
                    }

                    return updatedNodes;
                });
            },
            [setNodes, workflowId, isMobile]
        )
    );

    // Listen for node outputs (can be multiple per node for streaming)
    useSocketEvent(
        'workflow:node:output',
        useCallback(
            (data) => {
                // Filter events for this workflow only
                if (data.workflow_id && data.workflow_id !== workflowId) return;

                // Save large outputs to local cache (small outputs will be persisted by backend)
                // This function auto-checks size and only saves if output is large (>=50KB)
                saveLargeOutputIfNeeded(data.node_id, data.output, Date.now());

                // Replace the node's output with the canonical payload. There's
                // no merge logic here: WorkflowNodeOutputEvent is emitted exactly
                // once per node execution and carries the final structured shape.
                // Streaming text accumulates in node.data.progress via the
                // workflow:node:progress handler — see useSocketEvent below — and
                // is cleared here so the panel switches from live streaming back
                // to the canonical output the moment it lands.
                setNodes((currentNodes) =>
                    currentNodes.map((n) => {
                        if (n.id !== data.node_id) return n;
                        const update: Parameters<typeof applyNodeUpdate>[1] = {
                            extras: {
                                output: data.output,
                                outputTimestamp: Date.now(),
                                progress: undefined,
                            },
                        };
                        if (
                            n.type === 'state-manager' &&
                            (data.output as any)?.state
                        ) {
                            update.config = {
                                state: (data.output as any).state,
                            };
                        }
                        return applyNodeUpdate(n, update);
                    })
                );

                // Record per-node timing and remove from loading set
                setLoadingBlockIds((prev) => {
                    if (!prev.has(data.node_id)) return prev;
                    const next = new Set(prev);
                    next.delete(data.node_id);
                    return next;
                });
                // Persist time-to-fill on the node for future progress bar estimates
                if (runStartTimeRef.current > 0) {
                    const timeToFill = Date.now() - runStartTimeRef.current;
                    if (timeToFill > 0) {
                        setNodes((nodes) =>
                            updateNodeInList(nodes, data.node_id, {
                                extras: { _timeToFillMs: timeToFill },
                            })
                        );
                    }
                }

                // Expand loading set when a conditional/switch resolves to a specific branch
                const outputHandle = data.output?.output_handle;
                if (
                    (data.node_type === 'conditional' ||
                        data.node_type === 'switch') &&
                    typeof outputHandle === 'string' &&
                    outputHandle
                ) {
                    const currentEdges = edgesRef.current;
                    const currentNodes = nodesRef.current;
                    const nodeTypes = new Map(
                        currentNodes.map((n) => [n.id, n.type ?? ''])
                    );
                    const newlyReachable = getReachableFromHandle(
                        currentEdges,
                        data.node_id,
                        outputHandle,
                        nodeTypes
                    );
                    const newInterfaceIds: string[] = [];
                    for (const nodeId of newlyReachable) {
                        const nodeType = nodeTypes.get(nodeId) ?? '';
                        if (
                            nodeType.startsWith('interface-') &&
                            nodeType !== 'interface-form'
                        ) {
                            newInterfaceIds.push(nodeId);
                        }
                    }
                    if (newInterfaceIds.length > 0) {
                        setLoadingBlockIds((prev) => {
                            const next = new Set(prev);
                            for (const id of newInterfaceIds) next.add(id);
                            return next;
                        });
                    }
                }

                // Trigger animation on edges where this node is the source

                // For multi-output nodes, only animate the activated handle's edges.
                // Iteration nodes signal via completed=true (done handle) vs loop handle.
                // All other multi-output nodes (conditional, switch, future types) use output_handle.
                const isIterationNode = data.node_type === 'iteration';
                const isIterationComplete =
                    isIterationNode && data.output?.completed === true;
                const activatedHandle = isIterationNode
                    ? isIterationComplete
                        ? 'done'
                        : 'loop'
                    : (data.output?.output_handle as string | undefined);

                const shouldAnimateEdge = (edge: {
                    sourceHandle?: string | null;
                }) => {
                    if (!activatedHandle) return true; // single-output node — animate all
                    return edge.sourceHandle === activatedHandle;
                };

                // Set isAnimating: true for edges from this node
                setEdges((currentEdges) => {
                    const updatedEdges = currentEdges.map((edge) => {
                        if (
                            edge.source === data.node_id &&
                            shouldAnimateEdge(edge)
                        ) {
                            return {
                                ...edge,
                                data: { ...edge.data, isAnimating: true },
                            };
                        }
                        return edge;
                    });
                    return updatedEdges;
                });

                // After animation duration (800ms), set back to false
                setTimeout(() => {
                    setEdges((currentEdges) => {
                        const updatedEdges = currentEdges.map((edge) => {
                            if (
                                edge.source === data.node_id &&
                                shouldAnimateEdge(edge)
                            ) {
                                return {
                                    ...edge,
                                    data: { ...edge.data, isAnimating: false },
                                };
                            }
                            return edge;
                        });
                        return updatedEdges;
                    });
                }, 800); // Match animation duration in AnimatedWorkflowEdge
            },
            [setNodes, setEdges, workflowId, saveLargeOutputIfNeeded]
        )
    );

    // Listen for in-flight node activity (streaming agent text, one-shot
    // self.emit({...}) summaries, etc.). The slot is cleared when
    // workflow:node:state goes to 'running' or when the canonical
    // workflow:node:output lands. See WorkflowNodeProgressEvent for why
    // progress lives in a separate slot from data.output.
    //
    // Two payload modes (exactly one set per event):
    //   - append (string): streaming text — concatenates onto progress.text
    //   - snapshot (dict): one-shot structured payload — replaces progress.snapshot
    useSocketEvent(
        'workflow:node:progress',
        useCallback(
            (data) => {
                if (data.workflow_id && data.workflow_id !== workflowId) return;
                setNodes((current) =>
                    current.map((n) => {
                        if (n.id !== data.node_id) return n;
                        const existing = ((n.data as any)?.progress ?? {}) as {
                            text?: string;
                            snapshot?: unknown;
                        };
                        const next: { text?: string; snapshot?: unknown } = {
                            ...existing,
                        };
                        if (
                            typeof data.append === 'string' &&
                            data.append.length > 0
                        ) {
                            next.text = (existing.text ?? '') + data.append;
                        }
                        if (
                            data.snapshot !== undefined &&
                            data.snapshot !== null
                        ) {
                            next.snapshot = data.snapshot;
                        }
                        return applyNodeUpdate(n, {
                            extras: { progress: next },
                        });
                    })
                );
            },
            [setNodes, workflowId]
        )
    );

    // Expose coordinate conversion function globally
    useEffect(() => {
        // Store the conversion function globally so Dashboard can use it
        window.screenToFlowPosition = (screenX: number, screenY: number) => {
            if (!screenToFlowPosition) return { x: screenX, y: screenY };

            // ReactFlow's screenToFlowPosition already handles all coordinate transformations
            // including viewport offset, zoom, and pan. We just need to pass the screen coordinates directly.
            return screenToFlowPosition({ x: screenX, y: screenY });
        };

        return () => {
            // Clean up
            delete window.screenToFlowPosition;
        };
    }, [screenToFlowPosition]);

    // Listen for components being added to the flow
    useEffect(() => {
        const handleComponentAddedToFlow = (
            e: CustomEvent<{ sourceId: string; nodeId: string }>
        ) => {
            const { sourceId, nodeId } = e.detail;
            // Component added to flow
        };

        window.addEventListener(
            'componentAddedToFlow',
            handleComponentAddedToFlow as EventListener
        );

        return () => {
            window.removeEventListener(
                'componentAddedToFlow',
                handleComponentAddedToFlow as EventListener
            );
        };
    }, []);

    // Check for pending node selection (set by ChatBox or deep link before navigation)
    // Uses nodesRef to avoid re-running on every node position change during drag.
    // For deep links, nodes may not be loaded when ReactFlow first initializes,
    // so we poll nodesRef until the target node is found (max 5 seconds).
    useEffect(() => {
        if (!workflowId || !isReactFlowReady) return;

        const processPending = (): boolean => {
            const pending = getPendingNodeSelection();
            if (!pending || pending.workflowId !== workflowId) return true; // nothing to do

            const currentNodes = nodesRef.current;
            if (currentNodes.length === 0) return false; // nodes not loaded yet, retry

            const node = currentNodes.find((n) => n.id === pending.nodeId);
            if (!node) return false; // target node not found yet, retry

            // Found the node - clear the pending selection so we don't process again
            clearPendingNodeSelection();

            // Clean deep-link URL params so they don't re-trigger
            setSearchParamsRef.current(
                (prev) => {
                    const newParams = new URLSearchParams(prev);
                    newParams.delete('node');
                    newParams.delete('field');
                    return newParams;
                },
                { replace: true }
            );

            // Use requestAnimationFrame to ensure DOM is ready before selecting
            requestAnimationFrame(() => {
                // Update the node's selected state in ReactFlow
                setNodes((prevNodes) =>
                    prevNodes.map((n) => ({
                        ...n,
                        selected: n.id === pending.nodeId,
                    }))
                );

                // Set the selected node for config view
                setSelectedNode(node);

                // Open config panel for deep-link navigation
                setIsConfigViewExpanded(true);
                setFlowHelperActiveTab('config');

                // Pan to the node after selection is applied
                setTimeout(() => {
                    panToNodeCallback(pending.nodeId);
                }, 50);

                // If deep link includes a field, go full screen and scroll to it
                if (pending.fieldKey) {
                    setIsFlowHelperFullScreen(true);
                    setTimeout(() => {
                        document.dispatchEvent(
                            new CustomEvent('noclick:field:scroll-to', {
                                detail: { fieldKey: pending.fieldKey },
                            })
                        );
                    }, 300);
                }
            });
            return true;
        };

        // Try immediately, then poll if nodes aren't loaded yet
        if (processPending()) return;
        const interval = setInterval(() => {
            if (processPending()) clearInterval(interval);
        }, 150);
        // Give up after 5 seconds to avoid leaking intervals
        const timeout = setTimeout(() => clearInterval(interval), 5000);
        return () => {
            clearInterval(interval);
            clearTimeout(timeout);
        };
    }, [
        workflowId,
        setSelectedNode,
        setNodes,
        panToNodeCallback,
        isReactFlowReady,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setIsFlowHelperFullScreen,
    ]);

    const onNodesChange = useCallback(
        (changes: NodeChange[]) => {
            // Block position/dimension changes while syncing (cached data is read-only)
            if (isSyncingRef.current) {
                changes = changes.filter(
                    (c) => c.type !== 'position' && c.type !== 'dimensions'
                );
                if (changes.length === 0) return;
            }
            // Filter out changes to cursor nodes (they're ephemeral visual elements)
            const workflowChanges = changes.filter((change) => {
                const nodeId = 'id' in change ? change.id : null;
                return nodeId ? !isCursorNode(nodeId) : true;
            });

            // Skip if no workflow node changes
            if (workflowChanges.length === 0) return;

            // Track deleted nodes for cron schedule cleanup and broadcast to collaborators
            workflowChanges.forEach((change) => {
                if (change.type === 'remove') {
                    deletedNodeIdsRef.current.add(change.id);
                    broadcastNodeRemove(change.id);
                    // Reverse auto-sync: remove corresponding block from interface grid
                    workflowInterfaceRef.current?.removeBlock(change.id);
                }
            });

            // Broadcast user-driven resizes (NodeResizer) to collaborators over
            // the node:update channel as a transport hint. xyflow tags only
            // NodeResizer changes with `resizing` (true mid-drag, false on
            // release); auto-measure dimension changes omit it, so layout
            // re-measurements (e.g. the agent node's expand animation) are never
            // rebroadcast. Fired here, outside setNodes, alongside the other
            // geometry broadcasts so StrictMode can't double-send.
            workflowChanges.forEach((change) => {
                if (
                    change.type === 'dimensions' &&
                    typeof (change as NodeDimensionChange).resizing ===
                        'boolean'
                ) {
                    const dims = (change as NodeDimensionChange).dimensions;
                    if (dims)
                        broadcastNodeUpdate(change.id, {
                            _dimensions: {
                                width: dims.width,
                                height: dims.height,
                            },
                        });
                }
            });

            // Check if this is a drag operation
            const isDragStart = workflowChanges.some(
                (change) =>
                    change.type === 'position' &&
                    (change as any).dragging === true
            );
            const isDragEnd = workflowChanges.some(
                (change) =>
                    change.type === 'position' &&
                    (change as any).dragging === false
            );

            // Start batching on drag start and enable global perf optimization
            if (isDragStart && !isDraggingRef.current) {
                isDraggingRef.current = true;
                if (workflowId) setGraphDragging(workflowId, true);
                canvasDivRef.current?.classList.add('perf-optimizing');
                perfState.shouldOptimize = true;
                startBatch();
            }

            setNodes((nds: Node[]) => {
                // Apply ReactFlow's changes first (only workflow nodes, not cursors)
                let updatedNodes = applyNodeChanges(workflowChanges, nds);

                // Broadcast position changes to collaborators during drag
                if (isDraggingRef.current) {
                    workflowChanges.forEach((change) => {
                        if (change.type === 'position' && change.position) {
                            broadcastNodeDrag(change.id, change.position);
                        }
                    });
                }

                // Skip z-index recalculation during drag for performance
                // Only recalculate on drag end or non-drag changes
                const isDuringDrag = isDraggingRef.current && !isDragEnd;
                if (!isDuringDrag) {
                    updatedNodes = recalculateZIndex(updatedNodes);
                }

                // On a single interactive delete, move selection to the nearest
                // node on the left (or nearest remaining) so focus isn't lost.
                // Skipped during drag/sync and for bulk removes (AI/multi-select),
                // which manage their own selection.
                const removeChanges = workflowChanges.filter(
                    (c) => c.type === 'remove'
                );
                if (
                    removeChanges.length === 1 &&
                    !isDraggingRef.current &&
                    !isSyncingRef.current
                ) {
                    const removed = nds.find(
                        (n) => n.id === (removeChanges[0] as { id: string }).id
                    );
                    // Position reads below must only see positioned real nodes:
                    // a single position-less node (or a cursor pseudo-node)
                    // throwing here aborts the WHOLE updater — the remove change
                    // never applies and the node becomes undeletable
                    // (2026-08-04 gmail-trigger incident).
                    const remaining = updatedNodes.filter(
                        (n) =>
                            n.type !== 'stickyNote' &&
                            !n.id?.startsWith('cursor-') &&
                            hasValidPosition(n)
                    );
                    if (
                        removed &&
                        hasValidPosition(removed) &&
                        removed.type !== 'stickyNote' &&
                        remaining.length > 0
                    ) {
                        const { x: rx, y: ry } = removed.position;
                        const leftward = remaining.filter(
                            (n) => n.position.x < rx
                        );
                        const pool = leftward.length > 0 ? leftward : remaining;
                        const dist = (n: Node) =>
                            Math.abs(n.position.x - rx) +
                            Math.abs(n.position.y - ry);
                        const next = pool.reduce((a, b) =>
                            dist(b) < dist(a) ? b : a
                        );
                        updatedNodes = updatedNodes.map((n) => ({
                            ...n,
                            selected: n.id === next.id,
                        }));
                        // Mouse deletes (delete pill) keep the selection move but
                        // skip the autopan — the cursor is already where the user
                        // is looking, and the camera jump reads as a distraction.
                        // Keyboard deletes (Backspace) keep the pan: focus follows
                        // the selection there.
                        if (!consumePointerDrivenDelete()) {
                            setTimeout(() => panToNode(next.id), 0);
                        }
                    }
                }

                // End batching on drag end and capture final state
                if (isDragEnd && isDraggingRef.current) {
                    isDraggingRef.current = false;
                    if (workflowId) setGraphDragging(workflowId, false);
                    canvasDivRef.current?.classList.remove('perf-optimizing');
                    perfState.shouldOptimize = false;
                    // Use setTimeout to ensure state is updated before capturing
                    setTimeout(() => {
                        endBatch(updatedNodes, edgesRef.current);
                    }, 0);
                }
                // Capture state for non-drag changes (add, remove, select, etc.)
                else if (!isDraggingRef.current && !isDragStart) {
                    // Capture after state update
                    setTimeout(() => {
                        captureState(updatedNodes, edgesRef.current);
                    }, 0);
                }

                return updatedNodes;
            });
        },
        [
            setNodes,
            recalculateZIndex,
            startBatch,
            endBatch,
            captureState,
            broadcastNodeDrag,
            broadcastNodeRemove,
            broadcastNodeUpdate,
            panToNode,
        ]
    );

    const onEdgesChange = useCallback(
        (changes: EdgeChange[]) => {
            // Broadcast edge removals to collaborators
            changes.forEach((change) => {
                if (change.type === 'remove') {
                    broadcastEdgeRemove(change.id);
                }
            });

            // Use the appropriate setter based on whether we're using Valtio or local state
            setEdges((eds: Edge[]) => {
                const updatedEdges = applyEdgeChanges(changes, eds);

                // Capture state after edge changes (using ref to avoid recreation)
                setTimeout(() => {
                    captureState(nodesRef.current, updatedEdges);
                }, 0);

                return updatedEdges;
            });
        },
        [setEdges, captureState, broadcastEdgeRemove]
    );

    // Validate connections - bottom-handle nodes (tool, alarm, mcp-server, filesystem)
    // can only connect their top handle to AgentNode's bottom handle.
    // Integration nodes with x-agent-tool-provider schemas also expose a top
    // handle for the same purpose (their operations become agent node_op tools).
    // SDK-based nodes (interface-html-react) use the SDK for communication, not edges.
    // Connections originating from the dashed "+" affordance carry a hint-handle id;
    // remap them to the underlying real source handle so validation and persisted
    // edges reference the actual handle the user is connecting from.
    const normalizeConnection = useCallback(
        (connection: Connection): Connection => {
            const real = fromHintHandleId(connection.sourceHandle);
            return real === undefined
                ? connection
                : { ...connection, sourceHandle: real };
        },
        []
    );

    const isValidConnection = useCallback(
        (rawConnection: Connection | Edge) => {
            const connection = normalizeConnection(rawConnection as Connection);
            const currentNodes = nodesRef.current;
            const sourceNode = currentNodes.find(
                (n) => n.id === connection.source
            );
            const targetNode = currentNodes.find(
                (n) => n.id === connection.target
            );

            if (!sourceNode || !targetNode) return false;

            // SDK-based nodes cannot be connected via edges
            if (
                CONNECTIONLESS_TYPES.has(sourceNode.type!) ||
                CONNECTIONLESS_TYPES.has(targetNode.type!)
            ) {
                return false;
            }

            // Reject exact duplicates of an existing connection — doubled edges
            // stack two midpoint chips and double-count dependencies.
            if (
                edgesRef.current.some(
                    (e) =>
                        e.source === connection.source &&
                        e.target === connection.target &&
                        (e.sourceHandle ?? null) ===
                            (connection.sourceHandle ?? null) &&
                        (e.targetHandle ?? null) ===
                            (connection.targetHandle ?? null)
                )
            ) {
                return false;
            }

            // Nothing flows INTO a trigger — it's an entry point. Its input handle
            // is hidden, but guard the drop anyway (handle-less drops still resolve).
            if (
                isTriggerSource(
                    targetNode.type,
                    (targetNode.data as { operation?: string } | undefined)
                        ?.operation
                )
            ) {
                return false;
            }

            // Top handles (source) can ONLY connect to a bottom handle: an
            // agent's (tools), or a hosting-mode MCP node's (the wired node's
            // operations become the hosted server's tools). A provider-wired node
            // also can't keep normal dataflow consumers: in provider mode its
            // output becomes tool metadata, which would break downstream {{refs}}
            // — so the two wiring styles are mutually exclusive.
            if (
                canFeedAgentBottom(sourceNode.type) &&
                connection.sourceHandle === 'top'
            ) {
                const intoAgent =
                    targetNode.type === 'agent' &&
                    connection.targetHandle === 'bottom';
                // Hosting an MCP node: integration providers only — no nesting
                // (mcp→mcp), no structural tool nodes (their definitions aren't
                // node_op bundles). Either-or with external mode (server_url set).
                const intoMcpHost =
                    targetNode.type === 'mcp-server' &&
                    connection.targetHandle === 'bottom' &&
                    isAgentToolProviderType(sourceNode.type) &&
                    !(
                        (
                            targetNode.data as
                                | { config?: { server_url?: string } }
                                | undefined
                        )?.config?.server_url || ''
                    ).trim();
                if (!intoAgent && !intoMcpHost) return false;
                // Either-or: a node with a trigger operation selected can't ALSO be
                // a tool provider — each role gets its own node instance (mirrors
                // workflow_ops.trigger_provider_conflict).
                if (
                    isTriggerSource(
                        sourceNode.type,
                        (sourceNode.data as { operation?: string } | undefined)
                            ?.operation
                    )
                ) {
                    return false;
                }
                return !edgesRef.current.some(
                    (e) =>
                        e.source === sourceNode.id && e.sourceHandle !== 'top'
                );
            }

            // Inverse direction of the same exclusivity: no normal dataflow output
            // from a node already wired to an agent as a tool provider.
            if (
                isAgentToolProviderType(sourceNode.type) &&
                connection.sourceHandle !== 'top' &&
                edgesRef.current.some(
                    (e) =>
                        e.source === sourceNode.id &&
                        e.sourceHandle === 'top' &&
                        e.targetHandle === 'bottom'
                )
            ) {
                return false;
            }

            // AgentNode's bottom handle can only receive top-handle connections
            // from tool-provider node types
            if (
                targetNode.type === 'agent' &&
                connection.targetHandle === 'bottom'
            ) {
                return (
                    canFeedAgentBottom(sourceNode.type) &&
                    connection.sourceHandle === 'top'
                );
            }

            // MCP node: bottom accepts only top-handle integration providers (the
            // hosting rule above); nothing else connects INTO an MCP node — its
            // left/dataflow input no longer exists.
            if (targetNode.type === 'mcp-server') {
                return false;
            }

            // All other connections are allowed
            return true;
        },
        [normalizeConnection]
    );

    const onConnect = useCallback(
        (rawParams: Connection) => {
            if (isSyncingRef.current) return;
            const params = normalizeConnection(rawParams);
            // Use the appropriate setter based on whether we're using Valtio or local state

            setEdges((eds: Edge[]) => {
                const nextEdges = addEdge(params, eds);
                const newEdge = nextEdges[nextEdges.length - 1];
                // Apply consistent edge styling using shared utility
                const styledEdge = applyEdgeStyle(newEdge);
                const finalEdges = [...nextEdges.slice(0, -1), styledEdge];

                // Broadcast new edge to collaborators
                broadcastEdgeAdd(styledEdge);

                // Capture state after connecting nodes (using ref)
                setTimeout(() => {
                    captureState(nodesRef.current, finalEdges);
                }, 0);

                return finalEdges;
            });

            // Handle state manager connections: add state to function_inputs when
            // a state manager is connected to a code node's state handle
            if (
                params.targetHandle === 'state' &&
                params.source &&
                params.target
            ) {
                const currentNodes = nodesRef.current;
                const sourceNode = currentNodes.find(
                    (n) => n.id === params.source
                );
                const targetNode = currentNodes.find(
                    (n) => n.id === params.target
                );

                if (
                    sourceNode?.type === 'state-manager' &&
                    targetNode?.type === 'automation-serverless-function'
                ) {
                    setNodes((nds: Node[]) =>
                        nds.map((node) => {
                            if (node.id !== params.target) return node;

                            const nodeData = node.data || {};
                            const nodeConfig =
                                (nodeData.config as Record<string, unknown>) ||
                                {};
                            const currentInputs = Array.isArray(
                                nodeConfig.function_inputs
                            )
                                ? (nodeConfig.function_inputs as Array<{
                                      name: string;
                                      value: string;
                                  }>)
                                : [];

                            // Filter out any existing 'state' entries (may be stale from old connections)
                            const filteredInputs = currentInputs.filter(
                                (input: { name: string }) =>
                                    input.name !== 'state'
                            );
                            const stateInput = {
                                name: 'state',
                                value: `{{${params.source}.state}}`,
                            };

                            return {
                                ...node,
                                data: {
                                    ...nodeData,
                                    config: {
                                        ...nodeConfig,
                                        function_inputs: [
                                            ...filteredInputs,
                                            stateInput,
                                        ],
                                    },
                                },
                            };
                        })
                    );
                }
            }
        },
        [
            setNodes,
            setEdges,
            captureState,
            broadcastEdgeAdd,
            normalizeConnection,
        ]
    );

    // Drop-forgiveness: releasing a connection drag over a node's BODY (or on an
    // invalid handle) resolves the appropriate opposite handle via
    // resolveBodyDropConnection and completes the connection, so drops don't
    // have to land exactly on the small handle dot. Valid handle drops already
    // connected through onConnect (connectionState.isValid === true).
    const onConnectEndSnap = useCallback(
        (
            event: MouseEvent | TouchEvent,
            connectionState: FinalConnectionState
        ) => {
            if (isReplayMode || isSyncingRef.current) return;
            if (connectionState.isValid) return;
            const { fromNode, fromHandle } = connectionState;
            if (!fromNode || !fromHandle) return;

            const { clientX, clientY } =
                'changedTouches' in event ? event.changedTouches[0] : event;
            // mouseup targets the element under the pointer (z-order included);
            // touchend targets the drag ORIGIN, so hit-test the point instead.
            const el =
                'changedTouches' in event
                    ? document.elementFromPoint(clientX, clientY)
                    : (event.target as Element | null);
            const dropNodeId = el
                ?.closest('.react-flow__node')
                ?.getAttribute('data-id');
            if (!dropNodeId || dropNodeId === fromNode.id) return;

            const internal = getInternalNode(dropNodeId);
            const handleBounds = internal?.internals.handleBounds;
            const rawCandidates =
                (fromHandle.type === 'source'
                    ? handleBounds?.target
                    : handleBounds?.source) ?? [];
            if (!internal || rawCandidates.length === 0) return;

            const origin = internal.internals.positionAbsolute;
            const realFromId = fromHintHandleId(fromHandle.id);
            const connection = resolveBodyDropConnection({
                fromNodeId: fromNode.id,
                fromNodeType: fromNode.type,
                fromHandleId:
                    realFromId === undefined
                        ? (fromHandle.id ?? null)
                        : realFromId,
                fromHandleType: fromHandle.type,
                dropNodeId,
                dropPoint: screenToFlowPosition({ x: clientX, y: clientY }),
                candidates: rawCandidates.map((h) => ({
                    id: h.id ?? null,
                    x: origin.x + h.x + h.width / 2,
                    y: origin.y + h.y + h.height / 2,
                })),
                isValidConnection,
            });
            if (connection) onConnect(connection);
        },
        [
            isReplayMode,
            getInternalNode,
            screenToFlowPosition,
            isValidConnection,
            onConnect,
        ]
    );

    // Tracks which node the config view describes. Opening it is onNodeClick's
    // job: xyflow selects a node ~1px into a DRAG, and selection also moves
    // programmatically (arrow traversal, post-delete reselect, sequence-add),
    // none of which are a request to open the config.
    // Skip sticky notes - they have their own inline editing UI.
    const onSelectionChange = useCallback(
        ({ nodes: selectedNodes }: { nodes: Node[] }) => {
            const nonStickyNodes = selectedNodes.filter(
                (n) => n.type !== 'stickyNote'
            );
            setSelectedNode(
                nonStickyNodes.length > 0 ? nonStickyNodes[0] : null
            );
            // Broadcast selection to collaborators
            updateLocalSelection(nonStickyNodes.map((n) => n.id));
        },
        [setSelectedNode, updateLocalSelection]
    );

    // A real click on a node opens the config view. Deliberately not driven off
    // onSelectionChange: a drag selects the node too, which popped the panel
    // open mid-drag. d3-drag suppresses the click after ANY pointer movement
    // (xyflow's nodeClickDistance defaults to 0), so this fires on clicks only.
    const onNodeClick = useCallback(
        (_event: React.MouseEvent, node: Node) => {
            if (node.type === 'stickyNote') return;
            setIsConfigViewExpanded(true);
            // Click = edit intent: let the operation picker focus on open
            // (arrow traversal suppresses it).
            setAutoFocusPickerOnOpen(true);
            // Preserve a manually collapsed tab strip (null).
            const currentTab =
                displayMetadataRef.current.flowHelperView.activeTab;
            if (currentTab !== null) {
                setFlowHelperActiveTab('config');
            }
        },
        [setIsConfigViewExpanded, setFlowHelperActiveTab]
    );

    // Double-click on a node opens FlowHelperView in full screen mode
    // Skip sticky notes - double-click activates their edit mode instead
    const onNodeDoubleClick = useCallback(
        (_event: React.MouseEvent, node: Node) => {
            if (node.type === 'stickyNote') {
                return; // Sticky notes handle double-click internally for edit mode
            }
            setSelectedNode(node);
            setIsConfigViewExpanded(true);
            setFlowHelperActiveTab('config');
            setIsFlowHelperFullScreen(true);
        },
        [
            setSelectedNode,
            setIsConfigViewExpanded,
            setFlowHelperActiveTab,
            setIsFlowHelperFullScreen,
        ]
    );

    // ── Replay-aware canvas handlers ───────────────────────────────────────
    // In replay mode the displayed graph IS the replay snapshot; xyflow change
    // events route to replay-local state (select + dimensions only) and every
    // mutation pathway is no-op'd so live nodes/edges stay frozen.
    const onNodesChangeForCanvas = useCallback(
        (changes: NodeChange[]) => {
            if (isReplayMode) {
                const allowed = changes.filter(
                    (c) => c.type === 'select' || c.type === 'dimensions'
                );
                if (allowed.length) {
                    setReplayNodes(
                        (nds) => applyNodeChanges(allowed, nds) as Node[]
                    );
                }
                return;
            }
            onNodesChange(changes);
        },
        [isReplayMode, onNodesChange]
    );

    const onEdgesChangeForCanvas = useCallback(
        (changes: EdgeChange[]) => {
            if (isReplayMode) return;
            onEdgesChange(changes);
        },
        [isReplayMode, onEdgesChange]
    );

    const onConnectForCanvas = useCallback(
        (params: Connection) => {
            if (isReplayMode) return;
            onConnect(params);
        },
        [isReplayMode, onConnect]
    );

    // Memoized style objects to prevent re-renders
    const connectionLineStyle = useMemo(
        () => ({
            // Match the rendered edge color (soft gray in light, white in dark);
            // --foreground made the drag line near-black on the light canvas.
            stroke: 'hsl(var(--canvas-edge))',
            strokeWidth: 3,
            opacity: 0.8,
            strokeDasharray: '5 5',
        }),
        []
    );

    const fitViewOptions = useMemo(
        () => ({
            padding: 0.2,
        }),
        []
    );

    const reactFlowStyle = useMemo(
        () => ({
            width: '100%',
            height: '100%',
        }),
        []
    );

    // Frozen-during-drag cache: only positions change while dragging, so config/credential/schema
    // computations don't need to re-run on every drag event.
    const hasInterfaceBlocksCacheRef = useRef(false);

    const hasInterfaceBlocks = useMemo(() => {
        if (isDraggingRef.current) return hasInterfaceBlocksCacheRef.current;
        const result = nodes.some((n) => {
            if (n.type?.startsWith('interface-')) return true;
            // Agents count as interface blocks unless show_in_interface is turned off.
            if (n.type === 'agent') {
                const cfg = (
                    n.data as { config?: Record<string, unknown> } | undefined
                )?.config;
                return agentShowsInInterface(cfg?.show_in_interface);
            }
            return false;
        });
        hasInterfaceBlocksCacheRef.current = result;
        return result;
    }, [nodes]);

    const hasNonCursorNodes = useMemo(
        () => nodes.some((n) => !n.id?.startsWith('cursor-')),
        [nodes]
    );

    // Leaving the Setup tab is driven by explicit user action — the wizard's
    // "Continue to Workflow" button (or its `setup:complete` socket event for
    // interactive setup) fires onContinue, which switches the tab. No
    // automatic bounce on count change: it used to fire the moment the user
    // typed a character that passed validation, yanking them out mid-edit.

    // Post-onboarding: OnboardingQuestionnaire stores the user's build_type answer
    // ('canvas' or 'interface') under 'noclick_post_onboarding_tab' before auto-creating
    // this blank workflow. Consume once on mount so the empty-state overlay opens on the
    // chosen tab instead of the default 'canvas'.
    const postOnboardingTabConsumedRef = useRef(false);
    useEffect(() => {
        if (postOnboardingTabConsumedRef.current) return;
        postOnboardingTabConsumedRef.current = true;
        const tab = sessionStorage.getItem('noclick_post_onboarding_tab');
        if (tab === 'interface' || tab === 'canvas') {
            sessionStorage.removeItem('noclick_post_onboarding_tab');
            setActiveTab(tab);
        }
    }, [setActiveTab]);

    // On clone/fork and the /agents scaffold handoff, the upstream flow sets
    // 'noclick_open_setup_tab' in sessionStorage before navigating. Consume it
    // once nodes hydrate — the Setup tab is permanent and state-derived, so
    // there is no node-presence gate anymore. Template forks additionally set
    // 'noclick_setup_fullscreen': the published-agent onboarding takes the
    // WHOLE viewport (no workspace chrome) until the user exits or runs the
    // test — the same presentation the setup was designed in.
    useEffect(() => {
        if (nodes.length === 0 || hasSetInitialTabRef.current) return;
        hasSetInitialTabRef.current = true;
        const flag = sessionStorage.getItem('noclick_open_setup_tab');
        if (flag === 'true') {
            sessionStorage.removeItem('noclick_open_setup_tab');
            setActiveTab('setup');
            if (sessionStorage.getItem('noclick_setup_fullscreen') === 'true') {
                sessionStorage.removeItem('noclick_setup_fullscreen');
                setSetupFullscreen(true);
            }
            // Tell the hand-off cover its job is done. An EVENT, not flag
            // polling: a 3-node graph consumes the flag between two polls,
            // and a cover that never observes the relay's middle state sat
            // beneath the onboarding until its fail-open timeout - resurfacing
            // the moment the user left full screen.
            document.dispatchEvent(new CustomEvent('noclick:setup-handoff-done'));
        }
    }, [nodes.length, setActiveTab]);

    // Bare agent scaffolds (from /agents) carry a guiding prompt the AI builder
    // should run once the graph opens — walking the user through choosing the
    // trigger + tool operations. The hero-prompt hand-off only fires for an EMPTY
    // canvas (FlowCanvasEmptyState never mounts when a scaffold has nodes), so we
    // consume it here once the nodes hydrate, reusing the same sidebar-expand +
    // builder-submit dispatch (NoClick mints the conversation + gates credits).
    // Wait for EDGES too: firing before they hydrate would hand the builder a
    // graph with the provider/trigger nodes but no wiring, so it re-adds the
    // edges (double-edge "almost solid" artifact) and misreads the tool setup.
    const scaffoldGuideSentRef = useRef(false);
    useEffect(() => {
        scaffoldGuideSentRef.current = false;
    }, [workflowId]);
    useEffect(() => {
        if (
            nodes.length === 0 ||
            edges.length === 0 ||
            scaffoldGuideSentRef.current ||
            typeof window === 'undefined'
        )
            return;
        // Keyed by workflow id (see WorkflowBrowser's scaffold consumer) so the
        // prompt can only fire into the workflow it was scaffolded for.
        const promptKey = `noclick_scaffold_builder_prompt:${workflowId}`;
        const prompt = sessionStorage.getItem(promptKey);
        if (!prompt) return;
        scaffoldGuideSentRef.current = true;
        sessionStorage.removeItem(promptKey);
        document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
        document.dispatchEvent(
            new CustomEvent('noclick:builder:submit', { detail: { prompt } })
        );
    }, [nodes.length, edges.length, workflowId]);

    // Handlers the Setup tab's step panes write through
    const handleGuidedSetupConfigChange = useCallback(
        (nodeId: string, config: Record<string, any>) => {
            setNodes((current) =>
                updateNodeInList(current, nodeId, { config })
            );
        },
        [setNodes]
    );

    const handleGuidedSetupOperationChange = useCallback(
        (nodeId: string, operation: string) => {
            setNodes((current) =>
                updateNodeInList(current, nodeId, { operation })
            );
        },
        [setNodes]
    );


    const handleGuidedSetupCredentialIdsChange = useCallback(
        (nodeId: string, credentialIds: Record<string, string>) => {
            setNodes((current) =>
                updateNodeInList(current, nodeId, { credentialIds })
            );
            authorizeCredentialsForWorkflow(workflowId, credentialIds);
        },
        [setNodes, workflowId]
    );

    // Handle node data update from config editor
    const handleNodeDataUpdate = useCallback(
        (nodeId: string, newData: Record<string, any>) => {
            const update = normalizeNodeUpdatePayload(newData);
            setNodes((currentNodes) => {
                const updatedNodes = currentNodes.map((n) => {
                    if (n.id !== nodeId) return n;
                    const updated = applyNodeUpdate(n, update);

                    // For state-manager nodes: update output preview when state changes.
                    // Route output through extras so it lands at data.output per the
                    // TOP_LEVEL_FIELDS registry (persist:false, restore:true) — keeps
                    // this on the same code path as real execution outputs.
                    if (
                        n.type === 'state-manager' &&
                        update.config &&
                        'state' in update.config
                    ) {
                        return applyNodeUpdate(updated, {
                            extras: {
                                output: {
                                    type: 'state_manager',
                                    status: 'preview',
                                    state: update.config.state || {},
                                },
                            },
                        });
                    }
                    return updated;
                });

                // Capture state after node data update
                setTimeout(() => {
                    captureState(updatedNodes, edgesRef.current);
                }, 0);

                return updatedNodes;
            });

            // For switch nodes: clean up edges whose sourceHandle no longer matches a valid case,
            // then force ReactFlow to recalculate edge paths for the resized node
            if (newData.config && 'switch_cases' in newData.config) {
                // 'default' is the always-present fallback handle (see SwitchNode), so
                // edges off it must survive case edits.
                const validHandles = new Set<string>([
                    'default',
                    ...(Array.isArray(newData.config.switch_cases)
                        ? newData.config.switch_cases
                        : []
                    )
                        .map((c: { value: string }) => c.value)
                        .filter(Boolean),
                ]);
                setEdges((currentEdges) =>
                    currentEdges.filter(
                        (e) =>
                            e.source !== nodeId ||
                            !e.sourceHandle ||
                            validHandles.has(e.sourceHandle)
                    )
                );
                // Update after edges and node DOM have settled
                setTimeout(() => updateNodeInternals(nodeId), 150);
            }

            // Broadcast node update to collaborators
            broadcastNodeUpdate(nodeId, newData);
        },
        [
            setNodes,
            captureState,
            broadcastNodeUpdate,
            setEdges,
            updateNodeInternals,
        ]
    );

    // Keep ref updated so event listener can access latest callback
    handleNodeDataUpdateRef.current = handleNodeDataUpdate;

    // Right-click context menu (pane / node / multi-selection). The hook owns
    // state, the 3 handlers, action helpers, and the menu element — FlowCanvas
    // just wires the 3 props on ReactFlow and renders `contextMenuElement`.
    const {
        handlePaneContextMenu,
        handleNodeContextMenu,
        handleSelectionContextMenu,
        element: contextMenuElement,
    } = useCanvasContextMenu({
        nodesRef,
        setNodes,
        setEdges,
        deletedNodeIdsRef,
        workflowInterfaceRef,
        broadcastNodeAdd,
        broadcastNodeRemove,
        workflowId,
        logActivity,
        screenToFlowPosition,
        fitView,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        bumpSearchFocus,
        openNodeConfigExpanded,
        runFromNode,
        handleNodeDataUpdate,
        handleAutolayout,
        copySelection,
        pasteFromClipboard,
    });

    // Insert an iteration node between `sourceId` and `targetId`: point its
    // `items` at the source array (arrayPath '' = the output itself), make the
    // target the loop body, and rewrite the target's same-source refs ([] and
    // plain) to the iteration's per-item form. Driven by the under-field "Loop
    // over each item" button.
    const injectIterationBetween = useCallback(
        (sourceId: string, arrayPath: string, targetId: string) => {
            const targetNode = nodesRef.current.find((n) => n.id === targetId);
            if (!targetNode) return;
            const cfg = (targetNode.data?.config ?? {}) as Record<string, any>;

            const iterationId = generateNodeId('iteration');
            const sourceNode = nodesRef.current.find((n) => n.id === sourceId);
            // Drop the iteration node between source and target; layout can refine it.
            const position = sourceNode
                ? {
                      x: (sourceNode.position.x + targetNode.position.x) / 2,
                      y: targetNode.position.y,
                  }
                : { x: targetNode.position.x - 220, y: targetNode.position.y };

            // Smartly seed the iteration node with a clipped one-item preview built
            // from the source node's (live or mocked) output array, so its panel can
            // immediately offer draggable {{iter.item.*}} fields — no run required.
            // Stored in `previewOutput` (persisted, display-only) so it survives the
            // workflow sync; a real run's `output` takes precedence in the panel.
            const sourceOutput =
                sourceNode?.data?.output ??
                sourceNode?.data?.mockedOutput ??
                sourceNode?.data?.previewOutput;
            const sourceArray = getValueAtPath(sourceOutput, arrayPath);
            const iterationExtras =
                Array.isArray(sourceArray) && sourceArray.length > 0
                    ? {
                          previewOutput: {
                              isIterationNode: true,
                              item: clipSampleItem(sourceArray[0]),
                              index: 0,
                              row_number: 1,
                              total: sourceArray.length,
                          },
                      }
                    : {};

            const itemsRef = `{{${sourceId}${arrayPath ? '.' + arrayPath : ''}}}`;
            const iterationNode = createWorkflowNode(
                iterationId,
                'iteration',
                position,
                {
                    config: {
                        items: itemsRef,
                        header_row: 'false',
                        concurrency: 1,
                    },
                },
                iterationExtras
            );

            // Rewrite every same-source ref ([] and plain) across the target's fields.
            const newConfig: Record<string, any> = {};
            for (const [k, v] of Object.entries(cfg)) {
                newConfig[k] =
                    typeof v === 'string'
                        ? rewriteListRefsForIteration(
                              v,
                              sourceId,
                              arrayPath,
                              iterationId
                          )
                        : v;
            }

            setNodes((prev) =>
                updateNodeInList(
                    appendIfUnique(prev, iterationNode),
                    targetId,
                    { config: newConfig }
                )
            );

            // Source feeds the iteration node; the iteration's loop body is the target.
            // Drop any direct source -> target edge (the data now flows through the loop).
            const sourceToIter = applyEdgeStyle({
                id: `xy-edge__${sourceId}-${iterationId}`,
                source: sourceId,
                target: iterationId,
            } as Edge);
            const iterToTarget = applyEdgeStyle({
                id: `xy-edge__${iterationId}loop-${targetId}`,
                source: iterationId,
                target: targetId,
                sourceHandle: 'loop',
            } as Edge);
            const removedEdgeIds: string[] = [];
            setEdges((prev) => {
                const kept = prev.filter((e) => {
                    const drop = e.source === sourceId && e.target === targetId;
                    if (drop) removedEdgeIds.push(e.id);
                    return !drop;
                });
                return appendIfUnique(
                    appendIfUnique(kept, sourceToIter),
                    iterToTarget
                );
            });

            // Mirror to collaborators + snapshot for undo.
            broadcastNodeAdd(iterationNode);
            broadcastNodeUpdate(targetId, { config: newConfig });
            removedEdgeIds.forEach((id) => broadcastEdgeRemove(id));
            broadcastEdgeAdd(sourceToIter);
            broadcastEdgeAdd(iterToTarget);
            setTimeout(
                () => captureState(nodesRef.current, edgesRef.current),
                0
            );
        },
        [
            setNodes,
            setEdges,
            captureState,
            broadcastNodeAdd,
            broadcastNodeUpdate,
            broadcastEdgeAdd,
            broadcastEdgeRemove,
        ]
    );

    // Field-button entry: resolve the field's `[]` list ref OR plain array ref
    // ({{node.items}}) to (source, arrayPath), then inject the loop.
    const handleInjectIteration = useCallback(
        (nodeId: string, fieldKey: string) => {
            const targetNode = nodesRef.current.find((n) => n.id === nodeId);
            const raw = (
                targetNode?.data?.config as Record<string, any> | undefined
            )?.[fieldKey];
            if (typeof raw !== 'string') return;
            const listRef = parseListReference(raw);
            if (listRef) {
                injectIterationBetween(
                    listRef.nodeId,
                    listRef.arrayPath,
                    nodeId
                );
                return;
            }
            const whole = parseWholeReference(raw);
            // Loop the OUTERMOST array: the path up to its first literal index
            // ({{x.values[8][1]}} -> iterate `values`). rewriteListRefsForIteration
            // then turns the literal index into the per-item accessor.
            if (whole)
                injectIterationBetween(
                    whole.nodeId,
                    splitAtFirstIndex(whole.arrayPath).prefix,
                    nodeId
                );
        },
        [injectIterationBetween]
    );

    // Keyboard shortcuts for workflow operations (d=disable, m/p=mock)
    useWorkflowKeyboardShortcuts({
        nodes,
        activeTab,
        onNodeDataUpdate: handleNodeDataUpdate,
        onToggleFlowHelper: () => {
            const next = !isConfigViewExpanded;
            if (next) setFlowHelperNoAnim(true);
            setIsConfigViewExpanded(next);
        },
        onOpenFlowHelperTab: (tab) => {
            setFlowHelperNoAnim(true);
            setIsConfigViewExpanded(true);
            setFlowHelperActiveTab(tab);
        },
    });

    // Register with test harness for SDK bridge node access (all envs) and debugging (dev only).
    // Uses nodesRef to avoid re-registering on every node change (positions change during drag).
    // The SDK bridge reads nodes via __workflowTest.getNodes() which persists across tab switches,
    // unlike __reactFlowInstance which returns empty when the canvas tab is inactive.
    // (so this is not only for test - it's used by SDK and removing it will break reading node outputs)
    useEffect(() => {
        workflowTestHarness.registerFlowCanvas({
            workflowId: workflowId || null,
            get nodes() {
                return nodesRef.current;
            },
            get edges() {
                return edgesRef.current;
            },
            getNodeOutput: (nodeId: string) => {
                const node = nodesRef.current.find((n) => n.id === nodeId);
                if (!node?.data?.output) return undefined;
                return {
                    output: node.data.output,
                    outputTimestamp:
                        (node.data as any).outputTimestamp ?? Date.now(),
                };
            },
            setNodes: setNodes,
            setEdges: setEdges,
            activeExecutionsRef,
        });

        // Socket sender only needed for dev debugging (replay, test execution)
        if (process.env.NODE_ENV === 'development') {
            workflowTestHarness.registerSocketSender({ sendEventAsync });
        }

        return () => {
            workflowTestHarness.unregisterFlowCanvas();
        };
    }, [workflowId, setNodes, setEdges]);

    return (
        <div className="w-full h-full relative flex flex-col bg-background text-foreground overflow-hidden">
            <CanvasTopBar
                workflowTitle={workflowTitle}
                workflowId={workflowId}
                isRealWorkflow={isRealWorkflow}
                nodes={nodes}
                edges={edges}
                onTitleChange={onTitleChange}
                onBack={onBack}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                onConfigViewExpandedChange={setIsConfigViewExpanded}
                onFlowHelperTabChange={setFlowHelperActiveTab}
                resourceCount={resourceCount}
                isMobile={isMobile}
                collaborators={collaborators}
                fileInputRef={fileInputRef}
                onImportWorkflow={handleImportWorkflow}
                onFileChange={handleFileChange}
                onExportWorkflow={handleExportWorkflow}
                onAutolayout={handleAutolayout}
                onDeleteWorkflow={handleDeleteWorkflow}
                onShareDialogOpen={() => setIsShareDialogOpen(true)}
                onSettingsDialogOpen={() => {
                    setSettingsInitialSection('general');
                    setIsSettingsDialogOpen(true);
                }}
                onCheckpointRestore={handleCheckpointRestore}
                isWorkflowRunning={isWorkflowRunning}
                activeExecutions={activeExecutions}
                onRun={requestRunWorkflow}
                onStop={stopWorkflow}
                onHoveredExecutionChange={setHoveredExecutionId}
            />

            {isMobile && activeTab === 'canvas' && (
                <MobileRunPill
                    isWorkflowRunning={isWorkflowRunning}
                    activeExecutionCount={activeExecutions.size}
                    onRun={requestRunWorkflow}
                    onStop={() => stopWorkflow()}
                />
            )}

            {isMobile && activeTab === 'canvas' && resourceCount > 0 && (
                <MobileResourcesPill
                    onClick={() => setActiveTab('resources')}
                />
            )}

            {isMobile &&
                activeTab === 'canvas' &&
                !isFlowHelperFullScreen &&
                workflowId && (
                    <MobileBuilderStatusPill
                        workflowId={workflowId}
                        onOpenChat={() =>
                            document.dispatchEvent(
                                new CustomEvent('noclick:mobile:set-view', {
                                    detail: { view: 'chat' },
                                })
                            )
                        }
                    />
                )}

            {/* Content Area — wrapped so the shared empty-state overlay below stays
                mounted across canvas↔interface tab switches (only the inner chips animate).
                WorkflowProvider is hoisted here (instead of per-branch) so flipping tabs
                doesn't unmount it — its unmount cleanup clears the editor id, which the
                sidebar conversation reducer keys off and would otherwise reset. */}
            <div className="relative flex-1 min-h-0 flex flex-col">
                <WorkflowProvider
                    workflowId={workflowId}
                    workflowName={workflowTitle}
                >
                    {activeTab === 'setup' ? (
                        ((pane) =>
                            // PORTALED to body when fullscreen: the workspace
                            // content div is a z-0 stacking context, so an
                            // inner z-40 could never cover the SIBLING chat
                            // sidebar - portaling escapes the context (React
                            // context still flows to portal children).
                            setupFullscreen && typeof document !== 'undefined'
                                ? createPortal(pane, document.body)
                                : pane)(
                        <div
                            className={cn(
                                'flex flex-col bg-sunken',
                                setupFullscreen
                                    ? 'fixed inset-0 z-40'
                                    : 'flex-1 relative min-h-0'
                            )}
                        >
                            {setupFullscreen && (
                                <button
                                    onClick={() => setSetupFullscreen(false)}
                                    title="Exit full screen — open the workspace"
                                    aria-label="Exit full screen"
                                    className="absolute right-4 top-4 z-10 flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background/80 text-foreground/50 backdrop-blur transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                >
                                    <X className="h-4 w-4" />
                                </button>
                            )}
                            <WorkflowSetupView
                                nodes={nodes}
                                edges={edges}
                                onOperationChange={
                                    handleGuidedSetupOperationChange
                                }
                                onConfigChange={handleGuidedSetupConfigChange}
                                onCredentialIdsChange={
                                    handleGuidedSetupCredentialIdsChange
                                }
                                onOpenTestRun={() => {
                                    // Test Run leaves the onboarding: land on
                                    // the interface testing page in the normal
                                    // workspace, never inside the overlay.
                                    // Un-hiding may be what CREATES the
                                    // interface surface, so decide the tab
                                    // from its result, not the stale memo.
                                    const agentVisible =
                                        ensureAgentChatVisible();
                                    setSetupFullscreen(false);
                                    setActiveTab(
                                        agentVisible || hasInterfaceBlocks
                                            ? 'interface'
                                            : 'canvas'
                                    );
                                }}
                                workflowId={workflowId}
                                variableDefinitions={variableDefinitions}
                                onVariableDefinitionsChange={
                                    handleVariableDefinitionsChange
                                }
                            />
                        </div>
                        )
                    ) : activeTab === 'canvas' ? (
                        <div className="flex-1 relative min-h-0 flex flex-col">
                            {/* Execution replay banner — sits in-flow above the canvas; the
                        canvas itself renders the replay snapshot via isReplayMode
                        (same FlowCanvas / FlowHelperView / shortcuts as live). */}
                            {isReplayMode && (
                                <div className="relative flex shrink-0 items-center justify-between gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 z-20">
                                    <div className="flex min-w-0 items-center gap-2 text-sm text-amber-700 dark:text-amber-200">
                                        <History className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                                        <span className="font-medium">
                                            Viewing execution run
                                        </span>
                                        <span className="truncate text-amber-600/80 dark:text-amber-400/80">
                                            {replay!.log.timestamp.toLocaleString()}{' '}
                                            · {replay!.log.trigger ?? 'manual'}
                                        </span>
                                        <span className="hidden shrink-0 text-amber-600/70 dark:text-amber-500/70 sm:inline">
                                            (read-only)
                                        </span>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                        {replay!.toolCalls.length > 0 && (
                                            <button
                                                onClick={() =>
                                                    setShowReplayToolCalls(
                                                        (s) => !s
                                                    )
                                                }
                                                className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors ${
                                                    showReplayToolCalls
                                                        ? 'bg-amber-500/30 text-amber-800 dark:text-amber-100'
                                                        : 'bg-amber-500/20 text-amber-700 dark:text-amber-200 hover:bg-amber-500/30'
                                                }`}
                                            >
                                                <Wrench className="h-3.5 w-3.5" />
                                                {replay!.toolCalls.length} tool
                                                call
                                                {replay!.toolCalls.length === 1
                                                    ? ''
                                                    : 's'}
                                            </button>
                                        )}
                                        <button
                                            onClick={closeExecutionReplay}
                                            className="flex shrink-0 items-center gap-1.5 rounded-md bg-amber-500/20 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-200 transition-colors hover:bg-amber-500/30"
                                        >
                                            <X className="h-3.5 w-3.5" /> Exit
                                            replay
                                        </button>
                                    </div>
                                    {showReplayToolCalls && (
                                        <div className="absolute right-4 top-full z-30 mt-1">
                                            <ReplayToolCallsPanel
                                                toolCalls={replay!.toolCalls}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}
                            <div className="relative min-h-0 flex-1">
                                {/* (Lazy output fetch in replay: handleReplayNodeSelect is
                            wired via a useEffect on selectedNode.id earlier.) */}
                                {workflowLoadError && (
                                    <div className="absolute inset-0 z-20 flex items-center justify-center bg-background">
                                        <div className="flex flex-col items-center gap-3 text-center max-w-sm px-6">
                                            <div className="text-muted-foreground text-sm">
                                                {workflowLoadError}
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div
                                    ref={(el) => {
                                        setNodeRef(el);
                                        canvasDivRef.current = el;
                                    }}
                                    data-testid="flow-canvas"
                                    className={`absolute inset-0 bg-[hsl(var(--canvas-bg))] select-none ${canvasEditState.isEditing ? 'workflow-animating' : ''}`}
                                    onMouseDown={() => {
                                        // Clear any text selection when clicking on canvas
                                        // This prevents shift-drag from extending text selection from other areas
                                        window
                                            .getSelection()
                                            ?.removeAllRanges();
                                    }}
                                >
                                    <FormSubmitContext.Provider
                                        value={handleFormSubmit}
                                    >
                                            <HoverExecutionGlow
                                                hoveredExecutionId={
                                                    hoveredExecutionId
                                                }
                                                activeExecutions={
                                                    activeExecutions
                                                }
                                            />
                                            <CollaborativeProvider
                                                nodeSelections={nodeSelections}
                                                collaborators={collaborators}
                                            >
                                                {useForkCanvas ? (
                                                    // Temporary feature-flag swap: ?canvas=fork renders the
                                                    // xyflow-free ForkCanvas with the same nodes/edges state.
                                                    // Used to verify AI edits (add/update/remove via Valtio)
                                                    // propagate through correctly. Drag fires onNodesChange in
                                                    // the same shape ReactFlow uses, so the existing reducer
                                                    // works unchanged.
                                                    <ForkCanvas
                                                        ref={forkCanvasRef}
                                                        nodes={nodes}
                                                        edges={edges}
                                                        nodeDefs={forkNodeDefs}
                                                        onNodesChange={
                                                            onNodesChange
                                                        }
                                                        editingNodeIds={
                                                            canvasEditState.affectedNodeIds
                                                        }
                                                        isEditing={
                                                            canvasEditState.isEditing
                                                        }
                                                        minZoom={0.05}
                                                        maxZoom={2.5}
                                                        defaultViewport={
                                                            safeViewport
                                                                ? {
                                                                      x: safeViewport.x,
                                                                      y: safeViewport.y,
                                                                      zoom: safeViewport.zoom,
                                                                  }
                                                                : undefined
                                                        }
                                                        fitView
                                                        style={reactFlowStyle}
                                                        workflowId={workflowId}
                                                    >
                                                        {/* Mobile syncing pill — mirrors the FlowHelperView
                                                            "Syncing" indicator, but standalone since
                                                            FlowHelperView itself is desktop-only. Auto-removes
                                                            when isSyncing flips false (workflow:get resolved). */}
                                                        {isSyncing && (
                                                            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 pointer-events-none flex items-center gap-2 px-3 py-1.5 rounded-full bg-card/95 backdrop-blur-sm border border-border dark:border-white/[0.08] shadow-sm">
                                                                <Loader2 className="h-3.5 w-3.5 text-muted-foreground animate-spin" />
                                                                <span className="text-xs font-medium text-muted-foreground">
                                                                    Syncing
                                                                </span>
                                                            </div>
                                                        )}
                                                    </ForkCanvas>
                                                ) : (
                                                    <ReactFlowComponent
                                                        nodes={
                                                            isReplayMode
                                                                ? replayNodes
                                                                : nodes
                                                        }
                                                        edges={
                                                            isReplayMode
                                                                ? replayEdges
                                                                : edges
                                                        }
                                                        onNodesChange={
                                                            onNodesChangeForCanvas
                                                        }
                                                        onEdgesChange={
                                                            onEdgesChangeForCanvas
                                                        }
                                                        onConnect={
                                                            onConnectForCanvas
                                                        }
                                                        onConnectEnd={
                                                            onConnectEndSnap
                                                        }
                                                        // Handle-snap radius for in-progress drags
                                                        // (default 20): drops just outside a node
                                                        // still snap to the nearest valid handle.
                                                        connectionRadius={30}
                                                        isValidConnection={
                                                            isValidConnection
                                                        }
                                                        onSelectionChange={
                                                            onSelectionChange
                                                        }
                                                        onNodeClick={
                                                            onNodeClick
                                                        }
                                                        onNodeDoubleClick={
                                                            onNodeDoubleClick
                                                        }
                                                        nodesDraggable={
                                                            !isReplayMode
                                                        }
                                                        nodesConnectable={
                                                            !isReplayMode
                                                        }
                                                        deleteKeyCode={
                                                            isReplayMode
                                                                ? null
                                                                : undefined
                                                        }
                                                        elevateNodesOnSelect={
                                                            false
                                                        }
                                                        onlyRenderVisibleElements={
                                                            false
                                                        }
                                                        onInit={onInit}
                                                        onMoveStart={
                                                            handleMoveStartForAutoFit
                                                        }
                                                        onMoveEnd={
                                                            handleMoveEnd
                                                        }
                                                        onMouseMove={
                                                            handleCanvasMouseMove
                                                        }
                                                        onMouseLeave={
                                                            handleCanvasMouseLeave
                                                        }
                                                        onNodeDragStart={
                                                            handleNodeDragStart
                                                        }
                                                        onNodeDrag={
                                                            handleNodeDrag
                                                        }
                                                        onNodeDragStop={
                                                            handleNodeDragStop
                                                        }
                                                        onPaneClick={
                                                            closeFlowHelperOnDeselect
                                                        }
                                                        onPaneContextMenu={
                                                            handlePaneContextMenu
                                                        }
                                                        onNodeContextMenu={
                                                            handleNodeContextMenu
                                                        }
                                                        onSelectionContextMenu={
                                                            handleSelectionContextMenu
                                                        }
                                                        connectionLineStyle={
                                                            connectionLineStyle
                                                        }
                                                        connectionLineComponent={
                                                            CustomConnectionLine
                                                        }
                                                        nodeTypes={nodeTypes}
                                                        edgeTypes={edgeTypes}
                                                        proOptions={proOptions}
                                                        minZoom={0.05}
                                                        maxZoom={2.5}
                                                        defaultViewport={
                                                            safeViewport
                                                        }
                                                        fitView={false}
                                                        fitViewOptions={
                                                            fitViewOptions
                                                        }
                                                        style={reactFlowStyle}
                                                        // Figma-style navigation: trackpad scroll pans,
                                                        // pinch zooms, left-drag selects, middle-drag or
                                                        // Cmd/Ctrl+drag pans. macOS uses panActivationKeyCode
                                                        // natively; Windows/Linux uses a pointer-capture layer
                                                        // (d3-zoom blocks event.ctrlKey on mousedown).
                                                        panOnDrag={[1]}
                                                        panOnScroll
                                                        panOnScrollSpeed={1}
                                                        zoomOnScroll={false}
                                                        selectionOnDrag
                                                        panActivationKeyCode={
                                                            panActivationKeyCode
                                                        }
                                                    >
                                                        <CanvasBackground />
                                                        {/* Collaborative cursors overlay - renders above all nodes */}
                                                        <CollaborativeCursors
                                                            collaborators={
                                                                collaborators
                                                            }
                                                        />
                                                    </ReactFlowComponent>
                                                )}
                                                {/* Right-click context menu — pane, node, and multi-selection
                                    variants. All state + items + actions live in the hook. */}
                                                {contextMenuElement}
                                            </CollaborativeProvider>
                                    </FormSubmitContext.Provider>
                                </div>

                                {/* Floating expand button - hidden on mobile */}
                                {!isConfigViewExpanded && !isMobile && (
                                    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
                                        <TooltipProvider delayDuration={200}>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <button
                                                        data-tour-target="flow-helper-button"
                                                        onClick={() => {
                                                            setIsConfigViewExpanded(
                                                                true
                                                            );
                                                        }}
                                                        className="px-4 py-2 rounded-full text-xs font-medium text-foreground hover:text-foreground transition-all border border-border/40 dark:border-zinc-700/40 shadow-2xl flex items-center gap-2"
                                                        style={{
                                                            background:
                                                                'radial-gradient(circle at 30% 30%, hsl(var(--fab-pill-from)), hsl(var(--fab-pill-to)))',
                                                            boxShadow:
                                                                '0 4px 24px rgba(0, 0, 0, calc(0.5 * var(--shadow-scale, 1))), 0 0 0 1px rgba(255, 255, 255, 0.08)',
                                                        }}
                                                    >
                                                        {isSyncing && (
                                                            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                                                        )}
                                                        {isSyncing
                                                            ? 'Syncing'
                                                            : 'Flow Helper'}
                                                    </button>
                                                </TooltipTrigger>
                                                <TooltipContent
                                                    side="top"
                                                    sideOffset={10}
                                                    className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                                                >
                                                    <span className="flex items-center gap-2">
                                                        Add nodes, config &amp;
                                                        credentials
                                                        <KeyHint keys={['F']} />
                                                    </span>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>
                                    </div>
                                )}

                                {/* Floating add-node + autolayout buttons - hidden on mobile.
                        Stay visible when FlowHelperView is open (still interactive
                        for users to drop nodes / reflow), but fade out when it's
                        full-screen since the canvas is no longer reachable.
                        Also hidden in replay (read-only, no add/reflow). */}
                                {!isMobile && !isReplayMode && (
                                    <TooltipProvider delayDuration={200}>
                                        <div
                                            className="absolute top-4 right-4 z-10 flex flex-col items-center gap-3.5 transition-all duration-300 ease-out"
                                            style={{
                                                opacity: isFlowHelperFullScreen
                                                    ? 0
                                                    : 1,
                                                filter: isFlowHelperFullScreen
                                                    ? 'blur(8px)'
                                                    : 'blur(0px)',
                                                pointerEvents:
                                                    isFlowHelperFullScreen
                                                        ? 'none'
                                                        : 'auto',
                                            }}
                                        >
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <button
                                                        onClick={() => {
                                                            setFlowHelperActiveTab(
                                                                'home'
                                                            );
                                                            setIsConfigViewExpanded(
                                                                true
                                                            );
                                                            bumpSearchFocus();
                                                        }}
                                                        aria-label="Add a node"
                                                        className="group h-11 w-11 rounded-full text-foreground flex items-center justify-center transition-all duration-150 active:translate-y-[3px] active:shadow-inner"
                                                        style={{
                                                            background:
                                                                'radial-gradient(ellipse at 50% 0%, hsl(var(--fab-top)) 0%, hsl(var(--fab-mid)) 35%, hsl(var(--fab-base)) 100%)',
                                                            boxShadow: [
                                                                'inset 0 1.5px 0.5px rgba(255, 255, 255, 0.28)',
                                                                'inset 0 -2px 1px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                'inset 0 0 0 1px rgba(0, 0, 0, calc(0.5 * var(--shadow-scale, 1)))',
                                                                '0 1px 0 rgba(255, 255, 255, 0.06)',
                                                                '0 3px 0 rgba(0, 0, 0, calc(0.7 * var(--shadow-scale, 1)))',
                                                                '0 6px 6px rgba(0, 0, 0, calc(0.4 * var(--shadow-scale, 1)))',
                                                                '0 12px 24px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                            ].join(', '),
                                                        }}
                                                    >
                                                        <Plus
                                                            className="h-[22px] w-[22px] transition-transform group-active:scale-95"
                                                            strokeWidth={2.5}
                                                            style={{
                                                                filter: 'drop-shadow(0 1px 0 rgba(0, 0, 0, calc(0.6 * var(--shadow-scale, 1))))',
                                                            }}
                                                        />
                                                    </button>
                                                </TooltipTrigger>
                                                <TooltipContent
                                                    side="left"
                                                    sideOffset={10}
                                                    className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                                                >
                                                    <span className="flex items-center gap-2">
                                                        Add a node
                                                        <KeyHint keys={['N']} />
                                                    </span>
                                                </TooltipContent>
                                            </Tooltip>
                                            {hasNonCursorNodes && (
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <button
                                                            onClick={
                                                                handleAutolayout
                                                            }
                                                            aria-label="Auto-layout"
                                                            className="group h-9 w-9 rounded-full text-foreground flex items-center justify-center transition-all duration-150 active:translate-y-[2px] active:shadow-inner"
                                                            style={{
                                                                background:
                                                                    'radial-gradient(ellipse at 50% 0%, hsl(var(--fab-top)) 0%, hsl(var(--fab-mid)) 35%, hsl(var(--fab-base)) 100%)',
                                                                boxShadow: [
                                                                    'inset 0 1.5px 0.5px rgba(255, 255, 255, 0.28)',
                                                                    'inset 0 -2px 1px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                    'inset 0 0 0 1px rgba(0, 0, 0, calc(0.5 * var(--shadow-scale, 1)))',
                                                                    '0 1px 0 rgba(255, 255, 255, 0.06)',
                                                                    '0 3px 0 rgba(0, 0, 0, calc(0.7 * var(--shadow-scale, 1)))',
                                                                    '0 6px 6px rgba(0, 0, 0, calc(0.4 * var(--shadow-scale, 1)))',
                                                                    '0 12px 24px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                ].join(', '),
                                                            }}
                                                        >
                                                            <Paintbrush
                                                                className="h-[18px] w-[18px] transition-transform group-active:scale-95 group-hover:rotate-[-12deg]"
                                                                strokeWidth={
                                                                    2.25
                                                                }
                                                                style={{
                                                                    filter: 'drop-shadow(0 1px 0 rgba(0, 0, 0, calc(0.6 * var(--shadow-scale, 1))))',
                                                                }}
                                                            />
                                                        </button>
                                                    </TooltipTrigger>
                                                    <TooltipContent
                                                        side="left"
                                                        sideOffset={10}
                                                        className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                                                    >
                                                        Auto-layout
                                                    </TooltipContent>
                                                </Tooltip>
                                            )}
                                            {/* Invite collaborators — opens a popup with the
                                    shareable link (same visual as the inline
                                    banner). Also the find-the-link walkthrough target. */}
                                            <Popover>
                                                <Tooltip>
                                                    <PopoverTrigger asChild>
                                                        {/* inline-flex wrapper splits the nested
                                                asChild Slots (Popover → span, Tooltip →
                                                button) so neither composed ref churns.
                                                Two Popper anchor refs on one element via
                                                a nested Slot chain loops to React #185
                                                (radix #3799). The span wraps the 36×36
                                                button tightly so popover/tooltip anchoring
                                                is unchanged; data-tour-target stays on the
                                                button so the walkthrough still finds it. */}
                                                        <span className="inline-flex">
                                                            <TooltipTrigger
                                                                asChild
                                                            >
                                                                <button
                                                                    data-tour-target="invite-button"
                                                                    aria-label="Invite collaborators"
                                                                    onClick={() =>
                                                                        logActivity(
                                                                            EVENTS.INVITE_BUTTON_CLICKED,
                                                                            {
                                                                                workflow_id:
                                                                                    workflowId,
                                                                            }
                                                                        )
                                                                    }
                                                                    className="group h-9 w-9 rounded-full text-foreground flex items-center justify-center transition-all duration-150 active:translate-y-[2px] active:shadow-inner"
                                                                    style={{
                                                                        background:
                                                                            'radial-gradient(ellipse at 50% 0%, hsl(var(--fab-top)) 0%, hsl(var(--fab-mid)) 35%, hsl(var(--fab-base)) 100%)',
                                                                        boxShadow:
                                                                            [
                                                                                'inset 0 1.5px 0.5px rgba(255, 255, 255, 0.28)',
                                                                                'inset 0 -2px 1px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                                'inset 0 0 0 1px rgba(0, 0, 0, calc(0.5 * var(--shadow-scale, 1)))',
                                                                                '0 1px 0 rgba(255, 255, 255, 0.06)',
                                                                                '0 3px 0 rgba(0, 0, 0, calc(0.7 * var(--shadow-scale, 1)))',
                                                                                '0 6px 6px rgba(0, 0, 0, calc(0.4 * var(--shadow-scale, 1)))',
                                                                                '0 12px 24px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                            ].join(
                                                                                ', '
                                                                            ),
                                                                    }}
                                                                >
                                                                    <UserPlus
                                                                        className="h-[18px] w-[18px] transition-transform group-active:scale-95"
                                                                        strokeWidth={
                                                                            2.25
                                                                        }
                                                                        style={{
                                                                            filter: 'drop-shadow(0 1px 0 rgba(0, 0, 0, calc(0.6 * var(--shadow-scale, 1))))',
                                                                        }}
                                                                    />
                                                                </button>
                                                            </TooltipTrigger>
                                                        </span>
                                                    </PopoverTrigger>
                                                    <TooltipContent
                                                        side="left"
                                                        sideOffset={10}
                                                        className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                                                    >
                                                        Invite collaborators
                                                    </TooltipContent>
                                                </Tooltip>
                                                <PopoverContent
                                                    side="left"
                                                    align="start"
                                                    sideOffset={12}
                                                    className="w-auto border-0 bg-transparent p-0 shadow-none"
                                                >
                                                    <InviteCard
                                                        workflowId={workflowId}
                                                        className="w-[330px]"
                                                        source="canvas_popover"
                                                    />
                                                </PopoverContent>
                                            </Popover>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <button
                                                        onClick={() => {
                                                            setSettingsInitialSection(
                                                                'variables'
                                                            );
                                                            setIsSettingsDialogOpen(
                                                                true
                                                            );
                                                        }}
                                                        aria-label="Workflow variables"
                                                        className="group h-9 w-9 rounded-full text-foreground flex items-center justify-center transition-all duration-150 active:translate-y-[2px] active:shadow-inner"
                                                        style={{
                                                            background:
                                                                'radial-gradient(ellipse at 50% 0%, hsl(var(--fab-top)) 0%, hsl(var(--fab-mid)) 35%, hsl(var(--fab-base)) 100%)',
                                                            boxShadow: [
                                                                'inset 0 1.5px 0.5px rgba(255, 255, 255, 0.28)',
                                                                'inset 0 -2px 1px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                                'inset 0 0 0 1px rgba(0, 0, 0, calc(0.5 * var(--shadow-scale, 1)))',
                                                                '0 1px 0 rgba(255, 255, 255, 0.06)',
                                                                '0 3px 0 rgba(0, 0, 0, calc(0.7 * var(--shadow-scale, 1)))',
                                                                '0 6px 6px rgba(0, 0, 0, calc(0.4 * var(--shadow-scale, 1)))',
                                                                '0 12px 24px rgba(0, 0, 0, calc(0.55 * var(--shadow-scale, 1)))',
                                                            ].join(', '),
                                                        }}
                                                    >
                                                        <Braces
                                                            className="h-[17px] w-[17px] transition-transform group-active:scale-95"
                                                            strokeWidth={2.25}
                                                            style={{
                                                                filter: 'drop-shadow(0 1px 0 rgba(0, 0, 0, calc(0.6 * var(--shadow-scale, 1))))',
                                                            }}
                                                        />
                                                    </button>
                                                </TooltipTrigger>
                                                <TooltipContent
                                                    side="left"
                                                    sideOffset={10}
                                                    className="rounded-lg border border-border dark:border-white/10 bg-background dark:bg-[#0a0a0b] px-3 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md"
                                                >
                                                    Workflow variables
                                                </TooltipContent>
                                            </Tooltip>
                                        </div>
                                    </TooltipProvider>
                                )}

                                {/* Find-the-link walkthrough: spotlights the invite button the
                        first time the user closes the inline invite banner. */}
                                <GuidedTourHighlight
                                    steps={INVITE_WALKTHROUGH_STEPS}
                                    isActive={inviteWalkthroughActive}
                                    onClose={finishInviteWalkthrough}
                                    onComplete={finishInviteWalkthrough}
                                />

                                {/* Chat-with-your-agent walkthrough — spotlights the Interface tab
                        after the builder finishes a workflow with a trigger-less agent. */}
                                <GuidedTourHighlight
                                    steps={agentChatWalkthroughSteps}
                                    isActive={agentChatWalkthroughActive}
                                    onClose={finishAgentChatWalkthrough}
                                    onComplete={finishAgentChatWalkthrough}
                                />

                                {/* Always-on run-history launcher (top-left). Clicking opens the
                        node-output results popup for the most recent run; the popup's
                        own switcher loads older runs. Hidden only in replay (the
                        replay bar owns the top) and on mobile. */}
                                {!isMobile && !isReplayMode && (
                                    <RunHistoryPill
                                        logs={logs}
                                        onOpen={async () => {
                                            // Refetch page 1 before anchoring:
                                            // headless (webhook/cron) runs land
                                            // while a tab's push stream may be
                                            // stale, so the in-memory newest can
                                            // be hours behind server truth — the
                                            // pill opened pinned to a 2h-old run
                                            // seconds after a webhook fired
                                            // (2026-07-19). Fall back to the
                                            // cached list if the fetch fails.
                                            logsNextCursorRef.current = null;
                                            const fresh =
                                                await fetchLogsPage(null);
                                            const latest =
                                                (fresh && fresh[0]) || logs[0];
                                            if (latest)
                                                openRunResultsForExecution(
                                                    latest
                                                );
                                            else {
                                                setRunResults([]);
                                                setRunResultsExecId(null);
                                                setRunResultsOpen(true);
                                            }
                                        }}
                                    />
                                )}

                                {/* Errored + incomplete navigator pills, hidden
                                    on mobile to avoid clutter. One row so the
                                    two sit a fixed gap apart at any count. */}
                                {!isMobile && (
                                    <CanvasNavigatorPills
                                        isConfigViewExpanded={
                                            isConfigViewExpanded
                                        }
                                        flowHelperHeight={flowHelperHeight}
                                        noAnimation={flowHelperNoAnim}
                                    >
                                        <ErrorNodeNavigator
                                            nodes={stableNodesForNav.current}
                                            selectedNodeId={
                                                selectedNode?.id || null
                                            }
                                            onNavigateToNode={
                                                navigateToErroredNode
                                            }
                                        />
                                        {!isFlowHelperFullScreen && (
                                            <IncompleteNodeNavigator
                                                nodes={
                                                    stableNodesForNav.current
                                                }
                                                validationContext={
                                                    validationContext
                                                }
                                                selectedNodeId={
                                                    selectedNode?.id || null
                                                }
                                                onNavigateToNode={
                                                    navigateToErroredNode
                                                }
                                            />
                                        )}
                                    </CanvasNavigatorPills>
                                )}

                                {!isMobile &&
                                    externalLink &&
                                    isConfigViewExpanded && (
                                        <CanvasExternalLinkPill
                                            url={externalLink.url}
                                            label={externalLink.label}
                                            Icon={externalLink.Icon}
                                            bgColor={externalLink.bgColor}
                                            flowHelperHeight={flowHelperHeight}
                                            noAnimation={flowHelperNoAnim}
                                        />
                                    )}

                                {/* Flow Helper View - hidden on mobile, desktop only */}
                                {isConfigViewExpanded && !isMobile && (
                                    <div
                                        ref={flowHelperContainerRef}
                                        className={`absolute pointer-events-none z-10 ${
                                            isFlowHelperFullScreen
                                                ? 'inset-4' // Full screen with 16px margin on all sides
                                                : 'bottom-0 left-0 right-0 px-4 pb-4'
                                        }`}
                                        style={
                                            !isFlowHelperFullScreen
                                                ? {
                                                      height: `${flowHelperHeight}px`,
                                                      // Eased height transition for programmatic resizes (auto-shrink
                                                      // on deselect, restore on re-select). Disabled mid-drag — the
                                                      // resize handler mutates style.height directly each tick, and
                                                      // a 280ms interpolation would lag the cursor.
                                                      transition:
                                                          isFlowHelperResizing ||
                                                          flowHelperInstantHeight
                                                              ? 'none'
                                                              : 'height 280ms cubic-bezier(0.22, 0.61, 0.36, 1)',
                                                  }
                                                : undefined
                                        }
                                    >
                                        <div className="h-full pointer-events-auto">
                                            <FlowHelperView
                                                selectedNode={selectedNode}
                                                nodes={
                                                    isReplayMode
                                                        ? replayNodes
                                                        : stableNodesForPanel.current
                                                }
                                                edges={
                                                    isReplayMode
                                                        ? replayEdges
                                                        : edges
                                                }
                                                noAnimation={flowHelperNoAnim}
                                                onClose={() => {
                                                    setIsConfigViewExpanded(
                                                        false
                                                    );
                                                    setSelectedNode(null);
                                                    setIsFlowHelperFullScreen(
                                                        false
                                                    );
                                                }}
                                                // Mutation hooks are omitted in replay so the Run/Stop/Autofill
                                                // controls render disabled and data writes can't escape — same
                                                // pattern as the canvas-level handler gating above.
                                                onNodeDataUpdate={
                                                    isReplayMode
                                                        ? undefined
                                                        : handleNodeDataUpdate
                                                }
                                                onInjectIteration={
                                                    isReplayMode
                                                        ? undefined
                                                        : handleInjectIteration
                                                }
                                                onRunNode={
                                                    isReplayMode
                                                        ? undefined
                                                        : runSingleNode
                                                }
                                                onStopNode={
                                                    isReplayMode
                                                        ? undefined
                                                        : stopWorkflow
                                                }
                                                isWorkflowRunning={
                                                    isReplayMode
                                                        ? false
                                                        : isWorkflowRunning
                                                }
                                                isSyncing={
                                                    isReplayMode
                                                        ? false
                                                        : isSyncing
                                                }
                                                workflowId={workflowId}
                                                height={flowHelperHeight}
                                                onHeightChange={
                                                    setFlowHelperHeight
                                                }
                                                containerRef={
                                                    flowHelperContainerRef
                                                }
                                                isFullScreen={
                                                    isFlowHelperFullScreen
                                                }
                                                onFullScreenChange={
                                                    setIsFlowHelperFullScreen
                                                }
                                                onResizeStart={() => {
                                                    setIsFlowHelperResizing(
                                                        true
                                                    );
                                                    // The resize drags the panel up over canvas iframes;
                                                    // disable their pointer events so the global
                                                    // mousemove listener isn't swallowed mid-drag.
                                                    canvasDivRef.current?.classList.add(
                                                        'nc-canvas-interacting'
                                                    );
                                                }}
                                                onResizeEnd={() => {
                                                    setIsFlowHelperResizing(
                                                        false
                                                    );
                                                    canvasDivRef.current?.classList.remove(
                                                        'nc-canvas-interacting'
                                                    );
                                                }}
                                                activeTab={flowHelperActiveTab}
                                                onActiveTabChange={
                                                    setFlowHelperActiveTab
                                                }
                                                searchQuery={
                                                    flowHelperSearchQuery
                                                }
                                                onSearchQueryChange={
                                                    setFlowHelperSearchQuery
                                                }
                                                onSelectNode={
                                                    isReplayMode
                                                        ? undefined
                                                        : navigateToErroredNode
                                                }
                                                workflowVariables={
                                                    workflowVariables
                                                }
                                                onVariableValueChange={
                                                    handleVariableValueChange
                                                }
                                                declaredVariableNames={
                                                    declaredVariableNames
                                                }
                                                credentialVariables={
                                                    credentialVariables
                                                }
                                                nodeOutputSelectionsRef={
                                                    nodeOutputSelectionsRef
                                                }
                                                onNodeOutputSelection={
                                                    setNodeOutputSelection
                                                }
                                                onAutofill={
                                                    isReplayMode
                                                        ? undefined
                                                        : startCanvasAutofill
                                                }
                                                isAutofilling={
                                                    canvasEditState.isEditing
                                                }
                                                autofillStatus={
                                                    canvasAutofillStatus
                                                }
                                                freshlyDroppedNodeId={
                                                    freshlyDroppedNodeId
                                                }
                                                onConsumeFreshlyDroppedNode={() =>
                                                    setFreshlyDroppedNodeId(
                                                        null
                                                    )
                                                }
                                                searchFocusSignal={
                                                    searchFocusSignal
                                                }
                                                autoFocusOperationPicker={
                                                    autoFocusPickerOnOpen
                                                }
                                                onAgentWiringAdd={
                                                    isReplayMode
                                                        ? undefined
                                                        : handleAgentWiringAdd
                                                }
                                                onWiredNodeConfigPatch={
                                                    isReplayMode
                                                        ? undefined
                                                        : handleWiredNodeConfigPatch
                                                }
                                                onWiredNodeCredentialsChange={
                                                    isReplayMode
                                                        ? undefined
                                                        : handleWiredNodeCredentialsChange
                                                }
                                                getWiredNodeData={
                                                    getWiredNodeData
                                                }
                                            />
                                        </div>
                                    </div>
                                )}
                            </div>
                            {/* inner canvas wrapper */}
                        </div>
                    ) : activeTab === 'interface' ? (
                        <div className="flex-1 relative min-h-0 flex flex-col">
                            <CredentialVariablesContext.Provider
                                value={credentialVariables}
                            >
                                <React.Suspense
                                    fallback={
                                        <div className="flex-1 bg-background" />
                                    }
                                >
                                    <WorkflowInterface
                                        ref={workflowInterfaceRef}
                                        onBlockAdded={handleInterfaceBlockAdded}
                                        onBlockRemoved={
                                            handleInterfaceBlockRemoved
                                        }
                                        onBlockConfigChanged={
                                            handleInterfaceBlockConfigChanged
                                        }
                                        onFormSubmit={handleFormSubmit}
                                        onAgentChatSend={handleAgentChatSend}
                                        onAgentCredentialIdsChange={(
                                            nodeId,
                                            credentialIds
                                        ) => {
                                            setNodes((prev) =>
                                                updateNodeInList(prev, nodeId, {
                                                    credentialIds,
                                                })
                                            );
                                            authorizeCredentialsForWorkflow(
                                                workflowId,
                                                credentialIds
                                            );
                                        }}
                                        workflowId={workflowId}
                                        loadingBlockIds={loadingBlockIds}
                                        initialBlocks={interfaceInitialBlocks}
                                        savedState={interfaceGridState}
                                        onStateChange={
                                            handleInterfaceStateChange
                                        }
                                        agentWiring={agentWiring}
                                        onAgentWiringAdd={handleAgentWiringAdd}
                                        onAgentWiringRemove={
                                            handleAgentWiringRemove
                                        }
                                        onWiredNodeConfigPatch={
                                            handleWiredNodeConfigPatch
                                        }
                                        onWiredNodeCredentialsChange={
                                            handleWiredNodeCredentialsChange
                                        }
                                        getWiredNodeData={getWiredNodeData}
                                    />
                                </React.Suspense>
                            </CredentialVariablesContext.Provider>
                        </div>
                    ) : activeTab === 'resources' ? (
                        <div className="flex-1 bg-sunken p-6 flex flex-col overflow-hidden">
                            <h2 className="text-muted-foreground dark:text-white/70 text-base font-semibold uppercase tracking-wider mb-6 ml-4">
                                Resources
                            </h2>
                            <WorkflowResources workflowId={workflowId || ''} />
                        </div>
                    ) : (
                        <div className="flex-1 bg-sunken p-3 sm:p-5 flex flex-col overflow-hidden">
                            <WorkflowExecutionLogs
                                logs={logs}
                                counts={logCounts}
                                hasMore={logsHasMore}
                                loading={logsLoading}
                                onFiltersChange={handleLogsFiltersChange}
                                onLoadMore={handleLogsLoadMore}
                                onRowClick={openExecutionReplay}
                            />
                        </div>
                    )}

                    {/* Shared empty-state overlay for canvas + interface tabs. Canvas hint
                disappears once any node exists; interface hint sticks around as long
                as the interface has no blocks, even if the canvas already has nodes. */}
                    <AnimatePresence>
                        {!isSyncing &&
                            !workflowLoadError &&
                            ((activeTab === 'canvas' &&
                                !isConfigViewExpanded &&
                                !hasNonCursorNodes) ||
                                (activeTab === 'interface' &&
                                    !hasInterfaceBlocks)) && (
                                <FlowCanvasEmptyState
                                    key="shared-empty-state"
                                    activeTab={
                                        activeTab as 'canvas' | 'interface'
                                    }
                                    onSwitchTab={(tab) => setActiveTab(tab)}
                                />
                            )}
                    </AnimatePresence>
                </WorkflowProvider>
            </div>

            <CanvasDialogs
                workflowId={workflowId}
                workflowTitle={workflowTitle}
                nodes={nodes}
                isShareDialogOpen={isShareDialogOpen}
                onShareDialogChange={setIsShareDialogOpen}
                isSettingsDialogOpen={isSettingsDialogOpen}
                onSettingsDialogChange={setIsSettingsDialogOpen}
                settingsInitialSection={settingsInitialSection}
                workflowSettings={workflowSettings}
                onWorkflowSettingsChange={setWorkflowSettings}
                confettiTrigger={confettiTrigger}
                isMobile={isMobile}
                mobileErrors={mobileErrors}
            />

            {/* Steps OR paths. This used to require a non-empty step list,
                which held back when the popup only ever explained missing
                setup — but the gate also takes over the press to ask which
                entry points to run, and a fully-configured workflow has no
                steps. That combination swallowed the press and rendered
                nothing: Run looked dead. Both are still checked so a popup
                whose nodes were deleted under it closes instead of lingering
                as an empty shell. */}
            {incompleteDialogOpen &&
                (incompleteSteps.length > 0 || runPaths.length > 0) && (
                    <IncompleteRunDialog
                        steps={incompleteSteps}
                        valuesForNode={incompleteStepValues}
                        credentialsForNode={incompleteStepCredentials}
                        workflowId={workflowId}
                        onFieldChange={handleIncompleteFieldChange}
                        onOperationChange={handleIncompleteOperationChange}
                        onCredentialsChange={handleIncompleteCredentialsChange}
                        onClose={() => setIncompleteDialogOpen(false)}
                        onOpenStepConfig={handleOpenIncompleteConfig}
                        onOpenStepCredentials={handleOpenIncompleteCredentials}
                        paths={runPaths}
                        selectedPathIds={selectedPathIds}
                        onTogglePath={handleToggleRunPath}
                        onToggleAllPaths={handleToggleAllRunPaths}
                        pathMessages={pathMessages}
                        onPathMessageChange={handleRunPathMessageChange}
                        handsOffToChat={runPathsScope === 'workflow'}
                        onRun={() => {
                            track('workflow.incomplete_run_prompt_run', {
                                workflow_id: workflowId,
                                step_count: incompleteSteps.length,
                                unresolved: incompleteSteps.filter(
                                    (s) => !s.resolved
                                ).length,
                                paths_selected: selectedPathIds.size,
                            });
                            setIncompleteDialogOpen(false);
                            // Replays the run this popup interrupted — the whole
                            // workflow, a single node, or from a node down.
                            const pending = incompletePendingRunRef.current;
                            incompletePendingRunRef.current = null;
                            runWithoutGate(() => {
                                // A node-scoped run already knows what it
                                // runs, so the popup only collected the
                                // agent's opening message — hand it to the
                                // very call the gate intercepted.
                                if (runPathsScope === 'node')
                                    (pending ?? runWorkflow)(
                                        agentMessageOverrides(runPaths)
                                    );
                                else if (runPaths.length > 0)
                                    startSelectedRunPaths();
                                else (pending ?? runWorkflow)();
                            });
                        }}
                    />
                )}

            {triggerDialogOpen && (
                <TriggerInfoDialog
                    triggers={triggerRunPrompt}
                    onClose={() => setTriggerDialogOpen(false)}
                    onAddRunStep={handleAddManualRun}
                    onOpenTriggerConfig={handleOpenTriggerConfig}
                    onRunAnyway={() => {
                        setTriggerDialogOpen(false);
                        runWorkflow();
                    }}
                />
            )}

            {runResultsOpen && (
                <RunResultsDialog
                    results={runResults}
                    agentInputs={agentInputs}
                    workflowName={workflowTitle}
                    runs={logs}
                    currentExecId={runResultsExecId}
                    loading={runResultsLoading}
                    hasMore={logsHasMore}
                    loadingMore={logsLoading}
                    onLoadMore={handleLogsLoadMore}
                    onSelectRun={openRunResultsForExecution}
                    onClose={() => setRunResultsOpen(false)}
                    onOpenConfig={handleOpenResultsConfig}
                    onDontShowAgain={markResultsPopupDisabled}
                />
            )}
        </div>
    );
};

// Wrapper component that provides DndContext
const FlowCanvasWithDnd = ({
    workflowTitle,
    workflowId,
    onBack,
    onDelete,
    onTitleChange,
    onNavigateToWorkflow,
    source,
}: FlowCanvasProps) => {
    const { logActivity } = useAnalytics();
    const [draggedNode, setDraggedNode] = useState<NodeDefinition | null>(null);
    // Model a seeded Agent tile will write into data.config (harness/model
    // palette search) — the overlay mirrors the tile's harness logo from it.
    const [draggedSeedModel, setDraggedSeedModel] = useState<string | null>(
        null
    );
    const [draggedJsonField, setDraggedJsonField] =
        useState<JsonFieldDragData | null>(null);

    // Store node setters in a ref so handleDragEnd can access them
    const nodeSettersRef = useRef<NodeSetters>({});

    // Prefetch credentials on mount for faster auto-selection
    useEffect(() => {
        prefetchCredentials();
    }, []);

    const handleDragStart = useCallback((event: DragStartEvent) => {
        const { active } = event;

        if (active.data.current?.type === 'workflow-node') {
            const nodeDefinition = active.data.current
                .nodeDefinition as NodeDefinition;
            setDraggedNode(nodeDefinition);
            const seedConfig = active.data.current.initialConfig as
                | Record<string, unknown>
                | null
                | undefined;
            setDraggedSeedModel(
                typeof seedConfig?.model === 'string' ? seedConfig.model : null
            );
            // The draggable node IS the preview (same size as the overlay
            // content), so dnd-kit keeps the cursor under the grab point
            // automatically — no offset math needed.
        } else if (active.data.current?.type === 'json-field-reference') {
            const jsonFieldData = active.data.current as JsonFieldDragData;
            setDraggedJsonField(jsonFieldData);
            // Mirror the drag through a DOM event so out-of-tree consumers
            // (e.g. ChatBox in the sidebar) can land drops too — see
            // jsonFieldDragBridge.ts for the rationale.
            dispatchJsonFieldDragStart(jsonFieldData);
        }
    }, []);

    // Translate a drop on a smart target into the click-to-add event the "+"
    // buttons already dispatch, so drop and click share one wiring path. Returns
    // false when the dropped type can't be wired to that target — the caller then
    // falls through to a plain canvas placement.
    const dispatchSmartDrop = useCallback(
        (
            nodeType: string,
            dropKind: string | undefined,
            drop: Record<string, unknown>,
            active: Record<string, unknown>
        ): boolean => {
            const seed = {
                nodeType,
                initialConfig: active.initialConfig ?? null,
                initialOperation: active.initialOperation ?? null,
            };

            if (dropKind === 'agent-tools-drop') {
                if (!canFeedAgentBottom(nodeType)) return false;
                // The dropped provider is the edge SOURCE (its 'top'); the agent
                // is the TARGET (its 'bottom'). Priming the agent's bottom handle
                // as the "source" also places the new node below it.
                document.dispatchEvent(
                    new CustomEvent('noclick:add-connected-node', {
                        detail: {
                            ...seed,
                            source: {
                                nodeId: drop.agentNodeId as string,
                                handleId: 'bottom',
                                handlePosition: Position.Bottom,
                                handleOffsetFromCenter: 0,
                            },
                            reverseEdge: { sourceHandle: 'top' },
                        },
                    })
                );
                return true;
            }

            if (dropKind === 'edge-insert-drop') {
                if (nodeType === 'stickyNote') return false;
                document.dispatchEvent(
                    new CustomEvent('noclick:add-connected-node', {
                        detail: {
                            ...seed,
                            insert: {
                                edgeId: drop.edgeId,
                                source: drop.source,
                                target: drop.target,
                                sourceHandle: drop.sourceHandle ?? null,
                                targetHandle: drop.targetHandle ?? null,
                                position: drop.position,
                            },
                        },
                    })
                );
                return true;
            }

            if (dropKind === 'node-tail-drop') {
                const directAddAgent = drop.directAddAgent === true;
                if (nodeType === 'stickyNote') return false;
                // A provider's top hint only accepts a node that can receive a
                // tools edge on its bottom.
                if (
                    directAddAgent &&
                    nodeType !== 'agent' &&
                    nodeType !== 'mcp-server'
                ) {
                    return false;
                }
                document.dispatchEvent(
                    new CustomEvent('noclick:add-connected-node', {
                        detail: {
                            ...seed,
                            ...(directAddAgent
                                ? { targetHandle: 'bottom' }
                                : {}),
                            source: {
                                nodeId: drop.nodeId as string,
                                handleId: (drop.handleId as string) ?? null,
                                handlePosition: drop.handlePosition,
                                handleOffsetFromCenter:
                                    (drop.offsetFromCenter as number) ?? 0,
                            },
                        },
                    })
                );
                return true;
            }

            return false;
        },
        []
    );

    const handleDragEnd = useCallback(
        (event: DragEndEvent) => {
            const { active, over } = event;
            const isJsonFieldDrag =
                active.data.current?.type === 'json-field-reference';

            setDraggedNode(null);
            setDraggedSeedModel(null);
            setDraggedJsonField(null);

            if (isJsonFieldDrag) {
                dispatchJsonFieldDragEnd();
            }

            // Handle JSON field reference drops on config fields
            if (
                active.data.current?.type === 'json-field-reference' &&
                over?.data?.current?.type === 'config-field'
            ) {
                const jsonData = active.data.current as JsonFieldDragData;
                const fieldKey = over.data.current.fieldKey as string;

                // Trailing space so the cursor lands OUTSIDE the block after a drop — the
                // user can keep dropping references without the expression builder popping
                // open each time (it opens when the cursor sits inside a `{{ }}` block).
                const reference =
                    createReferenceString(jsonData.nodeId, jsonData.path) + ' ';
                logActivity(EVENTS.REFERENCE_DROPPED, {
                    source_node_id: jsonData.nodeId,
                    target: 'node_config',
                });

                // Try registry first (most reliable), then fall back to DOM element
                const insertFn = getInsertReferenceForField(fieldKey);
                if (insertFn) {
                    insertFn(reference);
                } else {
                    // Fallback to DOM element method
                    const fieldElement = document.querySelector(
                        `[data-field-key="${fieldKey}"]`
                    ) as HTMLInputElement | HTMLTextAreaElement | null;
                    if (
                        fieldElement &&
                        (fieldElement as any).__insertReference
                    ) {
                        (fieldElement as any).__insertReference(reference);
                    } else {
                        console.error(
                            '[DragEnd] Cannot insert reference - no handler found for fieldKey:',
                            fieldKey
                        );
                    }
                }
                return;
            }

            // Handle JSON field reference drops on state editor fields
            if (
                active.data.current?.type === 'json-field-reference' &&
                over?.data?.current?.type === 'state-editor-field'
            ) {
                const jsonData = active.data.current as JsonFieldDragData;
                const fieldKey = over.data.current.fieldKey as string;

                // Create the reference string (for state editor, we insert it as a string value)
                const reference = `"{{${jsonData.nodeId}.${jsonData.path}}}"`;
                logActivity(EVENTS.REFERENCE_DROPPED, {
                    source_node_id: jsonData.nodeId,
                    target: 'state_editor',
                });

                // Find the state editor element and call its insertReference method
                const stateEditorEl = document.querySelector(
                    `[data-state-editor-field-key="${fieldKey}"]`
                );
                if (stateEditorEl && (stateEditorEl as any).__insertReference) {
                    (stateEditorEl as any).__insertReference(reference);
                } else {
                    console.error(
                        '[DragEnd] Cannot insert reference into state editor - no handler found for fieldKey:',
                        fieldKey
                    );
                }
                return;
            }

            // Node drops land on bare canvas OR on a smart target (agent body,
            // edge midpoint "+", node tail "+") that wires the node up instead of
            // placing it standalone.
            const dropKind = over?.data?.current?.type as string | undefined;
            const isSmartDrop = !!dropKind && CANVAS_DROP_KINDS.has(dropKind);
            if (
                !over ||
                (over.id !== 'flow-canvas' && !isSmartDrop) ||
                active.data.current?.type !== 'workflow-node'
            ) {
                return;
            }

            const nodeType = active.data.current.nodeType as string;
            if (!nodeType) {
                return;
            }

            // A smart drop reuses the click-to-add pipeline (node creation, edge
            // wiring, credential auto-select, collab broadcast all live there).
            // An unwired type falls through to a plain canvas placement.
            if (
                isSmartDrop &&
                dispatchSmartDrop(
                    nodeType,
                    dropKind,
                    over.data.current as Record<string, unknown>,
                    active.data.current as Record<string, unknown>
                )
            ) {
                return;
            }

            // Calculate drop position
            let nodePosition = { x: 250, y: 150 };
            const translated = active.rect.current?.translated;

            if (translated && window.screenToFlowPosition) {
                nodePosition = window.screenToFlowPosition(
                    translated.left,
                    translated.top
                );
            }

            // Only one on-error node allowed per workflow
            if (nodeType === 'on-error') {
                const currentNodes = nodeSettersRef.current.getNodes?.() ?? [];
                if (currentNodes.some((n: Node) => n.type === 'on-error')) {
                    toast.error(
                        'Only one On Error node is allowed per workflow'
                    );
                    return;
                }
            }

            // Build node data - start with empty credentials for immediate placement
            const nodeData: Record<string, any> =
                nodeType === 'stickyNote'
                    ? { content: '', color: 8 }
                    : { credentialIds: {} };

            // Intentionally NO default operation for manually-dropped nodes —
            // we want the OperationPicker to open in its full action-selection
            // view so the user explicitly picks. AI-added nodes get their
            // operation from node drafter; before that lands the picker is open too.
            // (Validation falls back to the first variant if `operation` is
            // unset, so the schema still has a sensible shape until the user
            // commits.)

            // Picker-supplied seed. Agent model hits seed config fields; operation
            // hits seed the top-level operation so the picker opens selected.
            const initialOperation = active.data.current?.initialOperation as
                | string
                | null
                | undefined;
            if (initialOperation) {
                nodeData.operation = initialOperation;
            }
            const initialConfig = active.data.current?.initialConfig as
                | Record<string, any>
                | null
                | undefined;
            if (initialConfig && Object.keys(initialConfig).length > 0) {
                nodeData.config = {
                    ...(nodeData.config ?? {}),
                    ...initialConfig,
                };
            }

            // Create and add node IMMEDIATELY (optimistic update)
            const newNodeId = generateNodeId(nodeType);
            const newNode = createWorkflowNode(
                newNodeId,
                nodeType,
                nodePosition,
                nodeData
            );

            // Set initial dimensions for resizable nodes (sticky notes + interface blocks)
            if (nodeType === 'stickyNote') {
                newNode.style = { width: 200, height: 200 };
            } else if (nodeType.startsWith('interface-')) {
                const nodeDef = getNodeMetadata(nodeType);
                newNode.style = {
                    width: nodeDef?.dimensions.width ?? 350,
                    height: nodeDef?.dimensions.height ?? 200,
                };
            }

            // Split Out exists to produce items for a loop. Drop it pre-wired to an
            // Iteration node, with the iteration's `items` already pointed at the
            // split-out's output, so the items flow into an explicit loop with no
            // extra wiring (NoClick has no implicit per-item fan-out).
            let pairedIteration: Node | undefined;
            let pairedEdge: Edge | undefined;
            if (nodeType === 'split-out') {
                const iterId = generateNodeId('iteration');
                pairedIteration = createWorkflowNode(
                    iterId,
                    'iteration',
                    { x: nodePosition.x + 280, y: nodePosition.y },
                    {
                        config: {
                            items: `{{${newNodeId}.items}}`,
                            header_row: 'false',
                            concurrency: 1,
                        },
                    }
                );
                pairedEdge = applyEdgeStyle({
                    id: `xy-edge__${newNodeId}-${iterId}`,
                    source: newNodeId,
                    target: iterId,
                } as Edge);
            }

            const setterFn = nodeSettersRef.current.setNodes;

            if (setterFn) {
                setterFn((prevNodes: Node[]) =>
                    pairedIteration
                        ? [...prevNodes, newNode, pairedIteration]
                        : [...prevNodes, newNode]
                );
                // Broadcast new node to collaborators
                nodeSettersRef.current.broadcastNodeAdd?.(newNode);
                if (pairedIteration && pairedEdge) {
                    nodeSettersRef.current.broadcastNodeAdd?.(pairedIteration);
                    nodeSettersRef.current.setEdges?.((prevEdges: Edge[]) => [
                        ...prevEdges,
                        pairedEdge!,
                    ]);
                    nodeSettersRef.current.broadcastEdgeAdd?.(pairedEdge!);
                }
            }

            logActivity(EVENTS.NODE_ADDED, {
                node_id: newNodeId,
                node_type: nodeType,
                workflow_id: workflowId,
                source: 'manual',
            });

            // Reverse auto-sync: when an interface node is dropped onto the canvas,
            // also create the corresponding block in the WorkflowInterface grid
            if (nodeType.startsWith('interface-')) {
                const blockType = getBlockTypeForNodeType(nodeType);
                if (blockType) {
                    nodeSettersRef.current.addInterfaceBlock?.(
                        newNodeId,
                        blockType
                    );
                }
            }

            // For non-sticky-note nodes, select the node and open config view
            if (
                nodeType !== 'stickyNote' &&
                nodeSettersRef.current.onNodeCreated
            ) {
                // Mark this node as freshly dropped so the Config tab opens in
                // Edit view rather than Configuration when it becomes selected.
                nodeSettersRef.current.setFreshlyDroppedNodeId?.(newNodeId);
                // Small delay to ensure node is added to state before selecting
                setTimeout(() => {
                    nodeSettersRef.current.onNodeCreated?.(newNodeId);
                }, 50);
            }

            // Auto-select credentials: cache-first with background refresh
            if (nodeType !== 'stickyNote' && setterFn) {
                autoSelectCredentialsForNewNode(newNode, setterFn, workflowId);
            }
        },
        [workflowId, logActivity, dispatchSmartDrop]
    );

    // Calculate overlay dimensions to match MiniNodePreview size
    const overlayDimensions = draggedNode
        ? calculateOverlayDimensions(draggedNode)
        : null;

    // Drag overlay for workflow nodes
    const isStickyNoteDrag = draggedNode?.type === 'stickyNote';
    const isInterfaceNodeDrag = draggedNode?.type.startsWith('interface-');
    const interfaceBlockType = isInterfaceNodeDrag
        ? (getBlockTypeForNodeType(draggedNode!.type) ??
          draggedNode!.type.replace('interface-', ''))
        : null;
    const nodeOverlay =
        draggedNode && overlayDimensions ? (
            isStickyNoteDrag ? (
                <div
                    className="opacity-80"
                    style={{
                        width: overlayDimensions.width,
                        height: overlayDimensions.height,
                    }}
                >
                    <MiniStickyNotePreview size={overlayDimensions.height} />
                </div>
            ) : isInterfaceNodeDrag && interfaceBlockType ? (
                <div
                    className="shadow-2xl dark:shadow-black/40 rounded-lg opacity-80"
                    style={{ width: getBlockPreviewWidth() }}
                >
                    <BlockPreviewCard
                        blockType={interfaceBlockType}
                        label={draggedNode.label}
                        Icon={draggedNode.Icon}
                    />
                </div>
            ) : (
                <div
                    className="relative rounded-2xl overflow-hidden border border-border/40 dark:border-zinc-700/40 shadow-2xl flex items-center justify-center opacity-80"
                    style={{
                        width: overlayDimensions.width,
                        height: overlayDimensions.height,
                        background:
                            'radial-gradient(circle at 30% 30%, hsl(var(--fab-pill-from)), hsl(var(--fab-pill-to)))',
                    }}
                >
                    <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.08] via-transparent to-transparent backdrop-blur-[2px]" />
                    {/* NodePreviewIcon (not the raw Icon): keeps the ghost identical to
                    the palette tile (harness logo on seeded Agent tiles) and routes
                    through BrandIcon's text-foreground fallback — the overlay portals
                    to document.body where currentColor is black, so an empty iconColor
                    (MCP) needs it. */}
                    <NodePreviewIcon
                        node={draggedNode}
                        seedModel={draggedSeedModel}
                        iconSize={overlayDimensions.iconSize}
                        className="relative z-10"
                    />
                </div>
            )
        ) : null;

    // Drag overlay for JSON field references — theme-aware compact chip (white
    // popover in light, the zinc gradient pinned in dark).
    const jsonFieldOverlay = draggedJsonField ? (
        <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border border-border/60 dark:border-zinc-700/60 min-w-[120px] bg-popover dark:bg-transparent dark:bg-gradient-to-br dark:from-zinc-700/70 dark:to-zinc-900/95"
            style={{
                boxShadow:
                    '0 4px 20px rgba(0, 0, 0, calc(0.4 * var(--shadow-scale, 1))), 0 0 0 1px rgba(255, 255, 255, 0.06)',
            }}
        >
            <Link2 className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 flex-shrink-0" />
            <div className="flex flex-col min-w-0">
                {/* Value - compact display */}
                <span className="text-xs text-foreground font-medium truncate max-w-[160px]">
                    {draggedJsonField.displayValue}
                </span>
                {/* Reference path - subtle */}
                <span className="text-[9px] text-muted-foreground dark:text-zinc-500 font-mono truncate max-w-[160px]">
                    {draggedJsonField.path}
                </span>
            </div>
        </div>
    ) : null;

    // Combined overlay
    const dragOverlay = nodeOverlay || jsonFieldOverlay;

    return (
        <DndProvider
            onDragStart={handleDragStart}
            onDragEnd={handleDragEnd}
            overlay={dragOverlay}
            autoScroll={!draggedJsonField}
        >
            <FlowCanvasInner
                workflowTitle={workflowTitle}
                workflowId={workflowId}
                onBack={onBack}
                onDelete={onDelete}
                onTitleChange={onTitleChange}
                onNavigateToWorkflow={onNavigateToWorkflow}
                source={source}
                nodeSettersRef={nodeSettersRef}
            />
        </DndProvider>
    );
};

const FlowCanvas = ({
    workflowTitle,
    workflowId,
    onBack,
    onDelete,
    onTitleChange,
    onNavigateToWorkflow,
    source,
}: FlowCanvasProps) => {
    return (
        <ReactFlowProvider>
            <FlowCanvasWithDnd
                workflowTitle={workflowTitle}
                workflowId={workflowId}
                onBack={onBack}
                onDelete={onDelete}
                onTitleChange={onTitleChange}
                onNavigateToWorkflow={onNavigateToWorkflow}
                source={source}
            />
        </ReactFlowProvider>
    );
};

export { FlowCanvas };
export default FlowCanvas;
