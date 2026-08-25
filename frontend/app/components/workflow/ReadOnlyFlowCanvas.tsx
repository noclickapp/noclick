/**
 * ReadOnlyFlowCanvas - Simplified ReactFlow canvas for public workflow viewing.
 * Displays nodes and edges without editing capabilities.
 * Supports pan/zoom but disables all modification interactions.
 * Matches FlowCanvas styling for consistent appearance.
 */

import {
    useMemo,
    useCallback,
    useState,
    useRef,
    useEffect,
    type ComponentType,
} from 'react';
import { useIsMobile, useMediaQuery } from '~/hooks/useIsMobile';
import { useCtrlPan } from '~/hooks/useCtrlPan';
import { CanvasBackground } from '~/components/workflow/canvasBackground';
import {
    ReactFlow,
    ReactFlowProvider,
    useReactFlow,
    useNodesInitialized,
    useNodesState,
    useEdgesState,
    applyNodeChanges,
    type Node,
    type Edge,
    type FitViewOptions,
    type OnSelectionChangeFunc,
    type NodeChange,
    type OnNodeDrag,
} from '@xyflow/react';
import { perfState } from '~/lib/perf-state';
import '@xyflow/react/dist/style.css';
// nodeRegistry is dynamically imported so its ~92 node-component modules
// only load once the desktop canvas mounts (mobile takes the ForkCanvas path).
import AnimatedWorkflowEdge from './edges/AnimatedWorkflowEdge';
import { ReadOnlyFlowHelperView } from './ReadOnlyFlowHelperView';
import { applyEdgeStyle } from '~/utils/workflowLayout';
import {
    applyNodeUpdate,
    createWorkflowNode,
    updateNodeInList,
    normalizeNodeUpdatePayload,
} from '~/lib/applyNodeUpdate';
import { ForkCanvas } from './forkflow/ForkCanvas';
import { loadNodeDefsFor } from './nodeRegistryLazy';
import type { NodeDefinition } from './nodes/types';
import type { NodeEditInfo } from './WorkflowContext';
import { DndProvider } from '~/providers/DndProvider';

// Pro options to hide attribution
const proOptions = { hideAttribution: true };

// Edge types
const edgeTypes = {
    animated: AnimatedWorkflowEdge,
};

// Default edge options
const defaultEdgeOptions = {
    type: 'animated',
    animated: false,
};

interface ReadOnlyFlowCanvasProps {
    nodes: Node[];
    edges: Edge[];
    onForkPrompt?: () => void;
    isEmbed?: boolean;
    // Execution replay: overlay per-node runtime state (executionState / error /
    // output) onto the read-only graph so a past run renders with the same
    // status visuals a live run does, and surface node selection so the host can
    // lazily fetch a node's output. Both optional — unset = the plain share view.
    runtimeByNodeId?: Record<
        string,
        {
            executionState?: string;
            error?: string;
            output?: any;
            outputTimestamp?: number;
        }
    >;
    /** Optional live/replay edge state. The production animated edge restarts
     *  its one-shot travel bead on false -> true transitions, so read-only
     *  product stories can show the same execution hand-off as the editor
     *  without substituting a marketing-only SVG graph. */
    edgeRuntimeById?: Record<string, { isAnimating?: boolean }>;
    /** Opt-in product-preview state. Uses the production node editing UI while
     * keeping the read-only canvas isolated from the live editor singleton. */
    editInfoByNodeId?: Record<string, NodeEditInfo | undefined>;
    onNodeSelect?: (nodeId: string | null) => void;
    // Opt-in: allow dragging nodes to reposition them (default false keeps the
    // public share view non-editable). Used by the thumbnail generator to let
    // users arrange the graph for a screenshot.
    nodesDraggable?: boolean;
    // Max interactive zoom (default 1.25). The thumbnail generator raises this so
    // users can scale nodes up for a bolder screenshot.
    maxZoom?: number;
    // Optional cap used specifically by fitView. This lets incremental builder
    // stories keep enough surrounding canvas visible before the next node lands.
    fitViewMaxZoom?: number;
    /** Optional fitView padding (number, `Npx`/`N%`, or per-side). Product
     * scenes that float another window over the canvas pass an asymmetric
     * padding so the graph frames itself into the clear area. */
    fitViewPadding?: FitViewOptions['padding'];
    /** Keep the camera fixed after the graph's first measured fit. Product
     * stories use this when runtime/edit state changes should animate inside a
     * stable composition rather than making the whole canvas reframe. */
    refitOnNodeChanges?: boolean;
    /** Optional duration for measured-node re-fits. The live builder uses a
     * 500ms fit while streamed nodes settle into their autolayout positions. */
    refitDuration?: number;
    /** Let scroll gestures pass straight through to the page, and on touch
     * devices the drag/pinch gestures too. Marketing scenes set this: a canvas
     * that pans on wheel traps the page scroll, and on a phone one that claims
     * the drag makes the whole section impossible to scroll past. Mouse
     * panning, zooming and node dragging are untouched. */
    passiveViewport?: boolean;
}

const getDefaultPanelHeight = () => {
    if (typeof window === 'undefined') return 400;
    return Math.round(window.innerHeight * 0.4);
};

const getSelectedPanelHeight = () => {
    if (typeof window === 'undefined') return 540;
    return Math.round(window.innerHeight * 0.55);
};

function ReadOnlyFlowCanvasInner({
    nodes: initialNodes,
    edges: initialEdges,
    onForkPrompt,
    isEmbed = false,
    runtimeByNodeId,
    edgeRuntimeById,
    editInfoByNodeId,
    onNodeSelect,
    nodesDraggable = false,
    maxZoom = 1.25,
    fitViewMaxZoom = 1.2,
    fitViewPadding = 0.2,
    refitOnNodeChanges = true,
    refitDuration,
    passiveViewport = false,
}: ReadOnlyFlowCanvasProps) {
    // Touch has no equivalent of "scroll the page but pan with the middle
    // button": the same drag either moves the canvas or the page. On a coarse
    // pointer the page wins.
    const coarsePointer = useMediaQuery('(hover: none) and (pointer: coarse)');
    const passiveGestures = passiveViewport && coarsePointer;
    const { fitView, getNodes } = useReactFlow();
    const [selectedNode, setSelectedNode] = useState<Node | null>(null);
    const [panelHeight, setPanelHeight] = useState(getDefaultPanelHeight);
    const [isPanelExpanded, setIsPanelExpanded] = useState(false);
    const [activeTab, setActiveTab] = useState<
        'nodes' | 'config' | 'credentials'
    >('nodes');
    const panelContainerRef = useRef<HTMLDivElement>(null);

    // Redirect node-tile clicks to the fork prompt.
    useEffect(() => {
        if (!onForkPrompt) return;
        const handler = () => onForkPrompt();
        document.addEventListener(
            'noclick:add-connected-node',
            handler as EventListener
        );
        return () =>
            document.removeEventListener(
                'noclick:add-connected-node',
                handler as EventListener
            );
    }, [onForkPrompt]);

    // Some nodes (interface-config-form) render their own buttons / inputs
    // directly on the canvas (e.g. "Connect Google"). Intercept clicks /
    // typing on those interactive elements at the canvas root and route to
    // the fork prompt before any handler runs.
    const canvasInteractionRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const root = canvasInteractionRef.current;
        if (!root || !onForkPrompt) return;
        const interactiveSelector =
            'button, input, textarea, select, [role="button"], a, [contenteditable="true"]';
        const intercept = (e: Event) => {
            const target = e.target as HTMLElement | null;
            if (!target) return;
            const inNode = target.closest('.react-flow__node');
            if (!inNode) return;
            if (!target.closest(interactiveSelector)) return;
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            if (e.type === 'click' || e.type === 'keydown') onForkPrompt();
        };
        root.addEventListener('mousedown', intercept, true);
        root.addEventListener('click', intercept, true);
        root.addEventListener('keydown', intercept, true);
        return () => {
            root.removeEventListener('mousedown', intercept, true);
            root.removeEventListener('click', intercept, true);
            root.removeEventListener('keydown', intercept, true);
        };
    }, [onForkPrompt]);

    const canvasRef = useRef<HTMLDivElement>(null);
    const panActivationKeyCode = useCtrlPan(canvasRef);

    // nodeTypes is lazily resolved from the eager registry — the registry
    // pulls in all ~92 node-component modules, so we keep it out of the
    // initial bundle and hydrate the map asynchronously.
    const [nodeTypes, setNodeTypes] = useState<
        Record<string, ComponentType<any>>
    >({});
    useEffect(() => {
        let cancelled = false;
        import('./nodes/nodeRegistry').then((m) => {
            if (cancelled) return;
            setNodeTypes(m.buildReactFlowNodeTypes());
        });
        return () => {
            cancelled = true;
        };
    }, []);

    // Process nodes to ensure they have proper styling for read-only mode.
    // Parse backend format (node.config) into proper data model via createWorkflowNode.
    const processedInitialNodes = useMemo(() => {
        return initialNodes.map((node) => {
            const backendNode = node as any;
            if (!backendNode.config) {
                console.error(
                    '[ReadOnlyFlowCanvas] Node missing config:',
                    node
                );
                throw new Error(
                    `Node ${node.id} is missing config from backend`
                );
            }
            const parsed = createWorkflowNode(
                node.id,
                node.type || 'default',
                node.position,
                backendNode.config,
                {
                    isReadOnly: true,
                    ...(backendNode.previewHidden
                        ? { _previewHidden: true }
                        : {}),
                    ...(runtimeByNodeId?.[node.id] || {}),
                    ...(editInfoByNodeId
                        ? {
                              _previewEditInfo:
                                  editInfoByNodeId[node.id] ?? null,
                          }
                        : {}),
                }
            );
            return {
                ...parsed,
                draggable: nodesDraggable,
                selectable: true,
                // Reserved nodes hold their place for the camera and must paint
                // NOTHING. Inline `visibility: hidden` alone is escapable — any
                // descendant that sets its own visibility (transition libraries
                // do) paints on top of an invisible card. The class carries an
                // !important rule over the whole subtree.
                ...(backendNode.previewHidden
                    ? { className: 'nc-node-reserved' }
                    : {}),
                ...(backendNode.style || backendNode.width || backendNode.height
                    ? {
                          style: {
                              ...(backendNode.style || {}),
                              ...(backendNode.width
                                  ? { width: backendNode.width }
                                  : {}),
                              ...(backendNode.height
                                  ? { height: backendNode.height }
                                  : {}),
                          },
                      }
                    : {}),
            };
        });
    }, [editInfoByNodeId, initialNodes, runtimeByNodeId, nodesDraggable]);

    const processedInitialEdges = useMemo(() => {
        return initialEdges.map((edge) => ({
            ...applyEdgeStyle(edge),
            animated: false,
            data: {
                ...(edge.data || {}),
                ...(edgeRuntimeById?.[edge.id] || {}),
                isReadOnly: true,
            },
        }));
    }, [initialEdges, edgeRuntimeById]);

    // Use ReactFlow's state hooks for proper selection handling
    const [nodes, setNodes] = useNodesState<Node>(processedInitialNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(
        processedInitialEdges
    );
    const layoutSignature = (nodes: Node[]) =>
        nodes
            .map(
                (node) =>
                    `${node.id}@${Math.round(node.position.x)},${Math.round(node.position.y)}`
            )
            .join('|');
    const previousLayoutRef = useRef(layoutSignature(processedInitialNodes));

    // Public product stories can add nodes incrementally while the canvas is
    // already mounted. Reconcile those prop changes in place so the real node
    // editing transition remains visible; remounting ReactFlow for every step
    // briefly rendered fallback nodes while the lazy registry reloaded.
    useEffect(() => {
        const nextLayout = layoutSignature(processedInitialNodes);
        const layoutChanged = previousLayoutRef.current !== nextLayout;
        previousLayoutRef.current = nextLayout;

        setNodes((current) => {
            const byId = new Map(current.map((node) => [node.id, node]));
            return processedInitialNodes.map((incoming) => {
                const existing = byId.get(incoming.id);
                if (!existing) return incoming;
                return {
                    ...incoming,
                    // A builder mutation arrives with a freshly autolayouted
                    // graph, and that layout is authoritative: mixing new
                    // coordinates with stale ones leaves nodes overlapping or
                    // outside the fitted viewport. Keyed on the coordinates
                    // themselves rather than on membership — a story can reveal
                    // a node that was already holding its place, which re-lays
                    // the row out without changing the node set. User drags
                    // survive every update that carries no new layout.
                    position:
                        nodesDraggable && !layoutChanged
                            ? existing.position
                            : incoming.position,
                    selected: existing.selected,
                    zIndex: existing.selected ? 1002 : incoming.zIndex,
                };
            });
        });
    }, [nodesDraggable, processedInitialNodes, setNodes]);

    useEffect(() => {
        setEdges(processedInitialEdges);
    }, [processedInitialEdges, setEdges]);

    // Replay: overlay lazily-updated runtime state (e.g. a node's output fetched
    // on selection) onto the live nodes without resetting positions/selection.
    useEffect(() => {
        if (!runtimeByNodeId) return;
        setNodes((nds) =>
            nds.map((n) => {
                const rt = runtimeByNodeId[n.id];
                return rt ? applyNodeUpdate(n, { extras: rt }) : n;
            })
        );
    }, [runtimeByNodeId, setNodes]);

    useEffect(() => {
        setNodes((current) =>
            current.map((node) =>
                applyNodeUpdate(node, {
                    extras: {
                        ...(editInfoByNodeId
                            ? {
                                  _previewEditInfo:
                                      editInfoByNodeId[node.id] ?? null,
                              }
                            : {}),
                    },
                })
            )
        );
    }, [editInfoByNodeId, setNodes]);

    useEffect(() => {
        if (!edgeRuntimeById) return;
        setEdges((current) =>
            current.map((edge) => ({
                ...edge,
                data: {
                    ...(edge.data || {}),
                    ...(edgeRuntimeById[edge.id] || {
                        isAnimating: false,
                    }),
                    isReadOnly: true,
                },
            }))
        );
    }, [edgeRuntimeById, setEdges]);

    // Custom onNodesChange that allows selection, position, and dimension changes (blocks delete, add, etc.)
    const onNodesChange = useCallback(
        (changes: NodeChange[]) => {
            const allowedChanges = changes.filter(
                (change) =>
                    change.type === 'select' ||
                    change.type === 'position' ||
                    change.type === 'dimensions'
            );
            if (allowedChanges.length > 0) {
                setNodes((nds) =>
                    (applyNodeChanges(allowedChanges, nds) as typeof nds).map(
                        (node) => ({
                            ...node,
                            // NodeToolbar content lives inside the node stacking
                            // context. Keep a selected node above React Flow's
                            // edge-label layer so the compact "to edit" affordance
                            // is never crossed by a connected edge.
                            zIndex: node.selected ? 1002 : 0,
                        })
                    )
                );
            }
        },
        [setNodes]
    );

    // Drag performance optimizations - add perf-optimizing class to disable CSS transitions/blur
    const isDraggingRef = useRef(false);

    const onNodeDragStart: OnNodeDrag = useCallback(() => {
        if (!isDraggingRef.current) {
            isDraggingRef.current = true;
            canvasRef.current?.classList.add('perf-optimizing');
            perfState.shouldOptimize = true;
        }
    }, []);

    const onNodeDragStop: OnNodeDrag = useCallback(() => {
        if (isDraggingRef.current) {
            isDraggingRef.current = false;
            canvasRef.current?.classList.remove('perf-optimizing');
            perfState.shouldOptimize = false;
        }
    }, []);

    // Enable copy functionality (Cmd/Ctrl+C) for selected nodes
    useEffect(() => {
        const handleCopy = async (event: ClipboardEvent) => {
            // Don't intercept if user is in an editable element
            const activeElement = document.activeElement;
            const isEditableElement =
                activeElement instanceof HTMLInputElement ||
                activeElement instanceof HTMLTextAreaElement ||
                activeElement?.getAttribute('contenteditable') === 'true';

            // Don't intercept if user has text selected
            const selection = window.getSelection();
            const hasTextSelection =
                selection && selection.toString().length > 0;

            if (isEditableElement || hasTextSelection) return;

            // Get currently selected nodes
            const selectedNodes = nodes.filter((node) => node.selected);
            if (selectedNodes.length === 0) return;

            // Prevent default copy behavior
            event.preventDefault();

            // Get edges that connect selected nodes
            const selectedNodeIds = new Set(selectedNodes.map((n) => n.id));
            const selectedEdges = edges.filter(
                (edge) =>
                    selectedNodeIds.has(edge.source) &&
                    selectedNodeIds.has(edge.target)
            );

            // Create clipboard data in NoClick format
            const clipboardData = {
                type: 'noclick-workflow',
                version: '1.0',
                nodes: selectedNodes.map((node) => {
                    const {
                        executionState,
                        output,
                        outputTimestamp,
                        error,
                        isReadOnly,
                        ...config
                    } = node.data;
                    return {
                        id: node.id,
                        type: node.type,
                        position: node.position,
                        config,
                    };
                }),
                edges: selectedEdges.map((edge) => ({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    sourceHandle: edge.sourceHandle,
                    targetHandle: edge.targetHandle,
                    type: edge.type,
                })),
            };

            try {
                await navigator.clipboard.writeText(
                    JSON.stringify(clipboardData, null, 2)
                );
                console.log(
                    `[ReadOnly] Copied ${selectedNodes.length} nodes and ${selectedEdges.length} edges to clipboard`
                );
            } catch (err) {
                console.error('Failed to copy to clipboard:', err);
            }
        };

        window.addEventListener('copy', handleCopy);
        return () => window.removeEventListener('copy', handleCopy);
    }, [nodes, edges]);

    // Fit view options — lower maxZoom to show the full workflow including looping edges.
    const fitViewOptions = useMemo(
        () => ({
            padding: fitViewPadding,
            maxZoom: fitViewMaxZoom,
            // A scripted re-fit runs while the nodes themselves glide to new
            // autolayout slots. d3's default zoom interpolation arcs through
            // scale space, which detaches the camera from that straight-line
            // glide; linear keeps the two travelling together.
            ...(refitDuration == null
                ? {}
                : { interpolate: 'linear' as const }),
        }),
        [fitViewMaxZoom, fitViewPadding, refitDuration]
    );

    // Always fit view on init to auto-center at optimal zoom; saved viewport
    // from the editor won't match read-only container dimensions.
    // fitView with no `nodes` filter intermittently fits only the first node's
    // bounds (leaving the rest clipped); passing the explicit node list makes it
    // frame the whole graph reliably.
    const fitAll = useCallback(
        (duration?: number) =>
            fitView({
                ...fitViewOptions,
                duration,
                nodes: getNodes().map((n) => ({ id: n.id })),
            }),
        [fitView, getNodes, fitViewOptions]
    );

    const onInit = useCallback(() => {
        setTimeout(() => fitAll(300), 50);
    }, [fitAll]);

    // The node components load asynchronously (lazy registry), so the onInit fit
    // can run before nodes have real dimensions and leave some clipped. Re-fit once
    // every node has been measured (retry across a couple frames for late measurers).
    const nodesInitialized = useNodesInitialized();
    const hasMeasuredInitialFit = useRef(false);
    const lastFitSignature = useRef<string | null>(null);
    useEffect(() => {
        if (!nodesInitialized) return;
        if (!refitOnNodeChanges && hasMeasuredInitialFit.current) return;
        // Which composition the camera is framing: the node set and their
        // positions. Deliberately NOT their measured size — a card resizing
        // into or out of its AI-editing state re-measures every frame for
        // 300ms, and chasing that keeps the camera moving long after the
        // layout has settled. A node that mounts already-expanded is measured
        // expanded, so the first fit already frames it.
        const signature = getNodes()
            .map(
                (node) =>
                    `${node.id}:${Math.round(node.position.x)},${Math.round(node.position.y)}`
            )
            .join('|');
        if (refitDuration != null && lastFitSignature.current === signature) {
            return;
        }
        lastFitSignature.current = signature;
        hasMeasuredInitialFit.current = true;
        // An animated re-fit starts on the next frame, so the camera and the
        // nodes' own position transition begin together — a longer delay
        // leaves the camera still travelling after the layout has settled.
        // The two retries remain for static read-only canvases whose lazy
        // node modules may measure late.
        const delays = refitDuration == null ? [30, 250] : [16];
        const timers = delays.map((d) =>
            setTimeout(() => fitAll(refitDuration), d)
        );
        return () => timers.forEach(clearTimeout);
    }, [nodesInitialized, fitAll, getNodes, refitDuration, refitOnNodeChanges]);

    // Persist on-node edits (e.g. label rename) when the canvas is editable
    // (nodesDraggable). Node components dispatch the same event the editor
    // consumes; without a listener the edit reverts on the next render.
    useEffect(() => {
        if (!nodesDraggable) return;
        const handler = (event: Event) => {
            const { nodeId, data } = (
                event as CustomEvent<{
                    nodeId: string;
                    data: Record<string, unknown>;
                }>
            ).detail;
            setNodes((nds) =>
                updateNodeInList(nds, nodeId, normalizeNodeUpdatePayload(data))
            );
        };
        document.addEventListener('noclick:node:update-data', handler);
        return () =>
            document.removeEventListener('noclick:node:update-data', handler);
    }, [nodesDraggable, setNodes]);

    // Auto-opens collapse on deselect; manual opens (Flow Helper button) don't.
    const autoExpandedRef = useRef(false);

    // Handle node selection
    const onSelectionChange: OnSelectionChangeFunc = useCallback(
        ({ nodes: selectedNodes }) => {
            if (selectedNodes.length === 1) {
                const fullNode = nodes.find(
                    (n) => n.id === selectedNodes[0].id
                );
                setSelectedNode(fullNode || null);
                onNodeSelect?.(selectedNodes[0].id);
                setIsPanelExpanded(true);
                autoExpandedRef.current = true;
                setActiveTab('config');
                // Give the config view more vertical room. If the user already
                // resized larger than the auto-selected size, keep their value.
                setPanelHeight((prev) =>
                    Math.max(prev, getSelectedPanelHeight())
                );
            } else {
                setSelectedNode(null);
                onNodeSelect?.(null);
                if (autoExpandedRef.current) {
                    setIsPanelExpanded(false);
                    autoExpandedRef.current = false;
                    setPanelHeight(getDefaultPanelHeight());
                }
            }
        },
        [nodes, onNodeSelect]
    );

    return (
        <div
            ref={canvasRef}
            className="w-full h-full relative flex flex-col text-foreground"
        >
            {/* Canvas area */}
            <div ref={canvasInteractionRef} className="relative flex-1">
                {Object.keys(nodeTypes).length > 0 || nodes.length === 0 ? (
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        defaultEdgeOptions={defaultEdgeOptions}
                        onInit={onInit}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onSelectionChange={onSelectionChange}
                        onNodeDragStart={onNodeDragStart}
                        onNodeDragStop={onNodeDragStop}
                        // Prevent z-index changes during selection that can cause edge flickering
                        elevateNodesOnSelect={false}
                        // Cull off-viewport nodes — this is a read-only preview, drag flicker is not a concern.
                        onlyRenderVisibleElements={!nodesDraggable}
                        nodesDraggable={nodesDraggable}
                        nodesConnectable={false}
                        elementsSelectable={true}
                        deleteKeyCode={null}
                        // Figma-style navigation; mirrors FlowCanvas.
                        panOnDrag={passiveGestures ? false : [1]}
                        panOnScroll={!passiveViewport}
                        panOnScrollSpeed={1}
                        zoomOnScroll={false}
                        zoomOnPinch={!passiveGestures}
                        zoomOnDoubleClick={!passiveGestures}
                        preventScrolling={!passiveViewport}
                        minZoom={0.05}
                        maxZoom={maxZoom}
                        selectionOnDrag={!passiveGestures}
                        panActivationKeyCode={panActivationKeyCode}
                        fitView
                        fitViewOptions={fitViewOptions}
                        proOptions={proOptions}
                        className="bg-[hsl(var(--canvas-bg))]"
                    >
                        <CanvasBackground />
                    </ReactFlow>
                ) : (
                    <div className="absolute inset-0 bg-[hsl(var(--canvas-bg))]" />
                )}

                {/* Floating expand button when panel is collapsed - hidden in embed mode */}
                {!isEmbed && !isPanelExpanded && (
                    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
                        <button
                            onClick={() => {
                                setIsPanelExpanded(true);
                                autoExpandedRef.current = false;
                            }}
                            className="px-4 py-2 rounded-full text-xs font-medium text-foreground hover:text-foreground transition-all border border-border/40 dark:border-zinc-700/40 shadow-2xl"
                            style={{
                                background:
                                    'radial-gradient(circle at 30% 30%, rgba(63, 63, 70, 0.4), rgba(9, 9, 11, 0.95))',
                                boxShadow:
                                    '0 4px 24px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.08)',
                            }}
                        >
                            Flow Helper
                        </button>
                    </div>
                )}

                {!isEmbed && isPanelExpanded && (
                    <DndProvider>
                        <div
                            ref={panelContainerRef}
                            className="absolute bottom-0 left-0 right-0 px-4 pb-4 z-10"
                            style={{ height: `${panelHeight}px` }}
                        >
                            <ReadOnlyFlowHelperView
                                selectedNode={selectedNode}
                                nodes={nodes}
                                edges={edges}
                                onClose={() => {
                                    setIsPanelExpanded(false);
                                    setSelectedNode(null);
                                }}
                                height={panelHeight}
                                onHeightChange={setPanelHeight}
                                containerRef={panelContainerRef}
                                activeTab={activeTab}
                                onActiveTabChange={setActiveTab}
                                onForkPrompt={onForkPrompt}
                            />
                        </div>
                    </DndProvider>
                )}
            </div>
        </div>
    );
}

// Mobile read-only branch — renders the same workflow data through ForkCanvas instead
// of ReactFlow. xyflow's first-paint mass-mount + per-Handle store subscriptions OOM
// the iPhone WebContent process for wide-spread workflows; ForkCanvas is the
// from-scratch alternative that keeps composited-layer memory bounded. See
// docs/mobile/canvas-tile-cache.md.
function ReadOnlyFlowCanvasMobile({
    nodes: initialNodes,
    edges: initialEdges,
    onForkPrompt,
    isEmbed = false,
    runtimeByNodeId,
    edgeRuntimeById,
    editInfoByNodeId,
    onNodeSelect,
    nodesDraggable = false,
    passiveViewport = false,
}: ReadOnlyFlowCanvasProps) {
    const [selectedNode, setSelectedNode] = useState<Node | null>(null);
    const [panelHeight, setPanelHeight] = useState(getDefaultPanelHeight);
    const [isPanelExpanded, setIsPanelExpanded] = useState(false);
    const [activeTab, setActiveTab] = useState<
        'nodes' | 'config' | 'credentials'
    >('nodes');
    const [nodeDefs, setNodeDefs] = useState<
        Record<string, NodeDefinition | null>
    >({});
    const panelContainerRef = useRef<HTMLDivElement>(null);

    // Convert raw API nodes to xyflow shape with isReadOnly metadata. ForkCanvas
    // expects node.data.config (canonical xyflow shape after createWorkflowNode).
    const nodes = useMemo<Node[]>(
        () =>
            initialNodes.map((n) => {
                const backendNode = n as any;
                if (!backendNode.config) {
                    throw new Error(
                        `Node ${n.id} is missing config from backend`
                    );
                }
                const parsed = createWorkflowNode(
                    n.id,
                    n.type || 'default',
                    n.position,
                    backendNode.config,
                    {
                        isReadOnly: true,
                        ...(backendNode.previewHidden
                            ? { _previewHidden: true }
                            : {}),
                        ...(runtimeByNodeId?.[n.id] || {}),
                        ...(editInfoByNodeId
                            ? {
                                  _previewEditInfo:
                                      editInfoByNodeId[n.id] ?? null,
                              }
                            : {}),
                    }
                );
                if (backendNode.width != null) parsed.width = backendNode.width;
                if (backendNode.height != null)
                    parsed.height = backendNode.height;
                if (backendNode.style != null) parsed.style = backendNode.style;
                return parsed;
            }),
        [editInfoByNodeId, initialNodes, runtimeByNodeId]
    );

    const mobileFitSignature = useMemo(
        () =>
            nodes
                .map(
                    (node) =>
                        `${node.id}@${Math.round(node.position.x)},${Math.round(node.position.y)}`
                )
                .join('|'),
        [nodes]
    );

    const edges = useMemo<Edge[]>(
        () =>
            initialEdges.map((e) => ({
                ...applyEdgeStyle(e),
                animated: false,
                data: {
                    ...(e.data || {}),
                    ...(edgeRuntimeById?.[e.id] || {}),
                    isReadOnly: true,
                },
            })),
        [edgeRuntimeById, initialEdges]
    );

    const requiredTypes = useMemo(
        () => Array.from(new Set(nodes.map((n) => n.type).filter(Boolean))),
        [nodes]
    );
    const nodeDefsReady = requiredTypes.every(
        (type) => type != null && type in nodeDefs
    );

    // Lazy-load only the NodeDefinitions for types actually present in this workflow.
    // ForkCanvas's GenericCard uses these for the branded icon + dimensions.
    useEffect(() => {
        const types = requiredTypes as string[];
        if (types.length === 0) return;
        let cancelled = false;
        loadNodeDefsFor(types).then((defs) => {
            if (!cancelled) setNodeDefs(defs);
        });
        return () => {
            cancelled = true;
        };
    }, [requiredTypes]);

    return (
        <div className="w-full h-full relative flex flex-col">
            <div className="flex-1 relative">
                {nodeDefsReady ? (
                    <ForkCanvas
                        nodes={nodes}
                        edges={edges}
                        nodeDefs={nodeDefs}
                        fitView
                        // Product stories grow the graph after mount; without a
                        // refit the camera keeps the framing it chose for the
                        // first node and the finished graph sits off-centre.
                        fitViewSignal={mobileFitSignature}
                        nodesDraggable={nodesDraggable}
                        passiveViewport={passiveViewport}
                        onNodeClick={(_event, node) => {
                            onNodeSelect?.(node.id);
                            if (isEmbed) return;
                            setSelectedNode(node);
                            setIsPanelExpanded(true);
                            setActiveTab('config');
                        }}
                    />
                ) : (
                    <div className="absolute inset-0 bg-[hsl(var(--canvas-bg))]" />
                )}
                {!isEmbed && !isPanelExpanded && (
                    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
                        <button
                            onClick={() => setIsPanelExpanded(true)}
                            className="px-4 py-2 rounded-full text-xs font-medium text-foreground hover:text-foreground transition-all border border-border/40 dark:border-zinc-700/40 shadow-2xl"
                            style={{
                                background:
                                    'radial-gradient(circle at 30% 30%, rgba(63, 63, 70, 0.4), rgba(9, 9, 11, 0.95))',
                                boxShadow:
                                    '0 4px 24px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.08)',
                            }}
                        >
                            Flow Helper
                        </button>
                    </div>
                )}
                {!isEmbed && isPanelExpanded && (
                    <div
                        ref={panelContainerRef}
                        className="absolute bottom-0 left-0 right-0 px-4 pb-4 z-10"
                        style={{ height: `${panelHeight}px` }}
                    >
                        <ReadOnlyFlowHelperView
                            selectedNode={selectedNode}
                            nodes={nodes}
                            edges={edges}
                            onClose={() => {
                                setIsPanelExpanded(false);
                                setSelectedNode(null);
                            }}
                            height={panelHeight}
                            onHeightChange={setPanelHeight}
                            containerRef={panelContainerRef}
                            activeTab={activeTab}
                            onActiveTabChange={setActiveTab}
                            onForkPrompt={onForkPrompt}
                        />
                    </div>
                )}
            </div>
        </div>
    );
}

export function ReadOnlyFlowCanvas(props: ReadOnlyFlowCanvasProps) {
    const isMobile = useIsMobile();
    // Both branches sit inside <ReactFlowProvider>. Mobile uses ForkCanvas
    // (xyflow-free) for the actual rendering, but the provider stays so any
    // descendant module that transitively touches a React Flow hook
    // (useStore / useReactFlow — pulled in by certain node components when
    // their NodeDefinition module is evaluated) has a valid zustand context.
    // Without this, ForkCanvas crashes with React Flow error #001 on
    // workflows whose nodes do that, e.g. AIAgent / Iteration / Switch /
    // Conditional / Approval / ServerlessFunction / Interface.
    if (isMobile) {
        return (
            <ReactFlowProvider>
                <ReadOnlyFlowCanvasMobile {...props} />
            </ReactFlowProvider>
        );
    }
    return (
        <ReactFlowProvider>
            <ReadOnlyFlowCanvasInner {...props} />
        </ReactFlowProvider>
    );
}
