// FlowHelperView component provides utilities for working with workflow nodes.
// It displays node configuration details, search functionality, and other workflow helpers.
// Appears in the bottom half of the FlowCanvas as an expandable panel.

import { Node, Edge } from '@xyflow/react';
import { X, Settings, ArrowDownToLine, ArrowUpFromLine, Maximize2, Minimize2, Ban, Play, Loader2, Boxes, Key } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import { getAgentToolProviders, getAgentTriggerSources, getToolProviderConsumerTypes } from '~/utils/nodeSchemas';
import { AgentWiringChips } from './AgentWiringChips';
import { ImportCurlButton } from './ImportCurlButton';
import { hasUnconnectedCredentials, providerCredentialsMissing } from './NodeCredentials';
import { useDroppable } from '@dnd-kit/core';
import { useAgentCredentialsRequired } from '~/hooks/useAgentCredentialsRequired';
import { ReferenceHoverProvider } from './ReferenceHoverContext';
import { ReferenceAutocompleteProvider } from './ReferenceAutocompleteContext';
import { useInputNodeSchemas } from '~/hooks/useNodeOutputSchema';
import { parseWholeReference, splitAtFirstIndex, getValueAtPath } from '~/lib/listReferences';
import { getNodeArrayOutputPath } from '~/lib/arrayOutput';
import { isPreviousNodeOutputRequired } from '~/utils/workflowNodeExecution';
import type { CredentialVariable } from '~/hooks/useCredentialVariables';
import type { CredentialDisplayMeta } from '~/utils/credentialAutoSelect';
import { ConfigTabContent } from './flowHelper/ConfigTabContent';
import { CredentialsTabContent } from './flowHelper/CredentialsTabContent';
import { HeaderTab } from './flowHelper/HeaderTab';
import { IncompleteNodeNavigator } from './flowHelper/IncompleteNodeNavigator';
import { InputPanel } from './flowHelper/InputPanel';
import { NodesTabContent } from './flowHelper/NodesTabContent';
import { NodeSearchBar } from './flowHelper/NodeSearchBar';
import { OutputPanel } from './flowHelper/OutputPanel';
import { beginResizeDrag } from './flowHelper/resize';
import { ResizeHandle, VerticalResizeHandle } from './flowHelper/ResizeHandles';
import { useIncompleteNodes } from './flowHelper/useIncompleteNodes';
import { usePanelLayout } from './flowHelper/usePanelLayout';
import { useFit, type FitItem } from './flowHelper/useFit';
import { isTextEntryTarget, isModalOpen } from '~/lib/keyboard';
import { KeyHint } from '~/components/shared/KeyHint';
import { applyCredentialSelection } from '~/lib/applyCredentialSelection';

type HelperTabType = 'home' | 'config' | 'credentials' | null;

// Matches the HeaderTab (UX / Nodes / Config / Credentials) tooltip styling so
// the Input/Output/Run hints read as part of the same header.
const PANEL_TOOLTIP_CLASS =
    'rounded-lg border border-border dark:border-zinc-700/60 bg-popover/95 px-2 py-1.5 text-xs font-medium tracking-tight text-foreground shadow-2xl dark:shadow-black/60 backdrop-blur-md';

interface FlowHelperViewProps {
    selectedNode: Node | null;
    nodes: Node[];
    edges: Edge[];
    /** Skip the slide-up entrance animation (set when opened via the "F" key). */
    noAnimation?: boolean;
    onClose: () => void;
    onNodeDataUpdate?: (nodeId: string, newData: Record<string, any>) => void;
    /** Inject an iteration node to loop a scalar field's list reference over each item. */
    onInjectIteration?: (nodeId: string, fieldKey: string) => void;
    // Run single node callback - returns { success, error?, executionId? }
    // executionId is the optimistic `pending-<ts>` id; the helper keeps it so it
    // can target Stop at this specific run before the real execution_id arrives.
    onRunNode?: (nodeId: string) => { success: boolean; error?: string; executionId?: string };
    // Stop a specific execution by id (real or pending-)
    onStopNode?: (executionId: string) => void;
    isWorkflowRunning?: boolean;
    // True while workflow:get is in flight — cached data shown but edits blocked
    isSyncing?: boolean;
    // Workflow context for dynamic value loading (e.g., webhook URLs)
    workflowId?: string;
    // Height control for vertical resizing
    height: number;
    onHeightChange: (height: number) => void;
    // Ref to container for direct DOM manipulation during resize (avoids re-renders)
    containerRef: React.RefObject<HTMLDivElement | null>;
    // Resize lifecycle — lets the parent disable its CSS height transition during
    // drag (so each onMove tick doesn't trigger a 280ms interpolation) and reenable
    // it on release so programmatic height changes still ease.
    onResizeStart?: () => void;
    onResizeEnd?: () => void;
    // Full screen mode
    isFullScreen: boolean;
    onFullScreenChange: (isFullScreen: boolean) => void;
    // Persisted tab and search state
    activeTab: HelperTabType;
    onActiveTabChange: (tab: HelperTabType) => void;
    searchQuery: string;
    onSearchQueryChange: (query: string) => void;
    // Node selection callback for navigating between nodes
    onSelectNode?: (nodeId: string) => void;
    // When 'interface', only show the UX tab (hides Nodes, Config, Credentials, Input/Output)
    mode?: 'canvas' | 'interface';
    // Workflow-level variables for {{vars.key}} autocomplete
    workflowVariables?: Record<string, any>;
    onVariableValueChange?: (name: string, value: string) => void;
    // Variable names declared by set-variable nodes (for autocomplete of undefined vars)
    declaredVariableNames?: Set<string>;
    // Callback to reset setup state (clear variables so user can redo setup)
    // Credential variables from set-variable nodes — passed from FlowCanvas to avoid stale memo issues
    credentialVariables?: CredentialVariable[];
    // Per-node output selections from history carousel (persists across panel collapse)
    nodeOutputSelectionsRef?: React.RefObject<Record<string, { historyIndex: number; output: unknown }>>;
    onNodeOutputSelection?: (nodeId: string, historyIndex: number, output: unknown | undefined) => void;
    // AI autofill — wired to useCanvasWorkflowEdit.startAutofill
    onAutofill?: (nodeId: string, mode: 'full' | 'operation' | 'fields' | 'single_field', targetField?: string) => Promise<void>;
    // True while any AI edit/autofill is streaming — disable autofill buttons to avoid overlap
    isAutofilling?: boolean;
    // Which node/field/mode is currently autofilling — used to spin only the right control
    autofillStatus?: { nodeId: string | null; mode: 'full' | 'operation' | 'fields' | 'single_field' | null; targetField: string | null };
    // Node id that was just dragged onto the canvas — opens the Config panel in Edit view
    freshlyDroppedNodeId?: string | null;
    onConsumeFreshlyDroppedNode?: () => void;
    // Counter — when it changes, focus the search bar. Bumped by the parent
    // when the helper is opened via the canvas + button or a node "+" hint.
    searchFocusSignal?: number;
    /** Auto-focus the operation picker when it opens. False during keyboard
     *  node-traversal so it doesn't trap arrow navigation. */
    autoFocusOperationPicker?: boolean;
    /** Wire a trigger/tool node to an agent (FlowCanvas.handleAgentWiringAdd) —
     *  powers the "Add trigger" affordance under the agent's Message field. */
    onAgentWiringAdd?: (agentNodeId: string, nodeType: string, role: 'trigger' | 'tool', operation?: string) => string | void;
    /** Patch a wired node's config — provider allowlist/mounts (palette config step). */
    onWiredNodeConfigPatch?: (nodeId: string, config: Record<string, unknown>) => void;
    /** Patch a wired node's credentialIds (palette config step). */
    onWiredNodeCredentialsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** Live accessor for a wired node's data (palette config step). */
    getWiredNodeData?: (nodeId: string) => { nodeData: Record<string, unknown>; config: Record<string, unknown>; credentialIds: Record<string, string> } | null;
}

export const FlowHelperView = memo(({ selectedNode, nodes, edges, noAnimation, onClose, onNodeDataUpdate, onInjectIteration, onRunNode, onStopNode, isWorkflowRunning, isSyncing, workflowId, height, onHeightChange, containerRef, isFullScreen, onFullScreenChange, onResizeStart, onResizeEnd, activeTab, onActiveTabChange, searchQuery, onSearchQueryChange, onSelectNode, mode = 'canvas', workflowVariables, onVariableValueChange, declaredVariableNames, credentialVariables, nodeOutputSelectionsRef, onNodeOutputSelection, onAutofill, isAutofilling, autofillStatus, freshlyDroppedNodeId, onConsumeFreshlyDroppedNode, searchFocusSignal, autoFocusOperationPicker = true, onAgentWiringAdd, onWiredNodeConfigPatch, onWiredNodeCredentialsChange, getWiredNodeData }: FlowHelperViewProps) => {
    const { logActivity } = useAnalytics();
    const isInterfaceMode = mode === 'interface';
    // Use props for persisted state, with local aliases for cleaner code
    const setActiveTab = onActiveTabChange;
    const setSearchQuery = onSearchQueryChange;
    const [showInput, setShowInput] = useState(false);
    const [showOutput, setShowOutput] = useState(false);

    // When a node is freshly dropped/click-added we collapse the Input/Output
    // side panels so the user lands on a clean config form without distraction.
    useEffect(() => {
        if (selectedNode?.id && selectedNode.id === freshlyDroppedNodeId) {
            setShowInput(false);
            setShowOutput(false);
        }
    }, [selectedNode?.id, freshlyDroppedNodeId]);

    // A scalar field holding a plain `{{node.path}}` ref that reaches an array
    // should offer "Loop over each item". We loop the OUTERMOST array: the path
    // up to its first literal index ({{x.values[8][1]}} -> loop `values`, with
    // each row's `[1]` becoming the per-item accessor). A whole-array ref has no
    // index, so the prefix is the whole path.
    const fieldHoldsArrayRef = useCallback((value: unknown): boolean => {
        const ref = parseWholeReference(value);
        if (!ref) return false;
        const src = nodes.find((n) => n.id === ref.nodeId);
        if (!src) return false;
        const out = src.data?.output ?? src.data?.mockedOutput ?? src.data?.previewOutput;
        const { prefix } = splitAtFirstIndex(ref.arrayPath);
        // Before a run, only a known emitter's array path qualifies (an index /
        // nested path can't be resolved yet); with output, the prefix must
        // actually resolve to an array.
        if (out == null) return getNodeArrayOutputPath(src.type, null) === prefix;
        return Array.isArray(getValueAtPath(out, prefix));
    }, [nodes]);

    // Panel widths, compaction flags, observer, resize drag handlers — all bundled.
    const {
        inputPanelWidth,
        outputPanelWidth,
        collapsedSplitRatio,
        isSearchExpanded,
        setIsSearchExpanded,
        headerRef,
        inputPanelRef,
        outputPanelRef,
        contentAreaRef,
        startResize,
        startCollapsedResize,
    } = usePanelLayout();

    // Incomplete node navigation for full screen mode
    const { incompleteNodes, incompleteNodeIndex, prev: handlePrevIncomplete, next: handleNextIncomplete } =
        useIncompleteNodes({ nodes, selectedNode, onSelectNode });

    // Get input nodes (all transitive predecessors of the selected node)
    // Uses BFS backwards through all incoming edges so that {{upstream.field}} references
    // are valid for any ancestor, not just direct predecessors.
    const inputNodes = useMemo(() => {
        if (!selectedNode) return [];

        // For iteration nodes (when selected node is iteration), collect loop-back targets
        // so we can exclude edges that would create circular input references
        const isSelectedIterationNode = selectedNode.type === 'iteration';
        const iterationOutgoingTargets = isSelectedIterationNode
            ? new Set(edges.filter(e => e.source === selectedNode.id).map(e => e.target))
            : new Set<string>();

        // BFS backwards through all incoming edges to collect ALL transitive predecessors
        const visited = new Set<string>([selectedNode.id]);
        const queue: string[] = [selectedNode.id];
        const allPredecessors: Node[] = [];

        while (queue.length > 0) {
            const currentId = queue.shift()!;

            for (const edge of edges) {
                if (edge.target !== currentId) continue;

                // For the selected iteration node, skip loop-back edges from body nodes
                if (currentId === selectedNode.id && isSelectedIterationNode && iterationOutgoingTargets.has(edge.source)) {
                    continue;
                }

                if (visited.has(edge.source)) continue;
                visited.add(edge.source);

                const sourceNode = nodes.find(n => n.id === edge.source);
                if (!sourceNode) continue;

                allPredecessors.push(sourceNode);
                queue.push(edge.source);
            }
        }

        // TRANSITIVE LOOP BODY PROPAGATION:
        // Also find upstream iteration nodes where selectedNode is in the loop body
        // (most are already captured by BFS, but this handles iteration nodes connected
        // via loop handles that may not appear in the direct backward edge traversal)
        //
        // Example: iteration (loop) → A → B → C
        // All of A, B, C see iteration in inputs ✓
        nodes.forEach(node => {
            if (node.type !== 'iteration') return;
            if (node.id === selectedNode.id) return;
            if (allPredecessors.find(n => n.id === node.id)) return; // Already found by BFS

            const loopEdges = edges.filter(e =>
                e.source === node.id &&
                (e.sourceHandle === 'loop' || !e.sourceHandle)
            );
            const directLoopTargets = new Set(loopEdges.map(e => e.target));

            const isInLoopBody = (nodeId: string, vis = new Set<string>()): boolean => {
                if (nodeId === selectedNode.id) return true;
                if (vis.has(nodeId)) return false;
                vis.add(nodeId);
                return edges
                    .filter(e => e.source === nodeId && e.target !== node.id && e.sourceHandle !== 'done')
                    .some(e => isInLoopBody(e.target, vis));
            };

            if (Array.from(directLoopTargets).some(targetId => isInLoopBody(targetId))) {
                allPredecessors.push(node);
            }
        });

        return allPredecessors;
    }, [selectedNode, nodes, edges]);

    // Fetch expected schemas for input nodes that don't have output data yet
    // Used for autocomplete suggestions and reference validation
    const expectedSchemas = useInputNodeSchemas(inputNodes);

    // Ref to always track the latest selectedNode — used by callbacks to avoid stale closures
    // when switching nodes rapidly. Updated in an effect (not during render) so the
    // commit order is defined if multiple effects read the ref in the same pass.
    const selectedNodeRef = useRef(selectedNode);
    useEffect(() => {
        selectedNodeRef.current = selectedNode;
    }, [selectedNode]);

    // Check if node can be run: only block if a previous node is missing output AND
    // the selected node's config actually references that node's data via {{nodeId...}}
    const canRunNode = useMemo(() => {
        if (!selectedNode || !onRunNode) return false;
        if (inputNodes.length === 0) return true;
        return inputNodes.every(n => {
            const output = n.data?.mockedOutput ?? n.data?.output;
            if (output !== undefined && output !== null) return true;
            // No output — only block if config actually references this node
            return !isPreviousNodeOutputRequired(n, selectedNode, edges);
        });
    }, [selectedNode, inputNodes, edges, onRunNode]);

    // Tracks the optimistic pending- id for a single-node run started from THIS
    // helper, scoped to the node it was launched on. Lets the Run button flip to
    // Stop immediately (before workflow:started replaces the pending- id with a
    // real one) and gives Stop something to target during that gap.
    const [pendingRun, setPendingRun] = useState<{ nodeId: string; tempId: string } | null>(null);

    // Drop the pending tracker when the user selects a different node — the
    // helper only owns the run it explicitly launched, and only while looking at
    // the launching node. (The actual backend run keeps going regardless; it
    // surfaces on the global Run/Stop button as before.)
    useEffect(() => {
        setPendingRun(prev => (prev && prev.nodeId !== selectedNode?.id ? null : prev));
    }, [selectedNode?.id]);

    // Once the node reaches a terminal state, the run is done — clear the
    // optimistic tracker so the button flips back to "Run".
    useEffect(() => {
        const state = selectedNode?.data?.executionState;
        if (state === 'completed' || state === 'error' || state === 'skipped' || state === 'idle') {
            setPendingRun(prev => (prev && prev.nodeId === selectedNode?.id ? null : prev));
        }
    }, [selectedNode?.data?.executionState, selectedNode?.id]);

    // True iff the currently-selected node has a run in flight that the helper
    // can stop. Drives the Run↔Stop toggle.
    const isThisNodeRunning = useMemo(() => {
        if (!selectedNode) return false;
        if (selectedNode.data?.executionState === 'running') return true;
        return pendingRun?.nodeId === selectedNode.id;
    }, [selectedNode, pendingRun]);

    // Handler to run the selected node
    // Uses ref to ensure we're always operating on the currently selected node
    const handleRunNode = useCallback(() => {
        const currentNode = selectedNodeRef.current;
        if (!currentNode || !onRunNode) return;
        logActivity(EVENTS.NODE_RUN_CLICKED, {
            node_id: currentNode.id,
            node_type: currentNode.type,
            workflow_id: workflowId,
        });
        const result = onRunNode(currentNode.id);
        if (!result.success && result.error) {
            console.warn('[FlowHelperView] Failed to run node:', result.error);
            return;
        }
        if (result.executionId) {
            setPendingRun({ nodeId: currentNode.id, tempId: result.executionId });
        }
    }, [onRunNode, logActivity, workflowId]);

    // Handler to stop the current single-node run. Prefer the real execution_id
    // on the node (set by workflow:node:state) and fall back to the optimistic
    // pending- id for the brief gap before the first state event arrives.
    const handleStopNode = useCallback(() => {
        const currentNode = selectedNodeRef.current;
        if (!currentNode || !onStopNode) return;
        const nodeExecId = currentNode.data?._executionId as string | undefined;
        const idToStop = nodeExecId || pendingRun?.tempId;
        if (!idToStop) return;
        onStopNode(idToStop);
        setPendingRun(null);
    }, [onStopNode, pendingRun]);

    // Keyboard shortcuts while the helper is open: X toggles the input panel,
    // Y the output panel, and ⌘/Ctrl+Enter runs the selected node (that combo
    // works even while a config field is focused so you can edit-then-run).
    // Interface mode has no input/output/run, so it opts out.
    useEffect(() => {
        if (mode === 'interface') return;
        const onKey = (e: KeyboardEvent) => {
            if (isModalOpen()) return;
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                if (selectedNode && canRunNode && !isWorkflowRunning && !isThisNodeRunning) {
                    e.preventDefault();
                    handleRunNode();
                }
                return;
            }
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (isTextEntryTarget(e.target)) return;
            const k = e.key.toLowerCase();
            if (k === 'x' && selectedNode && inputNodes.length > 0) {
                e.preventDefault();
                setShowInput((v) => !v);
            } else if (k === 'y' && selectedNode) {
                e.preventDefault();
                setShowOutput((v) => !v);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [mode, selectedNode, inputNodes.length, canRunNode, isWorkflowRunning, isThisNodeRunning, handleRunNode]);

    // Pass nested config to NodeConfig — data.config is the authoritative store
    // for user/AI-editable fields. Display metadata (label, operation, goal) are
    // on data directly and passed via separate props.
    const nodeConfig = useMemo<Record<string, unknown>>(() => {
        const config = selectedNode?.data?.config;
        return config && typeof config === 'object' && !Array.isArray(config)
            ? (config as Record<string, unknown>)
            : {};
    }, [selectedNode?.data]);

    // Raw credential IDs from node data — may contain {{vars.*}} references.
    // Used by NodeCredentials to display variable references in the dropdown.
    const rawCredentialIds = useMemo<Record<string, string>>(() => {
        const value = selectedNode?.data?.credentialIds;
        if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
        return Object.fromEntries(
            Object.entries(value).filter(
                (entry): entry is [string, string] =>
                    typeof entry[1] === 'string',
            ),
        );
    }, [selectedNode?.data?.credentialIds]);

    // Resolved credential IDs — {{vars.*}} references replaced with actual UUIDs.
    // Used by NodeConfig for dynamic option loaders that need real credentials.
    const credentialIds = useMemo(() => {
        if (!workflowVariables) return rawCredentialIds;
        const resolved: Record<string, string> = {};
        for (const [k, v] of Object.entries(rawCredentialIds)) {
            const s = v as string;
            const m = s && /^\{\{vars\.([^}]+)\}\}$/.exec(s);
            resolved[k] = m && workflowVariables[m[1]] != null ? String(workflowVariables[m[1]]) : s;
        }
        return resolved;
    }, [rawCredentialIds, workflowVariables]);

    const agentCredentialsCheck = useAgentCredentialsRequired(
        selectedNode?.type === 'agent' ? ((selectedNode?.data?.config as Record<string, any> | undefined)?.model as string | undefined) : undefined,
        selectedNode?.type === 'agent' ? credentialIds as Record<string, string> : {},
        selectedNode?.type === 'agent' ? (selectedNode?.data?.config as Record<string, any> | undefined) : undefined
    );

    // Selected node is wired to an AI agent's bottom handle as a tool provider —
    // the config tab swaps the schema form for the operation allowlist.
    const toolProviderConsumerTypes = useMemo(
        () => (selectedNode ? getToolProviderConsumerTypes(selectedNode.id, nodes, edges) : []),
        [selectedNode, nodes, edges]
    );
    const agentToolProviderMode = toolProviderConsumerTypes.length > 0;

    // Check if selected node has unconnected credentials that need attention
    // (drives the red Credentials header tab). Provider-wired nodes are judged
    // by their allowlist — the plain check saw operation=None (providers skip
    // node drafter) and flagged usage-based providers that need no credential.
    const needsCredentialConnection = useMemo(() => {
        if (!selectedNode?.type) return false;
        // For agent nodes, use the hook result; for others, use hasUnconnectedCredentials
        if (selectedNode.type === 'agent') {
            return agentCredentialsCheck.credentialsRequired;
        }
        if (agentToolProviderMode) {
            return providerCredentialsMissing(selectedNode.type, credentialIds, selectedNode.data);
        }
        return hasUnconnectedCredentials(selectedNode.type, credentialIds, selectedNode.data);
    }, [selectedNode?.type, selectedNode?.data, credentialIds, agentCredentialsCheck.credentialsRequired, agentToolProviderMode]);

    // Wiring of a selected agent — trigger + tool chips under the Message
    // field (the agent runs when a trigger fires; tools are services it may
    // act on). Both add/configure flows open the shared AgentWiringPalette.
    const agentTriggerSources = useMemo(
        () =>
            selectedNode?.type === 'agent'
                ? getAgentTriggerSources(selectedNode.id, nodes, edges)
                : [],
        [selectedNode, nodes, edges]
    );
    const agentToolSources = useMemo(
        () =>
            selectedNode?.type === 'agent' || selectedNode?.type === 'mcp-server'
                ? getAgentToolProviders(selectedNode.id, nodes, edges, providerCredentialsMissing)
                : [],
        [selectedNode, nodes, edges]
    );
    const configFieldAddons = useMemo(() => {
        const isMcp = selectedNode?.type === 'mcp-server';
        if (selectedNode?.type !== 'agent' && !isMcp) return undefined;
        if (!agentTriggerSources.length && !agentToolSources.length && !onAgentWiringAdd) return undefined;
        const consumerId = selectedNode.id;
        const chips = (
            <AgentWiringChips
                variant={isMcp ? 'mcp' : 'agent'}
                triggers={agentTriggerSources}
                tools={agentToolSources}
                onAdd={
                    onAgentWiringAdd
                        ? (nodeType, role, operation) => onAgentWiringAdd(consumerId, nodeType, role, operation)
                        : undefined
                }
                onWiredNodeConfigPatch={onWiredNodeConfigPatch}
                onWiredNodeCredentialsChange={onWiredNodeCredentialsChange}
                getWiredNodeData={getWiredNodeData}
                workflowId={workflowId}
            />
        );
        // MCP nodes anchor the tools chips under server_url (the mode fork:
        // wired tools XOR external URL); agents under their Message field.
        return isMcp ? { server_url: chips } : { message: chips };
    }, [selectedNode, agentTriggerSources, agentToolSources, onAgentWiringAdd, onWiredNodeConfigPatch, onWiredNodeCredentialsChange, getWiredNodeData, workflowId]);

    // Global header above the node's config form.
    const configHeaderSlot = useMemo(() => {
        if (selectedNode?.type === 'automation-http-request') {
            return <ImportCurlButton nodeId={selectedNode.id} />;
        }
        return undefined;
    }, [selectedNode]);

    // Handle config changes from NodeConfig component
    // sourceNodeId is passed by NodeConfig to prevent race conditions when switching nodes
    // If sourceNodeId doesn't match the current node, the update is ignored (stale update from old node)
    const handleConfigChange = useCallback((newConfig: Record<string, any>, sourceNodeId?: string) => {
        const currentNode = selectedNodeRef.current;
        if (currentNode && onNodeDataUpdate) {
            if (sourceNodeId && sourceNodeId !== currentNode.id) {
                console.debug(`[FlowHelperView] Ignoring stale config update from node ${sourceNodeId}, current node is ${currentNode.id}`);
                return;
            }
            // NodeConfig passes pure config fields. Write them into data.config.
            onNodeDataUpdate(currentNode.id, { config: newConfig });
        }
    }, [onNodeDataUpdate]);

    // Handle credential selection changes
    // Uses ref to ensure we're always operating on the currently selected node
    // For agent nodes, also handles inline credential storage (not via credential store)
    const handleCredentialChange = useCallback((newCredentialIds: Record<string, string>, credentialMeta?: Record<string, CredentialDisplayMeta>, credentialRemoved?: string[]) => {
        const currentNode = selectedNodeRef.current;
        if (!currentNode || !onNodeDataUpdate) return;
        // Shared with the Run popup's inline credential block — see
        // lib/applyCredentialSelection for why this is more than a field write.
        applyCredentialSelection(
            currentNode.id,
            workflowId,
            newCredentialIds,
            onNodeDataUpdate,
            credentialMeta,
            credentialRemoved,
        );
    }, [onNodeDataUpdate, workflowId]);

    // Handle setting/clearing mock output data
    const handleMockToggle = useCallback((nodeId: string, isMocked: boolean, output: unknown) => {
        if (onNodeDataUpdate) {
            if (isMocked) {
                // Set mock: save output as mockedOutput
                onNodeDataUpdate(nodeId, { mockedOutput: output });
            } else {
                // Clear mock: remove mockedOutput (null signals deletion)
                onNodeDataUpdate(nodeId, { mockedOutput: null });
            }
        }
    }, [onNodeDataUpdate]);

    // Handle validation status changes (no-op for now, just for UI feedback in NodeConfig)
    // NodeConfig owns its own validation UI state; we don't mirror it into node data
    // because doing so would churn re-renders across the whole canvas on every keystroke.
    const handleValidationChange = useCallback(() => {}, []);

    const handleShowInputPrompt = useCallback(() => {
        setShowInput(true);
    }, []);

    const handleShowOutputPrompt = useCallback(() => {
        setShowOutput(true);
    }, []);

    // Note: Auto-switch to config when user clicks a node is handled in FlowCanvas (onSelectionChange)
    // This allows distinguishing user clicks from state restoration

    // Handle toggling node disabled state
    // Uses ref to ensure we're always operating on the currently selected node
    const handleDisabledToggle = useCallback(() => {
        const currentNode = selectedNodeRef.current;
        if (currentNode && onNodeDataUpdate) {
            const isCurrentlyDisabled = currentNode.data?.disabled || false;
            onNodeDataUpdate(currentNode.id, { disabled: !isCurrentlyDisabled });
        }
    }, [onNodeDataUpdate]);

    // Internal focus-bump counter. Bumped by the in-panel clear button so
    // NodeSearchBar's focusSignal effect re-runs and the input regains focus.
    // Kept separate from the parent's `searchFocusSignal` (which is bumped on
    // "open helper" events) so the two sources don't fight; they're summed
    // into a single counter passed to the search bar.
    const [internalSearchFocusBump, setInternalSearchFocusBump] = useState(0);
    const mergedSearchFocusSignal = (searchFocusSignal ?? 0) + internalSearchFocusBump;

    // Handler for search input — auto-switches to the Nodes tab on any
    // keystroke that produces content (not just empty→non-empty). Earlier
    // gating meant edits to an existing query never re-routed the user back
    // to the picker if they'd manually navigated elsewhere.
    const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const newValue = e.target.value;
        if (newValue.trim() && activeTab !== 'home') {
            setActiveTab('home');
        }
        setSearchQuery(newValue);
    }, [activeTab, setActiveTab, setSearchQuery]);

    // Clears the search and re-focuses the input. Called by both the X button
    // inside the search bar and the empty-state "Clear search" button.
    const handleClearSearch = useCallback(() => {
        setSearchQuery('');
        setInternalSearchFocusBump((n) => n + 1);
    }, [setSearchQuery]);

    // Debounced analytics for node-palette queries. Fires ~600ms after typing stops
    // and skips empty strings so a stray focus/blur doesn't produce a zero-length event.
    useEffect(() => {
        const q = searchQuery.trim();
        if (!q) return;
        const t = setTimeout(() => {
            logActivity(EVENTS.NODE_PALETTE_SEARCHED, {
                query: q,
                query_len: q.length,
                workflow_id: workflowId,
            });
        }, 600);
        return () => clearTimeout(t);
    }, [searchQuery, logActivity, workflowId]);

    // Track previous selected node to detect transitions
    const prevSelectedNodeRef = useRef<Node | null>(null);

    // Auto-toggle Input/Output panels only when transitioning from no node to having a node
    // Preserve user's manual toggle state when switching between nodes
    useEffect(() => {
        const hadNoNodeBefore = prevSelectedNodeRef.current === null;
        const hasNodeNow = selectedNode !== null;

        if (hadNoNodeBefore && hasNodeNow) {
            // Transitioning from no selection to having a selection - auto-show panels
            setShowInput(inputNodes.length > 0);
            setShowOutput(true);
        } else if (!hasNodeNow) {
            // No node selected - hide panels
            setShowInput(false);
            setShowOutput(false);
        }
        // When switching between nodes (hadNodeBefore && hasNodeNow), preserve current state

        prevSelectedNodeRef.current = selectedNode;
    }, [selectedNode, inputNodes.length]);

    // Vertical resize: drag upward increases height (hence the sign flip below),
    // clamped to 150px min and 90% of viewport max. When starting from full-screen,
    // first exit full-screen and anchor to the currently rendered height. If the
    // user drags above FULLSCREEN_SNAP_RATIO of the viewport on release, we snap
    // to full-screen — saves an extra trip to the maximize button.
    const FULLSCREEN_SNAP_RATIO = 0.75;
    const startVerticalResize = useCallback((e: React.MouseEvent) => {
        let startHeight = height;
        if (isFullScreen) {
            const currentHeight = containerRef.current?.getBoundingClientRect().height ?? height;
            onFullScreenChange(false);
            onHeightChange(currentHeight);
            startHeight = currentHeight;
            if (containerRef.current) {
                containerRef.current.style.height = `${currentHeight}px`;
            }
        }
        const heightFor = (dy: number) =>
            Math.max(150, Math.min(window.innerHeight * 0.9, startHeight + -dy));

        onResizeStart?.();
        beginResizeDrag(e, {
            axis: 'y',
            cursor: 'ns-resize',
            onMove: (dy) => {
                if (containerRef.current) containerRef.current.style.height = `${heightFor(dy)}px`;
            },
            onCommit: (dy) => {
                onResizeEnd?.();
                const finalHeight = heightFor(dy);
                if (finalHeight >= window.innerHeight * FULLSCREEN_SNAP_RATIO) {
                    onFullScreenChange(true);
                } else {
                    onHeightChange(finalHeight);
                }
            },
        });
    }, [height, onHeightChange, containerRef, isFullScreen, onFullScreenChange, onResizeStart, onResizeEnd]);

    // Make this a droppable area to cancel drag operations
    const { setNodeRef } = useDroppable({
        id: 'flow-helper-view',
    });

    // Enrich workflow variables with declared variable names so autocomplete suggests
    // {{vars.key}} even before the workflow runs. Prune stale persisted entries that no
    // longer correspond to a declared assignment so renamed/deleted variables don't linger.
    const enrichedVariables = useMemo(() => {
        const declared = declaredVariableNames ?? new Set<string>();
        const vars: Record<string, any> = {};
        if (workflowVariables) {
            for (const key of Object.keys(workflowVariables)) {
                if (declared.has(key)) {
                    vars[key] = workflowVariables[key];
                }
            }
        }
        for (const name of declared) {
            if (!(name in vars)) vars[name] = null;
        }
        return Object.keys(vars).length > 0 ? vars : undefined;
    }, [declaredVariableNames, workflowVariables]);

    // credentialVariables is received as a prop from FlowCanvas (pre-computed there)
    // to avoid memo staleness — FlowCanvas is always re-rendering with fresh node data.

    // Header-strip compaction via priority+ fit. Tabs sit last so they only
    // collapse once everything else (Disable, Output/Input, Run, search) has
    // already folded — the user can navigate the panel without the row of
    // icons becoming unreadable.
    type FitKey = 'disable' | 'output' | 'input' | 'run' | 'search' | 'tabs';
    const fitItems: ReadonlyArray<FitItem<FitKey>> = useMemo(() => ([
        { key: 'disable', priority: 1 },
        // input + output share priority 2: tie-broken by array order, output first.
        { key: 'output',  priority: 2 },
        { key: 'input',   priority: 2 },
        { key: 'run',     priority: 3 },
        { key: 'search',  priority: 4 },
        { key: 'tabs',    priority: 5 },
    ]), []);
    const { isCompact: isFitCompact } = useFit<FitKey>(headerRef, fitItems);
    const isDisableCompact = isFitCompact('disable');
    const isOutputCompact = isFitCompact('output');
    const isInputCompact = isFitCompact('input');
    const isRunCompact = isFitCompact('run');
    const isSearchCompact = isFitCompact('search');
    const isTabsCompact = isFitCompact('tabs');

    return (
        <ReferenceHoverProvider>
        <ReferenceAutocompleteProvider inputNodes={inputNodes} expectedSchemas={expectedSchemas} workflowVariables={enrichedVariables}>
        <div
            ref={setNodeRef}
            className={`h-full flex flex-col rounded-2xl ${noAnimation ? '' : 'animate-slide-up'} overflow-hidden relative border border-border dark:border-zinc-700/40 bg-muted dark:bg-[radial-gradient(circle_at_30%_30%,rgb(18,18,22),rgb(0,0,0))] shadow-[0_-8px_32px_rgba(0,0,0,0.12)] dark:shadow-[0_-8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.08)]`}
            style={{
                // CSS containment isolates this element from causing layout/paint recalculations
                // during ReactFlow drag operations. GPU layer promotion via transform prevents repaints.
                contain: 'layout paint',
                transform: 'translateZ(0)',
            }}
        >
            {/* Vertical resize handle at top */}
            <VerticalResizeHandle onMouseDown={startVerticalResize} />

            {/* Animated background gradient mesh */}
            <div
                className="absolute inset-0 opacity-40 pointer-events-none"
                style={{
                    background: 'radial-gradient(circle at 70% 70%, rgba(120, 113, 108, 0.15), transparent 50%)'
                }}
            />

            {/* Subtle light-wash overlay (panel is fully opaque now, so no
                backdrop-blur needed). Kept very faint to preserve the dark look. */}
            <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />

            {/* Inner soft glow */}
            <div className="absolute inset-[1px] rounded-2xl bg-gradient-radial from-white/[0.03] to-transparent opacity-70 pointer-events-none" />

            {/* Header — single flex row with flex-1 spacers between the three
                groups. The spacers shrink to 0 when content fills the strip,
                so any overflow shows up in the parent's scrollWidth and
                useFit can compact the next priority item. (A grid here would
                let columns shrink below their content and overlap silently.) */}
            <div ref={headerRef} className="flex items-center px-3 py-3 border-b border-border dark:border-zinc-700/60 relative z-10 select-none overflow-hidden">
                {/* Left: Syncing indicator when loading, otherwise normal tabs */}
                <div className="flex items-center gap-2 shrink-0">
                {isSyncing ? (
                <div className="flex items-center gap-2 px-2 min-w-0">
                    <Loader2 className="h-3.5 w-3.5 text-muted-foreground animate-spin flex-shrink-0" />
                    <span className="text-xs font-medium text-muted-foreground truncate">Syncing</span>
                </div>
                ) : !isInterfaceMode && (
                <>
                    {/* In full screen mode, show incomplete node navigator instead of search */}
                    {isFullScreen ? (
                        <IncompleteNodeNavigator
                            count={incompleteNodes.length}
                            currentIndex={incompleteNodeIndex}
                            onPrev={handlePrevIncomplete}
                            onNext={handleNextIncomplete}
                        />
                    ) : (
                        <NodeSearchBar
                            searchQuery={searchQuery}
                            onSearchChange={handleSearchChange}
                            onClear={handleClearSearch}
                            isVeryCompact={isSearchCompact}
                            isSearchExpanded={isSearchExpanded}
                            onSearchExpandedChange={setIsSearchExpanded}
                            // Only auto-focus the search when the Nodes tab is the
                            // surface. The signal effect re-runs on every mount, and
                            // the counter is nonzero after any earlier open — without
                            // this gate, opening to the config tab (Enter, node click)
                            // would steal focus into the search. Zeroing it makes the
                            // effect bail (it early-returns on 0).
                            focusSignal={activeTab === 'home' ? mergedSearchFocusSignal : 0}
                        />
                    )}
                    <TooltipProvider>
                    <Tooltip>
                    <TooltipTrigger asChild>
                    <button
                        data-tour-target="flow-helper-input-btn"
                        onClick={() => setShowInput(!showInput)}
                        disabled={!selectedNode || inputNodes.length === 0}
                        className={`flex items-center gap-1.5 ${isInputCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium ${
                            showInput
                                ? 'bg-foreground/[0.08] text-foreground border border-border dark:border-white/[0.1]'
                                : selectedNode && inputNodes.length > 0
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02] border border-transparent'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                    >
                        <ArrowDownToLine className="h-3.5 w-3.5" />
                        {!isInputCompact && <span>Input</span>}
                        {selectedNode && inputNodes.length > 0 && (
                            <span className="opacity-60">{inputNodes.length}</span>
                        )}
                    </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={8} className={PANEL_TOOLTIP_CLASS}>
                        {selectedNode && inputNodes.length > 0
                            ? <KeyHint keys={['X']} />
                            : !selectedNode ? 'Select a node first' : 'No input connections'}
                    </TooltipContent>
                    </Tooltip>
                    </TooltipProvider>
                </>
                )}
                </div>

                {/* Flex spacer — collapses to 0 when content fills the strip, pushes tabs toward center otherwise. */}
                <div className="flex-1" />

                {/* Center: Tabs — centered by the flanking flex-1 spacers. Clicking the active tab toggles it closed. */}
                <div className="flex items-center gap-1 shrink-0 px-0.5" data-tour-target="flow-helper-tabs">
                    <HeaderTab
                        icon={Boxes}
                        label="Nodes"
                        title="Nodes (click again to hide)"
                        shortcut="N"
                        tourTarget="flow-helper-nodes-tab"
                        isActive={activeTab === 'home'}
                        isCompact={isTabsCompact}
                        onClick={() => setActiveTab(activeTab === 'home' ? null : 'home')}
                    />
                    {!isInterfaceMode && (
                        <>
                            <HeaderTab
                                icon={Settings}
                                label="Config"
                                title="Config (click again to hide)"
                                shortcut="C"
                                tourTarget="flow-helper-config-tab"
                                isActive={activeTab === 'config'}
                                isCompact={isTabsCompact}
                                onClick={() => setActiveTab(activeTab === 'config' ? null : 'config')}
                                disabled={!selectedNode}
                            />
                            <HeaderTab
                                icon={Key}
                                label="Credentials"
                                title={needsCredentialConnection ? 'Connect credentials to run this node (click again to hide)' : 'Credentials (click again to hide)'}
                                shortcut="K"
                                tourTarget="flow-helper-credentials-tab"
                                isActive={activeTab === 'credentials'}
                                isCompact={isTabsCompact}
                                onClick={() => setActiveTab(activeTab === 'credentials' ? null : 'credentials')}
                                variant={needsCredentialConnection ? 'warning' : 'default'}
                            />
                        </>
                    )}
                </div>

                {/* Flex spacer — mirrors the one before the tabs so they stay centered when there's slack. */}
                <div className="flex-1" />

                {/* Right: Output toggle + Disable toggle + Close button */}
                <div className="flex items-center gap-2 shrink-0">
                    {!isInterfaceMode && (
                    <>
                    <TooltipProvider>
                    <Tooltip>
                    <TooltipTrigger asChild>
                    <button
                        data-tour-target="flow-helper-output-btn"
                        onClick={() => setShowOutput(!showOutput)}
                        disabled={!selectedNode}
                        className={`flex items-center gap-1.5 ${isOutputCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium ${
                            showOutput
                                ? 'bg-foreground/[0.08] text-foreground border border-border dark:border-white/[0.1]'
                                : selectedNode
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02] border border-transparent'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                    >
                        <ArrowUpFromLine className="h-3.5 w-3.5" />
                        {!isOutputCompact && <span>Output</span>}
                    </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={8} className={PANEL_TOOLTIP_CLASS}>
                        {selectedNode ? <KeyHint keys={['Y']} /> : 'Select a node first'}
                    </TooltipContent>
                    </Tooltip>
                    </TooltipProvider>

                    {/* Run Node Button / Syncing Indicator */}
                    {isSyncing ? (
                        <div
                            className={`flex items-center gap-1.5 ${isRunCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium bg-secondary dark:bg-zinc-700/50 text-muted-foreground border border-border dark:border-zinc-600/50`}
                        >
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            {!isRunCompact && <span>Syncing</span>}
                        </div>
                    ) : (
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                                {isThisNodeRunning ? (
                                    <button
                                        data-tour-target="flow-helper-run-btn"
                                        onClick={handleStopNode}
                                        aria-label="Stop node"
                                        className={`flex items-center gap-1.5 ${isRunCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium transition-all bg-secondary text-white border border-border dark:border-zinc-700 hover:bg-red-500/15 hover:border-red-500/40 hover:text-red-700 dark:hover:bg-red-900/50 dark:hover:border-red-800/50 dark:hover:text-red-100`}
                                    >
                                        <X className="h-3.5 w-3.5" />
                                        {!isRunCompact && <span>Stop</span>}
                                    </button>
                                ) : (
                                    <button
                                        data-tour-target="flow-helper-run-btn"
                                        onClick={handleRunNode}
                                        disabled={!selectedNode || !canRunNode || isWorkflowRunning}
                                        className={`flex items-center gap-1.5 ${isRunCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium transition-all ${
                                            isWorkflowRunning
                                                ? 'bg-secondary dark:bg-zinc-700/50 text-muted-foreground border border-border dark:border-zinc-600/50 cursor-wait'
                                                : selectedNode && canRunNode
                                                ? 'bg-foreground/10 text-foreground hover:bg-foreground/15 border border-border dark:border-white/10'
                                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                                        }`}
                                    >
                                        <Play className="h-3.5 w-3.5" />
                                        {!isRunCompact && <span>{isWorkflowRunning ? 'Running...' : 'Run'}</span>}
                                    </button>
                                )}
                            </TooltipTrigger>
                            <TooltipContent side="top" sideOffset={8} className={PANEL_TOOLTIP_CLASS}>
                                {isThisNodeRunning ? 'Stop this node' :
                                 !selectedNode ? 'Select a node first' :
                                 isWorkflowRunning ? 'Workflow is running' :
                                 !canRunNode ? 'Missing input data from previous nodes' :
                                 <KeyHint keys={['mod', 'enter']} />}
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    )}

                    {/* Disable Toggle Button */}
                    <TooltipProvider>
                    <Tooltip>
                    <TooltipTrigger asChild>
                    <button
                        data-tour-target="flow-helper-disable-btn"
                        onClick={handleDisabledToggle}
                        disabled={!selectedNode}
                        className={`flex items-center gap-1.5 ${isDisableCompact ? 'px-2' : 'px-3'} py-1.5 rounded-lg text-xs font-medium transition-all ${
                            selectedNode?.data?.disabled
                                ? 'bg-red-500/20 text-red-600 dark:text-red-400 border border-red-500/30 hover:bg-red-500/30'
                                : selectedNode
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02] border border-transparent'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                    >
                        <Ban className="h-3.5 w-3.5" />
                        {!isDisableCompact && <span>{selectedNode?.data?.disabled ? 'Disabled' : 'Disable'}</span>}
                    </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" sideOffset={8} className={PANEL_TOOLTIP_CLASS}>
                        {selectedNode ? <KeyHint keys={['D']} /> : 'Select a node first'}
                    </TooltipContent>
                    </Tooltip>
                    </TooltipProvider>
                    </>
                    )}

                    {/* Full screen toggle button */}
                    <button
                        onClick={() => onFullScreenChange(!isFullScreen)}
                        className="h-7 w-7 rounded-full text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-foreground/[0.1] transition-all flex items-center justify-center flex-shrink-0"
                        title={isFullScreen ? 'Exit full screen' : 'Enter full screen'}
                    >
                        {isFullScreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                    </button>

                    {/* Close button */}
                    <button
                        onClick={onClose}
                        className="h-7 w-7 rounded-full text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-foreground/[0.1] transition-all flex items-center justify-center flex-shrink-0"
                    >
                        <X className="h-3.5 w-3.5" />
                    </button>
                </div>
            </div>

            {/* Content - Three-column layout: Input | Main | Output */}
            <div ref={contentAreaRef} className="flex-1 relative z-10 flex overflow-hidden">
                {/* Syncing overlay — shown while loading fresh data from backend */}
                {isSyncing && (
                    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-card/80 backdrop-blur-sm">
                        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mb-3" />
                        <p className="text-sm text-muted-foreground">Loading latest workflow data</p>
                    </div>
                )}
                {/* Input Panel (Toggleable & Resizable) - expands with flex ratio when middle panel is hidden */}
                {!isInterfaceMode && showInput && (
                    <div
                        ref={inputPanelRef}
                        className={`relative min-w-0 ${activeTab !== null ? 'border-r border-border/50 dark:border-zinc-800/50' : ''}`}
                        style={activeTab !== null
                            ? { width: `${inputPanelWidth}px` }
                            : { flex: showOutput ? collapsedSplitRatio : 1 }
                        }
                    >
                        <div className="h-full overflow-y-auto scrollbar-subtle py-3 pl-4 pr-3 mr-[3px]">
                            <InputPanel
                                inputNodes={inputNodes}
                                workflowId={workflowId ?? ''}
                                selectedNodeId={selectedNode?.id}
                                allEdges={edges}
                                nodeOutputSelectionsRef={nodeOutputSelectionsRef}
                                onNodeOutputSelection={onNodeOutputSelection}
                            />
                        </div>
                        {/* Resize handle - different handler for normal vs collapsed mode */}
                        {activeTab !== null ? (
                            <ResizeHandle
                                position="right"
                                onMouseDown={(e) => startResize(e, 'input')}
                            />
                        ) : showOutput ? (
                            <ResizeHandle
                                position="right"
                                onMouseDown={startCollapsedResize}
                            />
                        ) : null}
                    </div>
                )}

                {/* Empty state - shown when all panels are hidden */}
                {!isInterfaceMode && activeTab === null && !showInput && !showOutput && (
                    <div className="flex-1 flex items-center justify-center">
                        <div className="text-center space-y-4">
                            <div className="text-muted-foreground text-sm">Select a panel to view</div>
                            <div className="flex items-center justify-center gap-3">
                                {selectedNode && inputNodes.length > 0 && (
                                    <button
                                        onClick={() => setShowInput(true)}
                                        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-foreground/[0.08] text-foreground hover:bg-foreground/[0.12] border border-border dark:border-white/[0.1] transition-all"
                                    >
                                        <ArrowDownToLine className="h-4 w-4" />
                                        Input
                                    </button>
                                )}
                                <button
                                    onClick={() => setActiveTab('config')}
                                    disabled={!selectedNode}
                                    className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                                        selectedNode
                                            ? "bg-foreground/[0.08] text-foreground hover:bg-foreground/[0.12] border border-border dark:border-white/[0.1]"
                                            : "bg-muted/50 text-muted-foreground/70 dark:text-zinc-600 cursor-not-allowed border border-border/30 dark:border-zinc-700/30"
                                    }`}
                                >
                                    <Settings className="h-4 w-4" />
                                    Config
                                </button>
                                {selectedNode && (
                                    <button
                                        onClick={() => setShowOutput(true)}
                                        className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-foreground/[0.08] text-foreground hover:bg-foreground/[0.12] border border-border dark:border-white/[0.1] transition-all"
                                    >
                                        <ArrowUpFromLine className="h-4 w-4" />
                                        Output
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Main Content - hidden when no tab selected to let input/output expand */}
                {activeTab !== null && (
                <div data-flow-helper-scroll="true" className="flex-1 overflow-y-auto scrollbar-subtle py-3 px-6" style={{ minWidth: '17.5rem' }}>
                    {activeTab === 'home' && (
                        <NodesTabContent searchQuery={searchQuery} onClearSearch={handleClearSearch} />
                    )}

                    {activeTab === 'config' && (
                        <ConfigTabContent
                            selectedNode={selectedNode}
                            onNodeDataUpdate={onNodeDataUpdate}
                            onInjectIteration={onInjectIteration}
                            fieldHoldsArrayRef={fieldHoldsArrayRef}
                            workflowId={workflowId}
                            workflowVariables={workflowVariables}
                            onVariableValueChange={onVariableValueChange}
                            nodeConfig={nodeConfig}
                            credentialIds={credentialIds}
                            onSwitchToCredentials={() => setActiveTab('credentials')}
                            onAutofill={onAutofill}
                            isAutofilling={isAutofilling}
                            autofillStatus={autofillStatus}
                            onValidationChange={handleValidationChange}
                            onConfigChange={handleConfigChange}
                            freshlyDroppedNodeId={freshlyDroppedNodeId}
                            onConsumeFreshlyDroppedNode={onConsumeFreshlyDroppedNode}
                            autoFocusOperationPicker={autoFocusOperationPicker}
                            showInputPrompt={inputNodes.length > 0 && !showInput}
                            onShowInputPrompt={handleShowInputPrompt}
                            showOutputPrompt={!showOutput}
                            onShowOutputPrompt={handleShowOutputPrompt}
                            agentToolProviderMode={agentToolProviderMode}
                            toolProviderConsumerTypes={toolProviderConsumerTypes}
                            headerSlot={configHeaderSlot}
                            fieldAddons={configFieldAddons}
                        />
                    )}

                    {activeTab === 'credentials' && (
                        <CredentialsTabContent
                            selectedNode={selectedNode}
                            nodeConfig={nodeConfig}
                            rawCredentialIds={rawCredentialIds}
                            credentialVariables={credentialVariables}
                            onCredentialChange={handleCredentialChange}
                        />
                    )}
                </div>
                )}

                {/* Output Panel (Toggleable & Resizable) - expands with flex ratio when middle panel is hidden */}
                {!isInterfaceMode && showOutput && (
                    <div
                        ref={outputPanelRef}
                        className={`relative min-w-0 ${activeTab !== null ? 'border-l border-border/50 dark:border-zinc-800/50' : ''}`}
                        style={activeTab !== null
                            ? { width: `${outputPanelWidth}px` }
                            : { flex: showInput ? 1 - collapsedSplitRatio : 1 }
                        }
                    >
                        {/* Only show resize handle when middle panel is visible (fixed width mode) */}
                        {activeTab !== null && (
                        <ResizeHandle
                            position="left"
                            onMouseDown={(e) => startResize(e, 'output')}
                        />
                        )}
                        <div className="h-full overflow-y-auto scrollbar-subtle py-3 px-4">
                            <OutputPanel selectedNode={selectedNode} onMockToggle={handleMockToggle} workflowId={workflowId} initialHistoryIndex={selectedNode ? nodeOutputSelectionsRef?.current?.[selectedNode.id]?.historyIndex : undefined} onHistoryIndexChange={onNodeOutputSelection} />
                        </div>
                    </div>
                )}
            </div>
        </div>
        </ReferenceAutocompleteProvider>
        </ReferenceHoverProvider>
    );
// Custom memo comparator. Returns true to SKIP a re-render when none of the
// listed props changed by reference.
//
// We intentionally compare only a curated subset of props rather than all of
// them. The unlisted props fall into two buckets:
//
// (1) Callback props (onNodeDataUpdate, onClose, onAutofill,
//     onHeightChange, onFullScreenChange, onActiveTabChange,
//     onSearchQueryChange, onNodeOutputSelection, containerRef,
//     nodeOutputSelectionsRef). FlowCanvas passes stable references for these,
//     so comparing them would either always return true (noise) or — if a
//     parent forgot to memoise — force a re-render on every parent render.
//
// (2) State-derived props that change together with listed props we DO compare
//     (isAutofilling, autofillStatus, workflowVariables, isSyncing). These
//     always flip alongside a change to `nodes` (FlowCanvas mutates node.data
//     when autofill flips state), so the `nodes` check below covers them.
//
// If you add a prop that changes independently of `nodes` and needs the view
// to re-render, add it here — forgetting will silently mask updates.
}, (prevProps, nextProps) => {
    return (
        prevProps.selectedNode === nextProps.selectedNode &&
        prevProps.activeTab === nextProps.activeTab &&
        prevProps.searchQuery === nextProps.searchQuery &&
        prevProps.height === nextProps.height &&
        prevProps.isFullScreen === nextProps.isFullScreen &&
        prevProps.isWorkflowRunning === nextProps.isWorkflowRunning &&
        prevProps.workflowId === nextProps.workflowId &&
        prevProps.onSelectNode === nextProps.onSelectNode &&
        prevProps.nodes === nextProps.nodes &&
        prevProps.edges === nextProps.edges &&
        prevProps.mode === nextProps.mode &&
        prevProps.credentialVariables === nextProps.credentialVariables &&
        prevProps.freshlyDroppedNodeId === nextProps.freshlyDroppedNodeId &&
        // Bumped (independently of `nodes`) when the add-node button is clicked
        // while the view is already open; needed so the search input re-focuses.
        prevProps.searchFocusSignal === nextProps.searchFocusSignal &&
        prevProps.autoFocusOperationPicker === nextProps.autoFocusOperationPicker
    );
});
