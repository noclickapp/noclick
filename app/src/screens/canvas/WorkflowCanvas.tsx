// A workflow's canvas as this app draws it on its own: the workflow read and saved through the platform API (the graph
// store, graph/), its steps and connections drawn (nodes/, edges/), and edited on the surface (surface/): steps selected,
// added from the palette (on their own, after a step from its "+", into a connection from its "+"), moved, removed,
// connected as the workflow's rules allow, copied, cut, pasted and duplicated, laid out, saved to a file and read from
// one, undone and done again, from the keys a canvas answers to and its right-click menus. Other writers' changes arrive
// through the account's change stream (graph/followCommits.ts), so the canvas renders inside the app's live frames
// (@/sdk/live). What only a host has (other people editing live, the builder chat, a step's panel) isn't here yet.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ReactFlowProvider, useNodesInitialized, useReactFlow, type Edge, type Node, type OnSelectionChangeParams } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Loader2, Paintbrush, Plus } from 'lucide-react';
import { toast } from 'sonner';
import { isTextEntryTarget } from '@/lib/keyboard';
import { useClient } from '@/sdk/client';
import { useSlot } from '@/slots';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { CanvasBackground } from '@/ui/CanvasBackground';
import { MENU_SURFACE } from '@/ui/menus';
import { cn } from '@/ui/utils';
import { applyNodeUpdate, normalizeNodeUpdatePayload } from './applyNodeUpdate';
import AnimatedWorkflowEdge from './edges/AnimatedWorkflowEdge';
import { useFollowCommits } from './graph/followCommits';
import { graphRecords, isStepPartial, markGraphDirty, recordDeletedNodes, setCanvasEditsClient } from './graph/liveGraphStore';
import { useLiveGraph } from './graph/useLiveGraph';
import { useOpenGraph } from './graph/useOpenGraph';
import { useUndoKeepsServerWrites } from './graph/useUndoKeepsServerWrites';
import { useWorkflowUndoRedo } from './graph/useWorkflowUndoRedo';
import { buildLazyNodeTypes } from './nodes/lazyNodeTypes';
import { PALETTE, STEP_ROLES } from './slots';
import { CanvasSurface } from './surface/CanvasSurface';
import { isStepArrow, selectOnly, stepInDirection } from './surface/stepTraversal';
import { useCanvasContextMenu } from './surface/useCanvasContextMenu';
import { useClickToAddNode } from './surface/useClickToAddNode';
import { useWorkflowCopyPaste } from './surface/useWorkflowCopyPaste';
import { useCtrlPan } from './surface/useCtrlPan';
import { useStickyNoteNode } from './surface/useStickyNoteNode';
import { useSurfaceEditing } from './surface/useSurfaceEditing';
import { useTidyLayout } from './surface/useTidyLayout';
import { useWorkflowFile } from './surface/useWorkflowFile';
import { useWorkflowKeyboardShortcuts } from './surface/useWorkflowKeyboardShortcuts';

const EDGE_TYPES = { animated: AnimatedWorkflowEdge };
const NO_NODES: Node[] = [];
const NO_EDGES: Edge[] = [];

export interface WorkflowCanvasProps {
    workflowId: string;
    /** The workflow's name, which names the file it's saved to. */
    name?: string;
    /** Hears which step is selected (null: none, or several). */
    onSelect?: (nodeId: string | null) => void;
}

export function WorkflowCanvas(props: WorkflowCanvasProps) {
    return (
        <ReactFlowProvider>
            <CanvasEditor {...props} />
        </ReactFlowProvider>
    );
}

function CanvasEditor({ workflowId, name, onSelect }: WorkflowCanvasProps) {
    const client = useClient();
    useEffect(() => setCanvasEditsClient(client), [client]);

    const deleted = useRef(new Set<string>());
    const open = useOpenGraph(workflowId, deleted);
    useFollowCommits(workflowId);
    const loaded = open.state === 'open';

    const { nodes, edges, setNodes, setEdges } = useLiveGraph(workflowId, false);
    const nodesRef = useRef(nodes);
    nodesRef.current = nodes;
    const edgesRef = useRef(edges);
    edgesRef.current = edges;
    const syncingRef = useRef(!loaded);
    syncingRef.current = !loaded;
    const draggingRef = useRef(false);
    const canvasRef = useRef<HTMLDivElement | null>(null);
    const roles = useSlot(STEP_ROLES).useRoles();
    const { getInternalNode, getZoom, setCenter, screenToFlowPosition, fitView, getViewport } = useReactFlow();

    const history = useWorkflowUndoRedo(NO_NODES, NO_EDGES, { historyLimit: 50, onNodesChange: setNodes, onEdgesChange: setEdges });
    const { resetBaseline, rebaseHistory, captureState } = history;
    // An edit made outside React Flow's own changes (a menu's, a pick's): the graph as the store holds it after it,
    // one step back, a task later as the surface's edits are recorded.
    const record = useCallback(() => {
        setTimeout(() => {
            const held = graphRecords[workflowId];
            if (held) captureState(held.nodes as Node[], held.edges as Edge[]);
        }, 0);
    }, [workflowId, captureState]);
    useUndoKeepsServerWrites(workflowId, rebaseHistory, resetBaseline);
    // Undo starts from the workflow as it was opened.
    useEffect(() => {
        if (loaded) resetBaseline(nodesRef.current, edgesRef.current);
    }, [loaded, resetBaseline]);

    const panToNode = useCallback(
        (nodeId: string) => {
            const node = getInternalNode(nodeId);
            if (!node) return;
            const { x, y } = node.internals.positionAbsolute;
            void setCenter(x + (node.measured.width ?? 0) / 2, y + (node.measured.height ?? 0) / 2, { zoom: getZoom(), duration: 300 });
        },
        [getInternalNode, getZoom, setCenter]
    );

    const { stickyNoteRenderer, recalculateZIndex } = useStickyNoteNode({ setNodes });
    const nodeTypes = useMemo(() => buildLazyNodeTypes({ stickyNote: stickyNoteRenderer }), [stickyNoteRenderer]);

    const stepRemoved = useCallback((nodeId: string) => void deleted.current.add(nodeId), []);
    const editing = useSurfaceEditing({
        workflowId,
        setNodes,
        setEdges,
        nodesRef,
        edgesRef,
        history,
        roles,
        syncingRef,
        draggingRef,
        canvasRef,
        panToNode,
        layer: recalculateZIndex,
        on: { removed: stepRemoved },
    });

    // Every change after the open is an edit to save; removed steps are told to the store so a merge never brings them
    // back.
    const baselined = useRef(false);
    useEffect(() => {
        if (!loaded) return;
        if (!baselined.current) {
            baselined.current = true;
            return;
        }
        const removed = [...deleted.current];
        deleted.current.clear();
        if (removed.length) recordDeletedNodes(workflowId, removed);
        markGraphDirty(workflowId);
    }, [loaded, nodes, edges, workflowId]);

    // The workflow framed once its steps have been measured.
    const measured = useNodesInitialized();
    const framed = useRef(false);
    useEffect(() => {
        if (loaded && measured && !framed.current) {
            framed.current = true;
            void fitView({ padding: 0.2 });
        }
    }, [loaded, measured, fitView]);

    const updateStep = useCallback(
        (nodeId: string, data: Record<string, unknown>) => {
            // A step held in part (still being read whole) can't be edited: its save keeps it as stored.
            if (isStepPartial(workflowId, nodeId)) return;
            const update = normalizeNodeUpdatePayload(data);
            setNodes((current) => {
                const updated = current.map((n) => (n.id === nodeId ? applyNodeUpdate(n, update) : n));
                setTimeout(() => captureState(updated, edgesRef.current), 0);
                return updated;
            });
        },
        [workflowId, setNodes, captureState]
    );
    useWorkflowKeyboardShortcuts({ nodes, activeTab: 'canvas', onNodeDataUpdate: updateStep });

    // The arrow keys walk the steps, selecting the next one and bringing it into view.
    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.metaKey || event.ctrlKey || event.altKey || !isStepArrow(event.key)) return;
            if (isTextEntryTarget(event.target) || isTextEntryTarget(document.activeElement)) return;
            const steps = nodesRef.current.filter((n) => n.type !== 'stickyNote');
            const target = stepInDirection(steps, steps.find((n) => n.selected) ?? null, event.key);
            if (!target) return;
            event.preventDefault();
            setNodes((ns) => selectOnly(ns, target.id));
            panToNode(target.id);
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    }, [setNodes, panToNode]);

    const onSelectionChange = useCallback(
        ({ nodes: selected }: OnSelectionChangeParams) => {
            const steps = selected.filter((n) => n.type !== 'stickyNote');
            onSelect?.(steps.length === 1 ? steps[0].id : null);
        },
        [onSelect]
    );

    // The palette, and a step added by a click: from the palette on its own, after a step whose "+" opened it, or into
    // a connection whose "+" did.
    const Palette = useSlot(PALETTE);
    const [palette, setPalette] = useState(false);
    const showPalette = useCallback(() => setPalette(true), []);
    const hidePalette = useCallback(() => setPalette(false), []);
    const { add } = useClickToAddNode({
        nodesRef,
        setNodes,
        setEdges,
        palette: { open: palette, show: showPalette, hide: hidePalette },
        panToNode,
        on: {
            added: (_node, { chained }) => {
                if (!chained) setPalette(false);
                record();
            },
        },
    });

    // A copy still being read is drawn, not edited: its keys and menus wait for the workflow to open.
    const { copySelection, pasteFromClipboard } = useWorkflowCopyPaste({ nodes, edges, active: loaded, setNodes, setEdges, screenToFlowPosition, captureState });

    const fit = useCallback(() => void fitView({ duration: 500, padding: 0.22, maxZoom: 1 }), [fitView]);
    const tidy = useTidyLayout({ nodesRef, edgesRef, setNodes, history, fit });

    const fileInput = useRef<HTMLInputElement | null>(null);
    const refuse = useCallback((message: string) => void toast.error(message), []);
    const { exportFile, importFile } = useWorkflowFile({ nodes, edges, title: name ?? '', setNodes, setEdges, captureState, getViewport, refuse });
    const pickFile = useCallback(() => fileInput.current?.click(), []);

    const menus = useCanvasContextMenu({
        nodesRef,
        setNodes,
        setEdges,
        screenToFlowPosition,
        fitView,
        openPalette: showPalette,
        updateStep,
        tidy,
        copySelection,
        pasteFromClipboard,
        importFile: pickFile,
        exportFile,
        on: {
            added: record,
            removed: (nodeId) => {
                stepRemoved(nodeId);
                record();
            },
        },
    });

    const panActivationKeyCode = useCtrlPan(canvasRef);

    return (
        <div ref={canvasRef} data-testid="workflow-canvas" className="relative h-full w-full select-none bg-[hsl(var(--canvas-bg))]">
            <CanvasSurface
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                edgeTypes={EDGE_TYPES}
                {...editing}
                onSelectionChange={onSelectionChange}
                onPaneContextMenu={loaded ? menus.handlePaneContextMenu : undefined}
                onNodeContextMenu={loaded ? menus.handleNodeContextMenu : undefined}
                onSelectionContextMenu={loaded ? menus.handleSelectionContextMenu : undefined}
                panActivationKeyCode={panActivationKeyCode}
            >
                <CanvasBackground />
            </CanvasSurface>
            {menus.element}
            <input ref={fileInput} type="file" accept=".json,application/json" className="hidden" aria-label="Import a workflow from a file" onChange={(event) => void importFile(event)} />
            {open.state === 'opening' && (
                <div className="pointer-events-none absolute left-1/2 top-3 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full bg-card/95 px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-sm ring-1 ring-border">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> Opening
                </div>
            )}
            {open.state === 'failed' && (
                <p role="alert" className="absolute left-1/2 top-3 z-20 max-w-md -translate-x-1/2 rounded-xl bg-card px-4 py-2 text-[13px] text-red-600 shadow-sm ring-1 ring-border dark:text-red-400">
                    {open.message}
                </p>
            )}
            {loaded && (
                <div className="absolute right-4 top-4 z-10 flex items-center gap-2">
                    {nodes.length > 0 && (
                        <button type="button" className={BUTTON_SECONDARY} onClick={tidy}>
                            <Paintbrush className="h-4 w-4" /> Tidy up
                        </button>
                    )}
                    <button type="button" className={BUTTON_SECONDARY} onClick={() => setPalette((shown) => !shown)} aria-expanded={palette}>
                        <Plus className="h-4 w-4" /> Add step
                    </button>
                </div>
            )}
            {loaded && palette && (
                <div
                    role="dialog"
                    aria-label="Add a step"
                    className={cn(MENU_SURFACE, 'absolute right-4 top-16 z-20 flex max-h-[min(520px,calc(100%-5rem))] w-[360px] max-w-[calc(100%-2rem)] flex-col rounded-2xl p-1.5')}
                >
                    <Palette onAdd={add} onClose={hidePalette} />
                </div>
            )}
        </div>
    );
}
