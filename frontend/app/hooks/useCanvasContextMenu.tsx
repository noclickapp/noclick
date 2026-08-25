// Owns the workflow canvas's right-click context menu — state, the three
// ReactFlow handlers (pane / node / selection), the action helpers (add sticky,
// duplicate, delete, etc.), and the rendered menu element. Extracted from
// FlowCanvas so the canvas file only sees a single hook call + 3 prop bindings
// + 1 element slot in JSX.

import { useCallback, useState, type MutableRefObject, type RefObject } from 'react';
import { Node, Edge } from '@xyflow/react';
import {
    Plus,
    StickyNote,
    ClipboardPaste,
    MousePointer2,
    Paintbrush,
    Maximize2,
    Copy,
    Scissors,
    EyeOff,
    Eye,
    Pencil,
    Play,
    Trash2,
    Repeat,
    Settings2,
} from 'lucide-react';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import { createWorkflowNode, removeById } from '~/lib/applyNodeUpdate';
import { autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelect';
import { EVENTS } from '~/lib/analytics-events';
import type { WorkflowInterfaceHandle } from '~/components/interface/WorkflowInterface';
import { CanvasContextMenu, type ContextMenuItem } from '~/components/workflow/CanvasContextMenu';

// Re-right-click within this many viewport px of the previous click is treated
// as the same place — the previous state object is returned so React skips the
// re-render and the menu doesn't flicker.
const SAME_PLACE_PX = 5;

type ContextMenuState =
    | { kind: 'pane'; px: { x: number; y: number }; flow: { x: number; y: number } }
    | { kind: 'node'; nodeId: string; px: { x: number; y: number } }
    | { kind: 'selection'; nodeIds: string[]; px: { x: number; y: number } }
    | null;

const isSamePlace = (a: { x: number; y: number }, b: { x: number; y: number }) =>
    Math.abs(a.x - b.x) < SAME_PLACE_PX && Math.abs(a.y - b.y) < SAME_PLACE_PX;

export interface UseCanvasContextMenuDeps {
    // State refs + setters
    nodesRef: MutableRefObject<Node[]>;
    setNodes: (setter: (prev: Node[]) => Node[]) => void;
    setEdges: (setter: (prev: Edge[]) => Edge[]) => void;
    deletedNodeIdsRef: MutableRefObject<Set<string>>;
    workflowInterfaceRef: RefObject<WorkflowInterfaceHandle | null>;
    // Collaboration broadcast helpers (no-ops when collab is off)
    broadcastNodeAdd?: (node: Node) => void;
    broadcastNodeRemove?: (nodeId: string) => void;
    // Workflow context
    workflowId: string | undefined;
    logActivity: (event: string, props: Record<string, unknown>) => void;
    // ReactFlow methods
    screenToFlowPosition: (position: { x: number; y: number }) => { x: number; y: number };
    fitView: (opts?: { duration?: number; padding?: number; maxZoom?: number }) => void;
    // FlowHelperView controls — used by the Add-node menu item
    setIsConfigViewExpanded: (open: boolean) => void;
    setFlowHelperActiveTab: (tab: 'home' | 'config' | 'credentials') => void;
    bumpSearchFocus: () => void;
    // Action callbacks that already exist in FlowCanvas
    openNodeConfigExpanded: (nodeId: string) => void;
    runFromNode: (nodeId: string) => void;
    handleNodeDataUpdate: (nodeId: string, data: Record<string, unknown>) => void;
    handleAutolayout: () => void;
    copySelection: (overrideNodeIds?: string[]) => Promise<void>;
    pasteFromClipboard: (positionPx?: { x: number; y: number }) => Promise<void>;
}

export interface UseCanvasContextMenuResult {
    handlePaneContextMenu: (event: React.MouseEvent | MouseEvent) => void;
    handleNodeContextMenu: (event: React.MouseEvent, node: Node) => void;
    handleSelectionContextMenu: (event: React.MouseEvent | MouseEvent, selectedNodes: Node[]) => void;
    /** Render this in the canvas JSX (no positioning concerns — menu uses fixed positioning). */
    element: React.ReactElement | null;
}

export function useCanvasContextMenu(deps: UseCanvasContextMenuDeps): UseCanvasContextMenuResult {
    const {
        nodesRef, setNodes, setEdges, deletedNodeIdsRef, workflowInterfaceRef,
        broadcastNodeAdd, broadcastNodeRemove,
        workflowId, logActivity,
        screenToFlowPosition, fitView,
        setIsConfigViewExpanded, setFlowHelperActiveTab, bumpSearchFocus,
        openNodeConfigExpanded, runFromNode, handleNodeDataUpdate, handleAutolayout,
        copySelection, pasteFromClipboard,
    } = deps;

    const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
    const closeContextMenu = useCallback(() => setContextMenu(null), []);

    // ── Handlers (wired to ReactFlow) ────────────────────────────────────
    // Same-place re-click returns prev state (no re-render, no flicker).
    // Otherwise a new state object lands and the menu's position-derived `key`
    // forces a clean remount with the open animation at the new spot.

    const handlePaneContextMenu = useCallback((event: React.MouseEvent | MouseEvent) => {
        event.preventDefault();
        const px = { x: event.clientX, y: event.clientY };
        const flow = screenToFlowPosition(px);
        setContextMenu(prev => (prev?.kind === 'pane' && isSamePlace(prev.px, px) ? prev : { kind: 'pane', px, flow }));
    }, [screenToFlowPosition]);

    const handleNodeContextMenu = useCallback((event: React.MouseEvent, node: Node) => {
        event.preventDefault();
        event.stopPropagation();
        const px = { x: event.clientX, y: event.clientY };
        setContextMenu(prev => (prev?.kind === 'node' && prev.nodeId === node.id && isSamePlace(prev.px, px) ? prev : { kind: 'node', nodeId: node.id, px }));
    }, []);

    // Fires when the right-click lands inside a drag-select rectangle. Without
    // this, ReactFlow shows nothing — onNodeContextMenu only fires for clicks
    // directly on a single node.
    const handleSelectionContextMenu = useCallback((event: React.MouseEvent | MouseEvent, selectedNodes: Node[]) => {
        event.preventDefault();
        event.stopPropagation();
        const px = { x: event.clientX, y: event.clientY };
        const nodeIds = selectedNodes.map(n => n.id);
        setContextMenu(prev => (prev?.kind === 'selection' && isSamePlace(prev.px, px) ? prev : { kind: 'selection', nodeIds, px }));
    }, []);

    // ── Action helpers ───────────────────────────────────────────────────

    // Add a sticky note at the given flow position. Mirrors the drop-handler
    // sticky-note branch — sticky notes intentionally skip onNodeCreated /
    // autoSelectCredentialsForNewNode (no config panel, no credentials).
    const addStickyNoteAt = useCallback((position: { x: number; y: number }) => {
        const newId = generateNodeId('stickyNote');
        const newNode = createWorkflowNode(newId, 'stickyNote', position, { content: '', color: 8 });
        newNode.style = { width: 200, height: 200 };
        setNodes(prev => [...prev, newNode]);
        broadcastNodeAdd?.(newNode);
        logActivity(EVENTS.NODE_ADDED, { node_id: newId, node_type: 'stickyNote', workflow_id: workflowId, source: 'context-menu' });
    }, [setNodes, broadcastNodeAdd, logActivity, workflowId]);

    // Select every node and edge on the canvas.
    const selectAllElements = useCallback(() => {
        setNodes(ns => ns.map(n => (n.selected ? n : { ...n, selected: true })));
        setEdges(es => es.map(e => (e.selected ? e : { ...e, selected: true })));
    }, [setNodes, setEdges]);

    // Duplicate a node next to itself. Sticky notes keep their dimensions;
    // other nodes get auto-credential-resolution to mirror manual placement.
    const duplicateNodeById = useCallback((nodeId: string) => {
        const src = nodesRef.current.find(n => n.id === nodeId);
        if (!src || !src.type) return;
        const newId = generateNodeId(src.type);
        const newPosition = { x: src.position.x + 40, y: src.position.y + 40 };
        const clonedData = JSON.parse(JSON.stringify(src.data ?? {}));
        const newNode = createWorkflowNode(newId, src.type, newPosition, clonedData);
        if (src.style) newNode.style = { ...src.style };
        if (src.width) newNode.width = src.width;
        if (src.height) newNode.height = src.height;
        setNodes(prev => [...prev, newNode]);
        broadcastNodeAdd?.(newNode);
        if (src.type !== 'stickyNote') {
            autoSelectCredentialsForNewNode(newNode, setNodes, workflowId ?? null);
        }
        logActivity(EVENTS.NODE_ADDED, { node_id: newId, node_type: src.type, workflow_id: workflowId, source: 'duplicate' });
    }, [nodesRef, setNodes, broadcastNodeAdd, logActivity, workflowId]);

    // Delete a node + its incident edges, broadcast to collaborators, and mark
    // for the post-delete graph-snapshot batch. Mirrors the change-handler
    // delete path at the onNodesChangeForCanvas site.
    const deleteNodeById = useCallback((nodeId: string) => {
        setNodes(prev => removeById(prev, nodeId));
        setEdges(prev => prev.filter(e => e.source !== nodeId && e.target !== nodeId));
        broadcastNodeRemove?.(nodeId);
        deletedNodeIdsRef.current.add(nodeId);
        workflowInterfaceRef.current?.removeBlock(nodeId);
    }, [setNodes, setEdges, broadcastNodeRemove, deletedNodeIdsRef, workflowInterfaceRef]);

    // ── Menu items ───────────────────────────────────────────────────────

    const buildItems = (): ContextMenuItem[] | null => {
        if (!contextMenu) return null;
        if (contextMenu.kind === 'pane') {
            return [
                { type: 'item', label: 'Add node', icon: <Plus className="h-3.5 w-3.5" />, shortcut: ['N'], onSelect: () => {
                    setIsConfigViewExpanded(true);
                    setFlowHelperActiveTab('home');
                    bumpSearchFocus();
                } },
                { type: 'item', label: 'Add sticky note', icon: <StickyNote className="h-3.5 w-3.5" />, onSelect: () => addStickyNoteAt(contextMenu.flow) },
                { type: 'separator' },
                { type: 'item', label: 'Paste', icon: <ClipboardPaste className="h-3.5 w-3.5" />, shortcut: ['mod', 'V'], onSelect: () => pasteFromClipboard(contextMenu.px) },
                { type: 'item', label: 'Select all', icon: <MousePointer2 className="h-3.5 w-3.5" />, onSelect: selectAllElements },
                { type: 'separator' },
                { type: 'item', label: 'Auto-layout', icon: <Paintbrush className="h-3.5 w-3.5" />, onSelect: handleAutolayout },
                { type: 'item', label: 'Fit view', icon: <Maximize2 className="h-3.5 w-3.5" />, onSelect: () => fitView({ duration: 500, padding: 0.22, maxZoom: 1.0 }) },
            ];
        }
        if (contextMenu.kind === 'node') {
            const node = nodesRef.current.find(n => n.id === contextMenu.nodeId);
            if (!node) return null;
            const isSticky = node.type === 'stickyNote';
            const isDisabled = !!node.data?.disabled;
            const selectedIds = nodesRef.current.filter(n => n.selected).map(n => n.id);
            const copyIds = selectedIds.includes(node.id) && selectedIds.length > 0 ? selectedIds : [node.id];
            const items: ContextMenuItem[] = [];
            if (!isSticky) {
                items.push({ type: 'item', label: 'Open', icon: <Settings2 className="h-3.5 w-3.5" />, shortcut: ['enter'], onSelect: () => openNodeConfigExpanded(node.id) });
                items.push({ type: 'item', label: 'Run from this node', icon: <Play className="h-3.5 w-3.5" />, onSelect: () => runFromNode(node.id) });
                items.push({ type: 'separator' });
            }
            items.push({ type: 'item', label: 'Duplicate', icon: <Repeat className="h-3.5 w-3.5" />, onSelect: () => duplicateNodeById(node.id) });
            items.push({ type: 'item', label: 'Copy', icon: <Copy className="h-3.5 w-3.5" />, shortcut: ['mod', 'C'], onSelect: () => copySelection(copyIds) });
            items.push({ type: 'item', label: 'Cut', icon: <Scissors className="h-3.5 w-3.5" />, onSelect: async () => {
                await copySelection(copyIds);
                copyIds.forEach(deleteNodeById);
            } });
            if (!isSticky) {
                items.push({ type: 'separator' });
                items.push({ type: 'item', label: isDisabled ? 'Enable' : 'Disable', icon: isDisabled ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />, shortcut: ['D'], onSelect: () => handleNodeDataUpdate(node.id, { disabled: !isDisabled }) });
                items.push({ type: 'item', label: 'Rename', icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => {
                    document.dispatchEvent(new CustomEvent('noclick:node:start-rename', { detail: { nodeId: node.id } }));
                } });
            }
            items.push({ type: 'separator' });
            items.push({ type: 'item', label: 'Delete', icon: <Trash2 className="h-3.5 w-3.5" />, shortcut: ['backspace'], destructive: true, onSelect: () => deleteNodeById(node.id) });
            return items;
        }
        // selection
        const selNodes = nodesRef.current.filter(n => contextMenu.nodeIds.includes(n.id));
        if (selNodes.length === 0) return null;
        const targetable = selNodes.filter(n => n.type !== 'stickyNote');
        const allDisabled = targetable.length > 0 && targetable.every(n => !!n.data?.disabled);
        const items: ContextMenuItem[] = [
            { type: 'item', label: `Duplicate (${selNodes.length})`, icon: <Repeat className="h-3.5 w-3.5" />, onSelect: () => selNodes.forEach(n => duplicateNodeById(n.id)) },
            { type: 'item', label: `Copy (${selNodes.length})`, icon: <Copy className="h-3.5 w-3.5" />, shortcut: ['mod', 'C'], onSelect: () => copySelection(contextMenu.nodeIds) },
            { type: 'item', label: `Cut (${selNodes.length})`, icon: <Scissors className="h-3.5 w-3.5" />, onSelect: async () => {
                await copySelection(contextMenu.nodeIds);
                contextMenu.nodeIds.forEach(deleteNodeById);
            } },
        ];
        if (targetable.length > 0) {
            items.push({ type: 'separator' });
            items.push({ type: 'item', label: allDisabled ? `Enable (${targetable.length})` : `Disable (${targetable.length})`, icon: allDisabled ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />, shortcut: ['D'], onSelect: () => {
                targetable.forEach(n => handleNodeDataUpdate(n.id, { disabled: !allDisabled }));
            } });
        }
        items.push({ type: 'separator' });
        items.push({ type: 'item', label: `Delete (${selNodes.length})`, icon: <Trash2 className="h-3.5 w-3.5" />, shortcut: ['backspace'], destructive: true, onSelect: () => contextMenu.nodeIds.forEach(deleteNodeById) });
        return items;
    };

    let element: React.ReactElement | null = null;
    if (contextMenu) {
        const items = buildItems();
        if (items) {
            // Position+target-derived key — different location OR different target =
            // remount = fresh open animation at the new spot. Same place returns the
            // prev state above, so the key stays and the menu doesn't re-mount.
            const targetKey = contextMenu.kind === 'node'
                ? contextMenu.nodeId
                : contextMenu.kind === 'selection'
                    ? contextMenu.nodeIds.join(',')
                    : 'pane';
            const key = `${contextMenu.kind}:${targetKey}:${contextMenu.px.x},${contextMenu.px.y}`;
            element = <CanvasContextMenu key={key} position={contextMenu.px} items={items} onClose={closeContextMenu} />;
        }
    }

    return { handlePaneContextMenu, handleNodeContextMenu, handleSelectionContextMenu, element };
}
