// Main grid layout component for the Gradio-style interface builder.
// Uses react-grid-layout v2 to render a drag-and-drop grid where users can
// place, resize, and rearrange interface UI blocks added from the node palette.
// Block config is derived directly from ReactFlow node data (single source of truth).
// Only layout (grid positions) is managed as local state.
// Supports fullscreen mode: blocks with config.fullscreen === 'true' render as
// full-viewport tabs instead of grid items, with a sub-tab bar for switching.

import React, {
    useState,
    useCallback,
    useMemo,
    useImperativeHandle,
    forwardRef,
    useRef,
    useEffect,
    useLayoutEffect,
} from 'react';
import { updateBuilderContext } from '~/lib/builder-context';
import { GridLayout, useContainerWidth, getCompactor } from 'react-grid-layout';
import { GridBackground } from 'react-grid-layout/extras';
import type { Layout, LayoutItem } from 'react-grid-layout';
import { LayoutGrid } from 'lucide-react';
import { BlockRenderer } from './BlockRenderer';
import { BlockWrapper } from './BlockWrapper';
import { getBlockDefinition } from './blockRegistry';
import { InterfaceBuildingAnimation } from './InterfaceBuildingAnimation';
import { InlineTextEditor } from '~/components/ui/InlineTextEditor';
import type { PlacedBlock, BlockConfig, AgentWiring } from './types';
import type { AgentChatAttachment } from '~/lib/agentChat';
import {
    isFullscreenValue,
    resolveInterfaceBlockLabel,
} from '~/utils/interfaceNodes';
import 'react-grid-layout/css/styles.css';

// Static placeholder id used as a template for items being dropped from outside.
// Gets replaced with a real unique id in onDrop.
const DROPPING_ITEM_ID = '__dropping-elem__';

/** Subtle wireframe that stands in for an empty interface. Evokes a generic
 * "app surface" — sidebar + header + main content — via a few soft shapes
 * with quiet hints of detail (logo dot, nav ticks, avatar) so the empty-state
 * overlay reads as sitting on top of a real UI. */
function InterfaceSkeleton() {
    // Light: faint /40 borders + card gradient vanished on the white canvas, so use
    // a visible border + subtle gray fill; dark keeps the original soft treatment.
    const surface =
        'rounded-xl border border-border bg-foreground/[0.02] dark:border-border/40 dark:bg-gradient-to-b dark:from-card/30 dark:to-card/10';
    const dot = 'rounded-full bg-muted-foreground/25 dark:bg-muted/50';
    const pill = 'rounded-full bg-muted-foreground/20 dark:bg-muted/40';
    return (
        <div className="absolute inset-0 p-5 flex gap-3.5 pointer-events-none select-none">
            <div className={`${surface} w-60 shrink-0 p-4 flex flex-col gap-5`}>
                <div className="flex items-center gap-2.5">
                    <div className="w-6 h-6 rounded-md bg-muted-foreground/25 dark:bg-muted/50" />
                    <div className={`${pill} h-2 w-20`} />
                </div>
                <div className="flex flex-col gap-3 mt-1">
                    <div className={`${pill} h-1.5 w-3/4`} />
                    <div className={`${pill} h-1.5 w-2/3`} />
                    <div className={`${pill} h-1.5 w-4/5`} />
                    <div className={`${pill} h-1.5 w-1/2`} />
                </div>
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-3.5">
                <div
                    className={`${surface} h-16 shrink-0 px-4 flex items-center justify-between`}
                >
                    <div className={`${pill} h-2 w-28`} />
                    <div className="flex items-center gap-3">
                        <div className={`${dot} w-1.5 h-1.5`} />
                        <div className={`${dot} w-1.5 h-1.5`} />
                        <div className="w-6 h-6 rounded-full bg-muted-foreground/25 dark:bg-muted/50" />
                    </div>
                </div>
                <div className={`${surface} flex-1 min-h-0`} />
                <div className="grid grid-cols-5 gap-3.5 h-28 shrink-0">
                    <div className={`${surface} col-span-3`} />
                    <div className={`${surface} col-span-2`} />
                </div>
            </div>
        </div>
    );
}
const ROW_H = 40;
const GRID_MARGIN: readonly [number, number] = [10, 10];
const GRID_CPAD: readonly [number, number] = [16, 16];
const CELL_RADIUS = 6;
// Free-form positioning (no compaction) with collision prevention so blocks can't overlap.
const freeFormCompactor = getCompactor(null, false, true);

const droppingItemTemplate: LayoutItem = {
    i: DROPPING_ITEM_ID,
    x: 0,
    y: 0,
    w: 4,
    h: 3,
};

export interface WorkflowInterfaceHandle {
    /** Add a block's layout to the interface grid (called when an interface node is dropped onto the canvas) */
    addBlock: (blockId: string, blockType: string) => void;
    /** Remove a block's layout from the interface grid by id */
    removeBlock: (blockId: string) => void;
    /** Replace the grid layout (used by MCP dual-delivery to sync interface layout) */
    setFullState: (state: InterfaceGridState) => void;
    /** Programmatically switch the active sub-tab (e.g. when the canvas
     *  "Chat" button on an agent node deep-links the user into that agent's
     *  fullscreen chat block). Accepts either 'grid' or a block id. */
    setActiveSubTab: (subTabId: string) => void;
}

/** Serialisable snapshot of the interface grid layout, stored in FlowCanvas to survive remounts. */
export interface InterfaceGridState {
    layout: Layout;
    /** Ordered list of sub-tab IDs ('grid' for default tab, node IDs for fullscreen tabs). */
    tabOrder?: string[];
}

interface WorkflowInterfaceProps {
    onBlockAdded?: (blockId: string, nodeType: string) => void;
    onBlockRemoved?: (blockId: string) => void;
    /** Initial blocks to populate the grid with (derived from existing ReactFlow interface nodes) */
    initialBlocks?: {
        id: string;
        blockType: string;
        nodeData?: Record<string, unknown>;
    }[];
    /** Persisted grid layout from a previous mount — restores positions across tab switches */
    savedState?: InterfaceGridState | null;
    /** Called whenever layout changes so the parent can persist state across remounts */
    onStateChange?: (state: InterfaceGridState) => void;
    /** Called when a block's config changes so the parent can sync to the Valtio node */
    onBlockConfigChanged?: (blockId: string, config: BlockConfig) => void;
    /** Called when a form block's submit button is clicked */
    onFormSubmit?: (blockId: string, values: Record<string, unknown>) => void;
    /** Set of block IDs currently loading (guaranteed-reachable blocks during execution) */
    loadingBlockIds?: Set<string>;
    /** Called when the active fullscreen sub-tab changes (node ID or 'grid') */
    onActiveSubTabChange?: (subTabId: string) => void;
    /** Read-only mode — disables drag/resize/drop, hides remove buttons, disables tab editing */
    isReadOnly?: boolean;
    /** Called when a user tries to interact with a block in read-only mode (e.g. form submit, SDK call) */
    onReadOnlyInteraction?: () => void;
    /** Active workflow id — needed by the agent-chat block to scope its conversation_id. */
    workflowId?: string;
    /** Called when an agent-chat block submits a chat message. */
    onAgentChatSend?: (
        nodeId: string,
        message: string,
        model: string,
        /** The conversation to send into. Passed explicitly because the send may
         *  be minting it in the same call — reading it back from the node config
         *  would race the write and land the turn in the thread being left. */
        conversationKey?: string,
        /** Files attached to this message (already uploaded to R2). */
        attachments?: AgentChatAttachment[]
    ) => void;
    /** Called when an agent-chat block updates the agent node's credentialIds
     *  (model-specific API keys / OAuth selections). */
    onAgentCredentialIdsChange?: (
        nodeId: string,
        credentialIds: Record<string, string>
    ) => void;
    /** Trigger/tool wiring per interface-shown agent (computed canvas-side) —
     *  drives the agent chat sidebar's Triggers and Tools sections. */
    agentWiring?: Record<string, AgentWiring>;
    /** Add a trigger or tool-provider node wired to an agent. Returns the new node id. */
    onAgentWiringAdd?: (
        agentNodeId: string,
        nodeType: string,
        role: 'trigger' | 'tool',
        operation?: string
    ) => string | void;
    /** Remove a wired trigger/tool (drops the edge; the node too when orphaned). */
    onAgentWiringRemove?: (edgeId: string, nodeId: string) => void;
    /** Patch a WIRED node's config (e.g. a provider's allowlist). */
    onWiredNodeConfigPatch?: (
        nodeId: string,
        config: Record<string, unknown>
    ) => void;
    /** Patch a WIRED node's credentialIds. */
    onWiredNodeCredentialsChange?: (
        nodeId: string,
        credentialIds: Record<string, string>
    ) => void;
    /** Live accessor for a wired node's data (palette config step). */
    getWiredNodeData?: (nodeId: string) => {
        nodeData: Record<string, unknown>;
        config: Record<string, unknown>;
        credentialIds: Record<string, string>;
    } | null;
}

/** Check whether a placed block should render in fullscreen mode (component blocks with fullscreen enabled).
 *  `fullscreen` is fullscreen unless explicitly false (shared semantics with the canvas — see isFullscreenValue). */
const isFullscreen = (b: PlacedBlock) =>
    (b.type === 'html-react' && isFullscreenValue(b.config.fullscreen)) ||
    b.type === 'agent-chat';

/** Mirror of isFullscreen that works against the lighter `initialBlocks` shape
 *  used at useState init time (no PlacedBlock projection yet). */
const isFullscreenInitial = (b: {
    blockType: string;
    nodeData?: Record<string, unknown>;
}): boolean => {
    if (b.blockType === 'agent-chat') return true;
    if (b.blockType !== 'html-react') return false;
    const nd = (b.nodeData ?? {}) as Record<string, unknown>;
    const nested = (nd.config as Record<string, unknown> | undefined)
        ?.fullscreen;
    // Prefer the nested config value (authoritative); fall back to a flat value if that's all there is.
    return isFullscreenValue(nested ?? nd.fullscreen);
};

export const WorkflowInterface = forwardRef<
    WorkflowInterfaceHandle,
    WorkflowInterfaceProps
>(function WorkflowInterface(
    {
        onBlockAdded,
        onBlockRemoved,
        initialBlocks,
        savedState,
        onStateChange,
        onBlockConfigChanged,
        onFormSubmit,
        loadingBlockIds,
        onActiveSubTabChange,
        isReadOnly = false,
        onReadOnlyInteraction,
        workflowId,
        onAgentChatSend,
        onAgentCredentialIdsChange,
        agentWiring,
        onAgentWiringAdd,
        onAgentWiringRemove,
        onWiredNodeConfigPatch,
        onWiredNodeCredentialsChange,
        getWiredNodeData,
    },
    ref
) {
    const { width, containerRef, mounted } = useContainerWidth();

    // Responsive columns: fewer columns on narrow containers so blocks wrap instead of shrinking
    const cols = useMemo(() => {
        if (width >= 1024) return 12;
        if (width >= 768) return 6;
        if (width >= 480) return 4;
        return 2;
    }, [width]);

    // Restore persisted layout, reconciled with initialBlocks to pick up nodes
    // added/removed on the canvas while this component was unmounted.
    const [layout, setLayout] = useState<Layout>(() => {
        const current = initialBlocks ?? [];
        if (!savedState) {
            return current.map((b, i) => {
                const def = getBlockDefinition(b.blockType);
                return {
                    i: b.id,
                    x: 0,
                    y: i * 3,
                    w: def?.defaultW ?? 4,
                    h: def?.defaultH ?? 3,
                    minW: def?.minW,
                    minH: def?.minH,
                };
            });
        }
        // If blocks haven't loaded yet (e.g. mounting before backend responds),
        // preserve saved layout as-is — the useLayoutEffect below will reconcile once
        // savedState updates with backend data and blocks are available.
        if (current.length === 0) {
            return savedState.layout;
        }
        // Keep saved positions for blocks still on canvas, append new ones at the bottom
        const savedIds = new Set(savedState.layout.map((item) => item.i));
        const kept = savedState.layout.filter((item) =>
            current.some((b) => b.id === item.i)
        );
        const bottomY = kept.reduce(
            (max, item) => Math.max(max, item.y + item.h),
            0
        );
        const added = current
            .filter((b) => !savedIds.has(b.id))
            .map((b, i) => {
                const def = getBlockDefinition(b.blockType);
                const h = def?.defaultH ?? 3;
                return {
                    i: b.id,
                    x: 0,
                    y: bottomY + i * h,
                    w: def?.defaultW ?? 4,
                    h,
                    minW: def?.minW,
                    minH: def?.minH,
                };
            });
        return [...kept, ...added];
    });

    // Blocks are derived directly from ReactFlow node data — single source of truth.
    // No local copy, no sync code. Config changes flow through ReactFlow nodes and
    // propagate back naturally via initialBlocks prop updates.
    const blocks = useMemo<PlacedBlock[]>(() => {
        return (initialBlocks ?? []).map((b) => {
            const def = getBlockDefinition(b.blockType);
            const nd = (b.nodeData || {}) as Record<string, unknown>;
            // Support both frontend format (nd.config nested) and backend format (nd is flat config).
            // Frontend: nd = { config: { ... }, operation, output, ... }
            // Backend:  nd = { field1, field2, operation, output, ... } — nd.config is undefined
            const nestedConfig = nd.config as BlockConfig | undefined;
            let config: BlockConfig;
            let operation: string | undefined;
            if (nestedConfig !== undefined) {
                // Frontend format: config lives under nd.config; metadata is top-level on nd
                config = nestedConfig;
                operation = nd.operation as string | undefined;
            } else {
                // Backend format: nd itself is the flat config; strip only runtime/metadata fields
                const {
                    operation: op,
                    output: _out,
                    _timeToFillMs: _ttf,
                    ...flatFields
                } = nd;
                config = flatFields as BlockConfig;
                operation = op as string | undefined;
            }
            return {
                id: b.id,
                type: b.blockType,
                credentialIds: nd.credentialIds as
                    | Record<string, string>
                    | undefined,
                config: {
                    ...config,
                    // Tab + grid-card title mirrors the node's own name — same resolver
                    // (and priority) as InterfaceNode's canvas header, so the tab never
                    // falls back to the block-type label while the node shows a real name.
                    label: resolveInterfaceBlockLabel(
                        nd.label as string | undefined,
                        config.label as string | undefined,
                        def?.label,
                        b.blockType
                    ),
                    ...(operation ? { operation } : {}),
                    // Runtime extras needed by BlockWrapper (not part of config model)
                    _timeToFillMs: nd._timeToFillMs,
                },
                output: nd.output as Record<string, unknown> | null | undefined,
            };
        });
    }, [initialBlocks]);

    // Tracks whether the agentic builder is currently constructing or rewriting
    // an interface. Two trigger paths:
    //   1. Initial add: node_added for an interface-html-react node — covers the
    //      window between "AI starts building" and "node drafting fills jsx_source".
    //   2. jsx_source regen: an edit is in flight and the brain is streaming a
    //      `<field name="jsx_source">` replacement on an existing html-react
    //      block (no node_added arrives, only a single node_updated at the end —
    //      so we sniff the streamed text to know a long regen is happening).
    // Cleared when the edit completes / errors.
    const [isBuildingInterface, setIsBuildingInterface] = useState(false);
    const [isEditInFlight, setIsEditInFlight] = useState(false);
    const [isJsxFieldStreaming, setIsJsxFieldStreaming] = useState(false);
    useEffect(() => {
        let jsxStreamTimeout: ReturnType<typeof setTimeout> | null = null;
        const onEdit = (e: Event) => {
            const detail = (e as CustomEvent).detail as
                | { type?: string; nodeType?: string; text?: string }
                | undefined;
            if (!detail) return;
            if (detail.type === 'started') {
                setIsEditInFlight(true);
            } else if (detail.type === 'complete' || detail.type === 'error') {
                setIsEditInFlight(false);
                setIsBuildingInterface(false);
                setIsJsxFieldStreaming(false);
                if (jsxStreamTimeout) {
                    clearTimeout(jsxStreamTimeout);
                    jsxStreamTimeout = null;
                }
            } else if (
                (detail.type === 'node_added' ||
                    detail.type === 'node_processing') &&
                detail.nodeType === 'interface-html-react'
            ) {
                setIsBuildingInterface(true);
            } else if (
                detail.type === 'text_chunk' &&
                detail.text?.includes('jsx_source')
            ) {
                // Brain is mid-stream of a `<field name="jsx_source">` payload — the
                // existing block's jsx_source will be replaced wholesale once the
                // field op lands. Surface the animation now instead of waiting for
                // the (silent) 30-60s of XML generation.
                setIsJsxFieldStreaming(true);
                if (jsxStreamTimeout) clearTimeout(jsxStreamTimeout);
                jsxStreamTimeout = setTimeout(
                    () => setIsJsxFieldStreaming(false),
                    3000
                );
            }
        };
        document.addEventListener('noclick:workflow:edit:event', onEdit);
        return () => {
            document.removeEventListener('noclick:workflow:edit:event', onEdit);
            if (jsxStreamTimeout) clearTimeout(jsxStreamTimeout);
        };
    }, []);

    // An html-react block whose jsx_source hasn't been filled yet renders as a
    // blank container, which looks broken next to the building animation. Treat
    // those blocks as "not yet renderable" — the animation overlays in their
    // place until node drafting fills the source.
    const isHtmlReactReady = (b: PlacedBlock) => {
        if (b.type !== 'html-react') return true;
        const src = b.config.jsx_source;
        return typeof src === 'string' && src.trim().length > 0;
    };
    // Used as a structural signal that an interface is mid-build, independent of
    // the node_added event timing — so the building animation keeps showing even
    // if other nodes (e.g. a file-upload) landed first and pushed blocks.length
    // above 0 before the interface node arrived.
    const hasEmptyInterfaceBlock = useMemo(
        () => blocks.some((b) => !isHtmlReactReady(b)),
        [blocks]
    );
    const hasHtmlReactBlock = useMemo(
        () => blocks.some((b) => b.type === 'html-react'),
        [blocks]
    );
    // Initial-add window: an interface block is being built and its jsx_source
    // hasn't landed yet. Regen window: an edit is mid-stream, replacing the
    // jsx_source on an existing html-react block.
    const showBuildingAnim =
        (isBuildingInterface &&
            (blocks.length === 0 || hasEmptyInterfaceBlock)) ||
        (isEditInFlight && isJsxFieldStreaming && hasHtmlReactBlock);

    // Hide unrendered interface blocks from the grid + fullscreen tabs ONLY
    // while the building animation is taking their place. Outside of an active
    // build (e.g. user drag-dropped an empty html-react node), render them
    // normally so the user can interact with the block — otherwise the tab
    // would go black (the block is filtered, but blocks.length > 0 so the
    // empty-state skeleton doesn't show either).
    const renderableBlocks = useMemo(
        () => (showBuildingAnim ? blocks.filter(isHtmlReactReady) : blocks),
        [blocks, showBuildingAnim]
    );

    // Partition blocks into fullscreen and grid sets
    const fullscreenBlocks = useMemo(
        () => renderableBlocks.filter(isFullscreen),
        [renderableBlocks]
    );
    const gridBlocks = useMemo(
        () => renderableBlocks.filter((b) => !isFullscreen(b)),
        [renderableBlocks]
    );

    // Sub-tab state: 'grid' shows the normal grid, a block ID shows that fullscreen block.
    // Initialize from initialBlocks so a workflow that opens with only a fullscreen
    // block (e.g. an agent-chat) doesn't flash an empty grid before the
    // soloFullscreen effect snaps the tab.
    const [activeSubTab, setActiveSubTab] = useState<string>(() => {
        const initial = initialBlocks ?? [];
        const fs = initial.filter(isFullscreenInitial);
        const grids = initial.filter((b) => !isFullscreenInitial(b));
        if (fs.length >= 1 && grids.length === 0) return fs[0].id;
        return 'grid';
    });
    // Tracks whether the user has manually clicked a tab this session.
    // While false, auto-correct always snaps to orderedTabIds[0] (respecting user's saved order).
    // Resets to false on unmount/remount so re-opening the Interface tab always shows the leading tab.
    const userHasSwitchedTabRef = useRef(false);
    // Brief cooldown after tab switch to suppress inline editor outline on click
    const [tabJustSwitched, setTabJustSwitched] = useState(false);
    const handleSubTabSwitch = useCallback(
        (tab: string) => {
            userHasSwitchedTabRef.current = true;
            setActiveSubTab(tab);
            onActiveSubTabChange?.(tab);
            setTabJustSwitched(true);
            setTimeout(() => setTabJustSwitched(false), 2000);
        },
        [onActiveSubTabChange]
    );

    // Persisted tab order — restored from savedState, reconciled with current blocks
    const [tabOrder, setTabOrder] = useState<string[]>(
        () => savedState?.tabOrder ?? []
    );

    // Ordered tab IDs: reconcile persisted order with current blocks (add new, remove stale)
    const orderedTabIds = useMemo(() => {
        const validIds = new Set<string>();
        if (gridBlocks.length > 0) validIds.add('grid');
        fullscreenBlocks.forEach((b) => validIds.add(b.id));
        // Keep persisted order for IDs that still exist
        const ordered = tabOrder.filter((id) => validIds.has(id));
        // Append any new IDs not in the persisted order
        const orderedSet = new Set(ordered);
        validIds.forEach((id) => {
            if (!orderedSet.has(id)) ordered.push(id);
        });
        return ordered;
    }, [tabOrder, gridBlocks, fullscreenBlocks]);

    // Tab drag-and-drop state
    const [dragTabId, setDragTabId] = useState<string | null>(null);
    // Drop indicator: { tabId, side } — shows a "|" bar before or after the target tab
    const [dropIndicator, setDropIndicator] = useState<{
        tabId: string;
        side: 'left' | 'right';
    } | null>(null);

    const handleTabDragStart = useCallback(
        (e: React.DragEvent, tabId: string) => {
            setDragTabId(tabId);
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/x-tab-id', tabId);
        },
        []
    );

    const handleTabDragOver = useCallback(
        (e: React.DragEvent, tabId: string) => {
            if (!e.dataTransfer.types.includes('text/x-tab-id')) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            // Determine left/right side based on cursor position within the tab element
            const rect = e.currentTarget.getBoundingClientRect();
            const side =
                e.clientX < rect.left + rect.width / 2 ? 'left' : 'right';
            setDropIndicator({ tabId, side });
        },
        []
    );

    const handleTabDrop = useCallback(
        (e: React.DragEvent, targetId: string) => {
            e.preventDefault();
            const sourceId = e.dataTransfer.getData('text/x-tab-id');
            const side =
                dropIndicator?.tabId === targetId
                    ? dropIndicator.side
                    : 'right';
            setDragTabId(null);
            setDropIndicator(null);
            if (!sourceId || sourceId === targetId) return;
            setTabOrder(() => {
                const ids = [...orderedTabIds];
                const srcIdx = ids.indexOf(sourceId);
                if (srcIdx === -1) return ids;
                ids.splice(srcIdx, 1);
                // Insert at the correct side of the target
                let tgtIdx = ids.indexOf(targetId);
                if (tgtIdx === -1) return ids;
                if (side === 'right') tgtIdx += 1;
                ids.splice(tgtIdx, 0, sourceId);
                return ids;
            });
        },
        [orderedTabIds, dropIndicator]
    );

    const handleTabDragEnd = useCallback(() => {
        setDragTabId(null);
        setDropIndicator(null);
    }, []);

    /** Renders a vertical drop indicator bar if the given tab/side matches the current drop position. */
    const renderDropIndicator = useCallback(
        (tabId: string, side: 'left' | 'right') => {
            if (
                !dropIndicator ||
                dropIndicator.tabId !== tabId ||
                dropIndicator.side !== side ||
                dragTabId === tabId
            )
                return null;
            return <div className="w-0.5 h-4 bg-white rounded-full shrink-0" />;
        },
        [dropIndicator, dragTabId]
    );

    // Whether to show sub-tab bar (multiple views available)
    const showSubTabs =
        fullscreenBlocks.length > 0 &&
        (gridBlocks.length > 0 || fullscreenBlocks.length > 1);
    // Single fullscreen block with no grid blocks — skip sub-tabs, show fullscreen directly
    const soloFullscreen =
        fullscreenBlocks.length === 1 && gridBlocks.length === 0;

    // Auto-correct activeSubTab when blocks change (direct setActiveSubTab — no cooldown needed)
    useEffect(() => {
        if (soloFullscreen) {
            // Single fullscreen block — always show it, no choice to be made
            const id = orderedTabIds[0] ?? fullscreenBlocks[0].id;
            setActiveSubTab(id);
            onActiveSubTabChange?.(id);
            return;
        }
        if (
            !userHasSwitchedTabRef.current &&
            orderedTabIds.length > 0 &&
            orderedTabIds[0] !== 'grid'
        ) {
            // User hasn't manually picked a tab yet (or component just remounted) — snap to the
            // leading tab in the user's saved order. This also fires when savedState arrives
            // asynchronously from IndexedDB and orderedTabIds updates, correcting the initial guess.
            setActiveSubTab(orderedTabIds[0]);
            onActiveSubTabChange?.(orderedTabIds[0]);
            return;
        }
        if (
            activeSubTab !== 'grid' &&
            !fullscreenBlocks.some((b) => b.id === activeSubTab)
        ) {
            setActiveSubTab('grid');
            onActiveSubTabChange?.('grid');
        }
    }, [
        fullscreenBlocks,
        gridBlocks,
        soloFullscreen,
        activeSubTab,
        onActiveSubTabChange,
        orderedTabIds,
    ]);

    const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
    useEffect(() => {
        updateBuilderContext({ selectedInterfaceBlockId: selectedBlockId });
    }, [selectedBlockId]);
    const [showGuides, setShowGuides] = useState(false);
    const dragOverTimeoutRef = useRef<
        ReturnType<typeof setTimeout> | undefined
    >(undefined);
    const [containerHeight, setContainerHeight] = useState(0);

    // Apply savedState changes after mount (e.g. backend data arriving after initial render
    // used a stale IndexedDB cache). Uses useLayoutEffect so the corrected layout is committed
    // before the browser paints, preventing a flash of blocks with wrong dimensions.
    const appliedSavedLayoutRef = useRef(
        savedState ? JSON.stringify(savedState.layout) : null
    );
    const appliedSavedTabOrderRef = useRef(
        savedState?.tabOrder ? JSON.stringify(savedState.tabOrder) : null
    );
    useLayoutEffect(() => {
        if (!savedState) return;
        const layoutKey = JSON.stringify(savedState.layout);
        const tabOrderKey = JSON.stringify(savedState.tabOrder ?? []);
        if (layoutKey !== appliedSavedLayoutRef.current) {
            appliedSavedLayoutRef.current = layoutKey;
            setLayout(savedState.layout);
        }
        // Apply tabOrder independently — a savedState update may bring a new tabOrder
        // with the same layout (e.g. initializeState reading IndexedDB after component mounted).
        if (tabOrderKey !== appliedSavedTabOrderRef.current) {
            appliedSavedTabOrderRef.current = tabOrderKey;
            if (savedState.tabOrder?.length) setTabOrder(savedState.tabOrder);
        }
    }, [savedState]);

    // Persist layout + tab order to parent so it survives component remounts (tab switches).
    // Skip the first fire when savedState was null at mount — the parent's IndexedDB load
    // is still pending, and reporting our derived initial state (tabOrder: []) would clobber
    // the persisted value before initializeState reads it. Once savedState arrives via the
    // useLayoutEffect above, the resulting state update triggers a subsequent fire with the
    // correct values.
    const skipFirstStateChangeRef = useRef(!savedState);
    useEffect(() => {
        if (skipFirstStateChangeRef.current) {
            skipFirstStateChangeRef.current = false;
            return;
        }
        onStateChange?.({ layout, tabOrder });
    }, [layout, tabOrder, onStateChange]);

    // Measure container height so we know how many rows fit in the viewport
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const ro = new ResizeObserver(([entry]) =>
            setContainerHeight(entry.contentRect.height)
        );
        ro.observe(el);
        return () => ro.disconnect();
    }, [containerRef]);

    // Cleanup timeout on unmount
    useEffect(() => () => clearTimeout(dragOverTimeoutRef.current), []);

    // Show column guides during internal drag/resize
    const handleDragStart = useCallback(() => setShowGuides(true), []);
    const handleResizeStart = useCallback(() => setShowGuides(true), []);

    // On drag/resize stop, persist positions of ALL items from the final layout (not just the
    // dragged/resized item). Without this, items pushed by collision prevention retain their
    // original positions in saved state, creating overlaps that the compactor resolves on remount
    // by reverting the visual order the user just set.
    const handleDragStop = useCallback(
        (
            layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null
        ) => {
            setShowGuides(false);
            if (!newItem) return;
            setLayout((prev) => {
                const posMap = new Map(layout.map((item) => [item.i, item]));
                return prev.map((item) => {
                    const pos = posMap.get(item.i);
                    return pos ? { ...item, x: pos.x, y: pos.y } : item;
                });
            });
        },
        []
    );
    const handleResizeStop = useCallback(
        (
            layout: Layout,
            _oldItem: LayoutItem | null,
            newItem: LayoutItem | null
        ) => {
            setShowGuides(false);
            if (!newItem) return;
            setLayout((prev) => {
                const posMap = new Map(layout.map((item) => [item.i, item]));
                return prev.map((item) => {
                    const pos = posMap.get(item.i);
                    return pos
                        ? { ...item, x: pos.x, y: pos.y, w: pos.w, h: pos.h }
                        : item;
                });
            });
        },
        []
    );

    // Expose imperative methods so FlowCanvas can add/remove layout items from the canvas side.
    // Block data itself comes from ReactFlow nodes via initialBlocks — no need to manage it here.
    useImperativeHandle(
        ref,
        () => ({
            addBlock: (blockId: string, blockType: string) => {
                const def = getBlockDefinition(blockType);
                if (!def) return;
                setLayout((prev) => {
                    if (prev.some((item) => item.i === blockId)) return prev;
                    const bottomY = prev.reduce(
                        (max, item) => Math.max(max, item.y + item.h),
                        0
                    );
                    return [
                        ...prev,
                        {
                            i: blockId,
                            x: 0,
                            y: bottomY,
                            w: def.defaultW,
                            h: def.defaultH,
                            minW: def.minW,
                            minH: def.minH,
                        },
                    ];
                });
            },
            removeBlock: (blockId: string) => {
                setLayout((prev) => prev.filter((item) => item.i !== blockId));
                setSelectedBlockId((current) =>
                    current === blockId ? null : current
                );
            },
            setFullState: (state: InterfaceGridState) => {
                setLayout(state.layout);
                if (state.tabOrder) setTabOrder(state.tabOrder);
            },
            setActiveSubTab: (subTabId: string) => {
                // Reuse the user-initiated handler so this counts as a "manual" switch
                // — otherwise the auto-correct effect can snap back to the first tab.
                handleSubTabSwitch(subTabId);
            },
        }),
        [handleSubTabSwitch]
    );

    const handleDrop = useCallback(
        (newLayout: Layout, droppedItem: LayoutItem | undefined, e: Event) => {
            if (!droppedItem) return;

            const dragEvent = e as unknown as DragEvent;
            const blockType = dragEvent.dataTransfer?.getData('text/plain');
            if (!blockType) return;

            const def = getBlockDefinition(blockType);
            if (!def) return;

            const newId = `block-${Date.now()}`;

            // Replace the dropping placeholder id with a real unique id and add min constraints
            setLayout(
                newLayout.map((item) =>
                    item.i === DROPPING_ITEM_ID
                        ? { ...item, i: newId, minW: def.minW, minH: def.minH }
                        : item
                )
            );
            setSelectedBlockId(newId);
            setShowGuides(false);

            // Auto-sync: create corresponding workflow node in the canvas.
            // The block will appear in `blocks` once FlowCanvas adds the node and
            // initialBlocks recalculates (batched in same React render cycle).
            if (def.nodeType && onBlockAdded) {
                onBlockAdded(newId, def.nodeType);
            }
        },
        [onBlockAdded]
    );

    const handleRemoveBlock = useCallback(
        (blockId: string) => {
            setLayout((prev) => prev.filter((item) => item.i !== blockId));
            if (selectedBlockId === blockId) {
                setSelectedBlockId(null);
            }
            // Auto-sync: remove corresponding workflow node from the canvas
            if (onBlockRemoved) {
                onBlockRemoved(blockId);
            }
        },
        [selectedBlockId, onBlockRemoved]
    );

    const handleDropDragOver = useCallback((e: React.DragEvent) => {
        // Reject if not carrying block data
        if (!e.dataTransfer?.types?.includes('text/plain')) return false;
        // Show column guides while an external block is being dragged over
        setShowGuides(true);
        clearTimeout(dragOverTimeoutRef.current);
        dragOverTimeoutRef.current = setTimeout(
            () => setShowGuides(false),
            150
        );
        // Return placeholder size for incoming blocks
        return { w: 4, h: 3 };
    }, []);

    // Config changes flow outward to ReactFlow nodes via onBlockConfigChanged.
    // The updated node data propagates back through initialBlocks → blocks useMemo.
    const handleConfigChange = useCallback(
        (blockId: string, newConfig: BlockConfig) => {
            onBlockConfigChanged?.(blockId, newConfig);
        },
        [onBlockConfigChanged]
    );

    // Renaming a sub-tab renames the interface NODE itself — the tab title and the
    // canvas node header share one name (data.label, top-level metadata). Reuse the
    // same node-data-update channel the canvas rename uses (FlowCanvas listens),
    // so the two never diverge. Empty label clears back to the default.
    const handleTabRename = useCallback((blockId: string, newLabel: string) => {
        document.dispatchEvent(
            new CustomEvent('noclick:node:update-data', {
                detail: {
                    nodeId: blockId,
                    data: { label: newLabel || undefined },
                },
            })
        );
    }, []);

    // Rows that fit in the visible viewport (no scroll). Falls back to 10 until measured.
    const visibleRows = useMemo(() => {
        if (containerHeight <= 0) return 10;
        return Math.floor(
            (containerHeight - GRID_CPAD[1] * 2 + GRID_MARGIN[1]) /
                (ROW_H + GRID_MARGIN[1])
        );
    }, [containerHeight]);

    // Guide rows: fill the viewport when content is small, extend past content when it grows.
    const guideRows = useMemo(() => {
        const contentBottom = layout.reduce(
            (max, item) =>
                Number.isFinite(item.y) ? Math.max(max, item.y + item.h) : max,
            0
        );
        return Math.max(visibleRows, contentBottom + 8);
    }, [layout, visibleRows]);

    // Compute layout with min constraints, clamp to current cols, and resolve any overlaps.
    // Only include items whose block exists in gridBlocks — fullscreen blocks are excluded from the grid.
    const layoutWithConstraints = useMemo(() => {
        const blockMap = new Map(gridBlocks.map((b) => [b.id, b]));
        // 1. Keep only items with a matching grid block, then clamp to responsive column count
        const clamped = layout
            .filter((item) => blockMap.has(item.i))
            .map((item) => {
                const def = getBlockDefinition(blockMap.get(item.i)!.type);
                const w = Math.min(item.w, cols);
                const x = Math.min(item.x, Math.max(0, cols - w));
                return {
                    ...item,
                    x,
                    w,
                    minW: Math.min(item.minW ?? def?.minW ?? 1, cols),
                    minH: item.minH ?? def?.minH,
                };
            });
        // 2. Resolve collisions: process top-to-bottom and push overlapping items down
        const sorted = [...clamped].sort((a, b) => a.y - b.y || a.x - b.x);
        const resolved: LayoutItem[] = [];
        for (const item of sorted) {
            let y = item.y;
            let pushed = true;
            while (pushed) {
                pushed = false;
                for (const placed of resolved) {
                    if (
                        item.x < placed.x + placed.w &&
                        item.x + item.w > placed.x &&
                        y < placed.y + placed.h &&
                        y + item.h > placed.y
                    ) {
                        y = placed.y + placed.h;
                        pushed = true;
                        break;
                    }
                }
            }
            resolved.push({ ...item, y });
        }
        return resolved;
    }, [layout, gridBlocks, cols]);

    // Active fullscreen block (if showing one). When we're in the soloFullscreen
    // bootstrap window — activeSubTab still 'grid' but there are fullscreen blocks
    // and no grid blocks — fall back to the first fullscreen block so we don't
    // render an empty grid for one frame.
    const activeFullscreenBlock =
        activeSubTab !== 'grid'
            ? fullscreenBlocks.find((b) => b.id === activeSubTab)
            : fullscreenBlocks.length > 0 && gridBlocks.length === 0
              ? fullscreenBlocks[0]
              : undefined;

    return (
        <div className="flex-1 relative min-h-0 bg-background flex flex-col">
            {/* Sub-tab bar for switching between grid and fullscreen blocks */}
            {showSubTabs && (
                <div
                    className="flex items-center px-2 border-b border-border bg-sunken shrink-0"
                    style={{ height: 34 }}
                >
                    <div className="flex items-center gap-1 flex-1 min-w-0">
                        {orderedTabIds.map((tabId) => {
                            if (tabId === 'grid') {
                                return (
                                    <React.Fragment key="grid">
                                        {!isReadOnly &&
                                            renderDropIndicator('grid', 'left')}
                                        <button
                                            draggable={!isReadOnly}
                                            onClick={() =>
                                                handleSubTabSwitch('grid')
                                            }
                                            onDragStart={
                                                isReadOnly
                                                    ? undefined
                                                    : (e) =>
                                                          handleTabDragStart(
                                                              e,
                                                              'grid'
                                                          )
                                            }
                                            onDragOver={
                                                isReadOnly
                                                    ? undefined
                                                    : (e) =>
                                                          handleTabDragOver(
                                                              e,
                                                              'grid'
                                                          )
                                            }
                                            onDrop={
                                                isReadOnly
                                                    ? undefined
                                                    : (e) =>
                                                          handleTabDrop(
                                                              e,
                                                              'grid'
                                                          )
                                            }
                                            onDragEnd={
                                                isReadOnly
                                                    ? undefined
                                                    : handleTabDragEnd
                                            }
                                            className={`px-2.5 h-[26px] text-xs font-medium rounded transition-colors ${
                                                isReadOnly
                                                    ? 'cursor-pointer'
                                                    : 'cursor-grab active:cursor-grabbing'
                                            } ${
                                                dragTabId === 'grid'
                                                    ? 'opacity-40'
                                                    : ''
                                            } ${
                                                activeSubTab === 'grid'
                                                    ? 'text-foreground bg-foreground/10'
                                                    : 'text-muted-foreground hover:text-foreground hover:bg-foreground/5'
                                            }`}
                                        >
                                            Default
                                        </button>
                                        {!isReadOnly &&
                                            renderDropIndicator(
                                                'grid',
                                                'right'
                                            )}
                                    </React.Fragment>
                                );
                            }
                            const b = fullscreenBlocks.find(
                                (fb) => fb.id === tabId
                            );
                            if (!b) return null;
                            const tabLabel =
                                (b.config.label as string) ||
                                'Custom Component';
                            const isActive = activeSubTab === b.id;
                            const isDragging = dragTabId === b.id;
                            return (
                                <React.Fragment key={b.id}>
                                    {!isReadOnly &&
                                        renderDropIndicator(b.id, 'left')}
                                    <div
                                        draggable={!isReadOnly}
                                        onDragStart={
                                            isReadOnly
                                                ? undefined
                                                : (e) =>
                                                      handleTabDragStart(
                                                          e,
                                                          b.id
                                                      )
                                        }
                                        onDragOver={
                                            isReadOnly
                                                ? undefined
                                                : (e) =>
                                                      handleTabDragOver(e, b.id)
                                        }
                                        onDrop={
                                            isReadOnly
                                                ? undefined
                                                : (e) => handleTabDrop(e, b.id)
                                        }
                                        onDragEnd={
                                            isReadOnly
                                                ? undefined
                                                : handleTabDragEnd
                                        }
                                        className={`rounded h-[26px] flex items-center ${
                                            isReadOnly
                                                ? 'cursor-pointer'
                                                : 'cursor-grab active:cursor-grabbing'
                                        } ${
                                            isDragging ? 'opacity-40' : ''
                                        } ${isActive ? 'bg-foreground/10 px-0.5' : ''}`}
                                    >
                                        {isActive ? (
                                            tabJustSwitched || isReadOnly ? (
                                                <span className="text-xs font-medium text-foreground px-1.5 leading-normal border border-transparent">
                                                    {tabLabel}
                                                </span>
                                            ) : (
                                                <InlineTextEditor
                                                    value={tabLabel}
                                                    placeholder="Tab name"
                                                    maxWidth={200}
                                                    className="inline-flex"
                                                    inputClassName="!text-xs !text-foreground !bg-transparent !border-foreground/30 !py-0"
                                                    spanClassName="!text-xs !text-foreground !py-0"
                                                    onSave={(newLabel) =>
                                                        handleTabRename(
                                                            b.id,
                                                            newLabel
                                                        )
                                                    }
                                                />
                                            )
                                        ) : (
                                            <button
                                                onClick={() =>
                                                    handleSubTabSwitch(b.id)
                                                }
                                                className="px-2.5 h-[26px] text-xs font-medium rounded transition-colors truncate max-w-[200px] text-muted-foreground hover:text-foreground hover:bg-foreground/5"
                                            >
                                                {tabLabel}
                                            </button>
                                        )}
                                    </div>
                                    {!isReadOnly &&
                                        renderDropIndicator(b.id, 'right')}
                                </React.Fragment>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Fullscreen block views — render all, show only active */}
            {fullscreenBlocks.map((b) => (
                <div
                    key={b.id}
                    className="flex-1 min-h-0"
                    style={{
                        display:
                            activeFullscreenBlock?.id === b.id
                                ? 'flex'
                                : 'none',
                    }}
                >
                    <BlockRenderer
                        blockType={b.type}
                        id={b.id}
                        config={b.config}
                        output={b.output}
                        isSelected={false}
                        onConfigChange={
                            isReadOnly
                                ? () => {}
                                : (config) => handleConfigChange(b.id, config)
                        }
                        isReadOnly={isReadOnly}
                        onInteraction={onReadOnlyInteraction}
                        workflowId={workflowId}
                        onAgentChatSend={onAgentChatSend}
                        credentialIds={b.credentialIds}
                        onCredentialIdsChange={
                            isReadOnly || !onAgentCredentialIdsChange
                                ? undefined
                                : (ids) => onAgentCredentialIdsChange(b.id, ids)
                        }
                        agentWiring={agentWiring?.[b.id]}
                        onAgentWiringAdd={
                            isReadOnly || !onAgentWiringAdd
                                ? undefined
                                : (nodeType, role, operation) =>
                                      onAgentWiringAdd(
                                          b.id,
                                          nodeType,
                                          role,
                                          operation
                                      )
                        }
                        onAgentWiringRemove={
                            isReadOnly ? undefined : onAgentWiringRemove
                        }
                        onWiredNodeConfigPatch={
                            isReadOnly ? undefined : onWiredNodeConfigPatch
                        }
                        onWiredNodeCredentialsChange={
                            isReadOnly
                                ? undefined
                                : onWiredNodeCredentialsChange
                        }
                        getWiredNodeData={getWiredNodeData}
                    />
                </div>
            ))}

            {/* Grid view — always mounted (display:none when a fullscreen tab is active)
          so containerRef stays attached and layout survives tab switches */}
            <div
                className="flex-1 relative min-h-0 overflow-auto scrollbar-subtle"
                style={{ display: activeFullscreenBlock ? 'none' : undefined }}
            >
                <div ref={containerRef} className="relative h-full">
                    {mounted && width > 0 ? (
                        <>
                            {/* Cell grid guides — uses same containerPadding as GridLayout for pixel-perfect alignment */}
                            <GridBackground
                                width={width}
                                cols={cols}
                                rowHeight={ROW_H}
                                margin={GRID_MARGIN}
                                containerPadding={GRID_CPAD}
                                rows={guideRows}
                                color="rgba(113,113,122,0.06)"
                                borderRadius={CELL_RADIUS}
                                className={`z-0 transition-opacity duration-150 ${showGuides ? 'opacity-100' : 'opacity-0'}`}
                            />
                            {/* Always render GridLayout so it can receive external drops */}
                            <GridLayout
                                layout={layoutWithConstraints}
                                width={width}
                                gridConfig={{
                                    cols,
                                    rowHeight: ROW_H,
                                    margin: GRID_MARGIN,
                                    containerPadding: GRID_CPAD,
                                }}
                                compactor={freeFormCompactor}
                                dragConfig={{
                                    enabled: !isReadOnly,
                                    cancel: '.block-content',
                                }}
                                resizeConfig={{ enabled: !isReadOnly }}
                                dropConfig={{ enabled: !isReadOnly }}
                                droppingItem={droppingItemTemplate}
                                onDrop={isReadOnly ? undefined : handleDrop}
                                onDropDragOver={
                                    isReadOnly ? undefined : handleDropDragOver
                                }
                                onDragStart={
                                    isReadOnly ? undefined : handleDragStart
                                }
                                onDragStop={
                                    isReadOnly ? undefined : handleDragStop
                                }
                                onResizeStart={
                                    isReadOnly ? undefined : handleResizeStart
                                }
                                onResizeStop={
                                    isReadOnly ? undefined : handleResizeStop
                                }
                                className="workflow-interface-grid"
                                style={{ minHeight: '100%' }}
                                autoSize
                            >
                                {gridBlocks.map((block) => (
                                    <div key={block.id}>
                                        <BlockWrapper
                                            blockType={block.type}
                                            label={block.config.label}
                                            isSelected={
                                                !isReadOnly &&
                                                selectedBlockId === block.id
                                            }
                                            isLoading={
                                                loadingBlockIds?.has(
                                                    block.id
                                                ) ?? false
                                            }
                                            estimatedDurationMs={
                                                block.config._timeToFillMs as
                                                    | number
                                                    | undefined
                                            }
                                            onSelect={
                                                isReadOnly
                                                    ? () => {}
                                                    : () =>
                                                          setSelectedBlockId(
                                                              block.id
                                                          )
                                            }
                                            onRemove={
                                                isReadOnly ||
                                                block.type === 'dataframe'
                                                    ? undefined
                                                    : () =>
                                                          handleRemoveBlock(
                                                              block.id
                                                          )
                                            }
                                        >
                                            <BlockRenderer
                                                blockType={block.type}
                                                id={block.id}
                                                config={block.config}
                                                output={block.output}
                                                isSelected={
                                                    !isReadOnly &&
                                                    selectedBlockId === block.id
                                                }
                                                onConfigChange={
                                                    isReadOnly
                                                        ? () => {}
                                                        : (config) =>
                                                              handleConfigChange(
                                                                  block.id,
                                                                  config
                                                              )
                                                }
                                                onSubmit={
                                                    block.type === 'form' &&
                                                    !isReadOnly
                                                        ? (values) =>
                                                              onFormSubmit?.(
                                                                  block.id,
                                                                  values
                                                              )
                                                        : undefined
                                                }
                                                isReadOnly={isReadOnly}
                                                onInteraction={
                                                    onReadOnlyInteraction
                                                }
                                            />
                                        </BlockWrapper>
                                    </div>
                                ))}
                            </GridLayout>
                            {/* Empty state overlay - pointer-events-none so drops pass through to grid.
                  Editable: always show the wireframe skeleton (covers initial sync without
                  flashing a text label). Read-only: show "No Interface" since there's
                  nothing for the viewer to build. */}
                            {blocks.length === 0 &&
                                (isReadOnly ? (
                                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                        <div className="flex flex-col items-center gap-4 text-muted-foreground/70 dark:text-zinc-600">
                                            <LayoutGrid className="w-12 h-12" />
                                            <div className="text-center">
                                                <p className="text-sm font-medium text-muted-foreground">
                                                    No Interface
                                                </p>
                                                <p className="text-xs text-muted-foreground/70 dark:text-zinc-600 mt-1">
                                                    This workflow has no
                                                    interface blocks
                                                </p>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <InterfaceSkeleton />
                                ))}
                        </>
                    ) : null}
                </div>
            </div>
            {/* Building animation shows while we're actively constructing OR
          regenerating an interface block — overlays the whole content area
          (including any active fullscreen html-react view) so the user sees
          progress whether the block is empty or being rewritten. */}
            {showBuildingAnim && (
                <div
                    className="absolute inset-x-0 bottom-0 pointer-events-none"
                    style={{ top: showSubTabs ? 34 : 0 }}
                >
                    <InterfaceBuildingAnimation />
                </div>
            )}
        </div>
    );
});
