// The canvas's right-click menus: on the empty canvas (add a step or a note, paste, select all, tidy the layout, fit it
// in view), on a step (open it, run from it, duplicate, copy, cut, turn it off, rename, delete) and on a selection drawn
// by a drag (the same for all of it). One hook: the three handlers React Flow takes, and the menu to draw. What only the
// canvas around it can do it's handed (opening the palette or a step's panel, a run); a choice it isn't handed isn't
// offered.
import { useCallback, useState, type MouseEvent as ReactMouseEvent, type ReactElement, type RefObject } from 'react';
import type { Edge, Node } from '@xyflow/react';
import {
    ClipboardPaste,
    Copy,
    Download,
    Eye,
    EyeOff,
    Maximize2,
    MousePointer2,
    Paintbrush,
    Pencil,
    Play,
    Plus,
    Repeat,
    Scissors,
    Settings2,
    StickyNote,
    Trash2,
    Upload,
} from 'lucide-react';
import { generateNodeId } from '@/lib/nodeIdGenerator';
import { createWorkflowNode, removeById } from '../applyNodeUpdate';
import { CanvasContextMenu, type ContextMenuItem } from './CanvasContextMenu';

// A right-click within this many pixels of the last one is the same place: the menu stays as it is (no flicker).
const SAME_PLACE_PX = 5;

type Point = { x: number; y: number };

type ContextMenuState =
    | { kind: 'pane'; px: Point; flow: Point }
    | { kind: 'node'; nodeId: string; px: Point }
    | { kind: 'selection'; nodeIds: string[]; px: Point }
    | null;

const isSamePlace = (a: Point, b: Point) => Math.abs(a.x - b.x) < SAME_PLACE_PX && Math.abs(a.y - b.y) < SAME_PLACE_PX;

/** What the host hears of a menu's edits, beyond the graph it holds. */
export interface ContextMenuListeners {
    /** A step the menu added, already in the graph: a note placed (`note`), or a copy of a step beside it
     *  (`duplicate`). */
    added?: (node: Node, how: 'note' | 'duplicate') => void;
    /** A step the menu removed (Delete, Cut), with its connections. */
    removed?: (nodeId: string) => void;
}

export interface CanvasContextMenuOptions {
    /** The steps as they stand, read when the menu is drawn and when a choice is made. */
    nodesRef: RefObject<Node[]>;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    setEdges: (update: (edges: Edge[]) => Edge[]) => void;
    screenToFlowPosition: (position: Point) => Point;
    fitView: (options?: { duration?: number; padding?: number; maxZoom?: number }) => void;
    /** Opens the palette for a step to add. */
    openPalette: () => void;
    /** Opens a step's panel; without it a step's menu has no Open. */
    openStep?: (nodeId: string) => void;
    /** Runs the workflow from a step; without it a step's menu has no Run. */
    runFrom?: (nodeId: string) => void;
    /** Changes a step's data (turning it off and on). */
    updateStep: (nodeId: string, data: Record<string, unknown>) => void;
    /** Lays the steps out. */
    tidy: () => void;
    copySelection: (nodeIds?: string[]) => Promise<void>;
    pasteFromClipboard: (position?: Point) => Promise<void>;
    /** Reads a workflow from a file and saves it to one, where the canvas offers them from this menu. */
    importFile?: () => void;
    exportFile?: () => void;
    on?: ContextMenuListeners;
}

export interface CanvasContextMenus {
    handlePaneContextMenu: (event: ReactMouseEvent | MouseEvent) => void;
    handleNodeContextMenu: (event: ReactMouseEvent, node: Node) => void;
    handleSelectionContextMenu: (event: ReactMouseEvent | MouseEvent, selectedNodes: Node[]) => void;
    /** The menu, drawn anywhere in the canvas (it places itself in the window); null while none is open. */
    element: ReactElement | null;
}

export function useCanvasContextMenu(options: CanvasContextMenuOptions): CanvasContextMenus {
    const { nodesRef, setNodes, setEdges, screenToFlowPosition, fitView, openPalette, openStep, runFrom, updateStep, tidy, copySelection, pasteFromClipboard, importFile, exportFile, on } = options;
    const added = on?.added;
    const removed = on?.removed;

    const [contextMenu, setContextMenu] = useState<ContextMenuState>(null);
    const closeContextMenu = useCallback(() => setContextMenu(null), []);

    // A right-click in the same place keeps the menu's state (nothing draws again); anywhere else, the menu's key
    // changes with its place and it opens anew there.
    const handlePaneContextMenu = useCallback(
        (event: ReactMouseEvent | MouseEvent) => {
            event.preventDefault();
            const px = { x: event.clientX, y: event.clientY };
            const flow = screenToFlowPosition(px);
            setContextMenu((prev) => (prev?.kind === 'pane' && isSamePlace(prev.px, px) ? prev : { kind: 'pane', px, flow }));
        },
        [screenToFlowPosition]
    );

    const handleNodeContextMenu = useCallback((event: ReactMouseEvent, node: Node) => {
        event.preventDefault();
        event.stopPropagation();
        const px = { x: event.clientX, y: event.clientY };
        setContextMenu((prev) => (prev?.kind === 'node' && prev.nodeId === node.id && isSamePlace(prev.px, px) ? prev : { kind: 'node', nodeId: node.id, px }));
    }, []);

    // A right-click inside a selection drawn by a drag: React Flow reports it here, not as a step's.
    const handleSelectionContextMenu = useCallback((event: ReactMouseEvent | MouseEvent, selectedNodes: Node[]) => {
        event.preventDefault();
        event.stopPropagation();
        const px = { x: event.clientX, y: event.clientY };
        const nodeIds = selectedNodes.map((n) => n.id);
        setContextMenu((prev) => (prev?.kind === 'selection' && isSamePlace(prev.px, px) ? prev : { kind: 'selection', nodeIds, px }));
    }, []);

    /** A note where the canvas was clicked. */
    const addStickyNoteAt = useCallback(
        (position: Point) => {
            const newNode = createWorkflowNode(generateNodeId('stickyNote'), 'stickyNote', position, { content: '', color: 8 });
            newNode.style = { width: 200, height: 200 };
            setNodes((prev) => [...prev, newNode]);
            added?.(newNode, 'note');
        },
        [setNodes, added]
    );

    const selectAllElements = useCallback(() => {
        setNodes((ns) => ns.map((n) => (n.selected ? n : { ...n, selected: true })));
        setEdges((es) => es.map((e) => (e.selected ? e : { ...e, selected: true })));
    }, [setNodes, setEdges]);

    /** A copy of a step beside it, with its settings and its size. */
    const duplicateNodeById = useCallback(
        (nodeId: string) => {
            const src = nodesRef.current?.find((n) => n.id === nodeId);
            if (!src || !src.type) return;
            const newPosition = { x: src.position.x + 40, y: src.position.y + 40 };
            const clonedData = JSON.parse(JSON.stringify(src.data ?? {}));
            const newNode = createWorkflowNode(generateNodeId(src.type), src.type, newPosition, clonedData);
            if (src.style) newNode.style = { ...src.style };
            if (src.width) newNode.width = src.width;
            if (src.height) newNode.height = src.height;
            setNodes((prev) => [...prev, newNode]);
            added?.(newNode, 'duplicate');
        },
        [nodesRef, setNodes, added]
    );

    /** A step gone, and the connections to and from it. */
    const deleteNodeById = useCallback(
        (nodeId: string) => {
            setNodes((prev) => removeById(prev, nodeId));
            setEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
            removed?.(nodeId);
        },
        [setNodes, setEdges, removed]
    );

    const buildItems = (): ContextMenuItem[] | null => {
        if (!contextMenu) return null;
        const nodes = nodesRef.current ?? [];
        if (contextMenu.kind === 'pane') {
            const items: ContextMenuItem[] = [
                { type: 'item', label: 'Add node', icon: <Plus className="h-3.5 w-3.5" />, shortcut: ['N'], onSelect: openPalette },
                { type: 'item', label: 'Add sticky note', icon: <StickyNote className="h-3.5 w-3.5" />, onSelect: () => addStickyNoteAt(contextMenu.flow) },
                { type: 'separator' },
                { type: 'item', label: 'Paste', icon: <ClipboardPaste className="h-3.5 w-3.5" />, shortcut: ['mod', 'V'], onSelect: () => pasteFromClipboard(contextMenu.px) },
                { type: 'item', label: 'Select all', icon: <MousePointer2 className="h-3.5 w-3.5" />, onSelect: selectAllElements },
                { type: 'separator' },
                { type: 'item', label: 'Auto-layout', icon: <Paintbrush className="h-3.5 w-3.5" />, onSelect: tidy },
                { type: 'item', label: 'Fit view', icon: <Maximize2 className="h-3.5 w-3.5" />, onSelect: () => fitView({ duration: 500, padding: 0.22, maxZoom: 1.0 }) },
            ];
            if (importFile || exportFile) {
                items.push({ type: 'separator' });
                if (importFile) items.push({ type: 'item', label: 'Import from a file', icon: <Upload className="h-3.5 w-3.5" />, onSelect: importFile });
                if (exportFile) items.push({ type: 'item', label: 'Export to a file', icon: <Download className="h-3.5 w-3.5" />, onSelect: exportFile });
            }
            return items;
        }
        if (contextMenu.kind === 'node') {
            const node = nodes.find((n) => n.id === contextMenu.nodeId);
            if (!node) return null;
            const isSticky = node.type === 'stickyNote';
            const isDisabled = !!node.data?.disabled;
            // Among selected steps, a step's Copy and Cut take them all.
            const selectedIds = nodes.filter((n) => n.selected).map((n) => n.id);
            const copyIds = selectedIds.includes(node.id) && selectedIds.length > 0 ? selectedIds : [node.id];
            const items: ContextMenuItem[] = [];
            if (!isSticky && (openStep || runFrom)) {
                if (openStep) items.push({ type: 'item', label: 'Open', icon: <Settings2 className="h-3.5 w-3.5" />, shortcut: ['enter'], onSelect: () => openStep(node.id) });
                if (runFrom) items.push({ type: 'item', label: 'Run from this node', icon: <Play className="h-3.5 w-3.5" />, onSelect: () => runFrom(node.id) });
                items.push({ type: 'separator' });
            }
            items.push({ type: 'item', label: 'Duplicate', icon: <Repeat className="h-3.5 w-3.5" />, onSelect: () => duplicateNodeById(node.id) });
            items.push({ type: 'item', label: 'Copy', icon: <Copy className="h-3.5 w-3.5" />, shortcut: ['mod', 'C'], onSelect: () => copySelection(copyIds) });
            items.push({
                type: 'item',
                label: 'Cut',
                icon: <Scissors className="h-3.5 w-3.5" />,
                onSelect: async () => {
                    await copySelection(copyIds);
                    copyIds.forEach(deleteNodeById);
                },
            });
            if (!isSticky) {
                items.push({ type: 'separator' });
                items.push({
                    type: 'item',
                    label: isDisabled ? 'Enable' : 'Disable',
                    icon: isDisabled ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />,
                    shortcut: ['D'],
                    onSelect: () => updateStep(node.id, { disabled: !isDisabled }),
                });
                items.push({
                    type: 'item',
                    label: 'Rename',
                    icon: <Pencil className="h-3.5 w-3.5" />,
                    // The step's own label hears this and turns into a field.
                    onSelect: () => {
                        document.dispatchEvent(new CustomEvent('noclick:node:start-rename', { detail: { nodeId: node.id } }));
                    },
                });
            }
            items.push({ type: 'separator' });
            items.push({ type: 'item', label: 'Delete', icon: <Trash2 className="h-3.5 w-3.5" />, shortcut: ['backspace'], destructive: true, onSelect: () => deleteNodeById(node.id) });
            return items;
        }
        const selNodes = nodes.filter((n) => contextMenu.nodeIds.includes(n.id));
        if (selNodes.length === 0) return null;
        const targetable = selNodes.filter((n) => n.type !== 'stickyNote');
        const allDisabled = targetable.length > 0 && targetable.every((n) => !!n.data?.disabled);
        const items: ContextMenuItem[] = [
            { type: 'item', label: `Duplicate (${selNodes.length})`, icon: <Repeat className="h-3.5 w-3.5" />, onSelect: () => selNodes.forEach((n) => duplicateNodeById(n.id)) },
            { type: 'item', label: `Copy (${selNodes.length})`, icon: <Copy className="h-3.5 w-3.5" />, shortcut: ['mod', 'C'], onSelect: () => copySelection(contextMenu.nodeIds) },
            {
                type: 'item',
                label: `Cut (${selNodes.length})`,
                icon: <Scissors className="h-3.5 w-3.5" />,
                onSelect: async () => {
                    await copySelection(contextMenu.nodeIds);
                    contextMenu.nodeIds.forEach(deleteNodeById);
                },
            },
        ];
        if (targetable.length > 0) {
            items.push({ type: 'separator' });
            items.push({
                type: 'item',
                label: allDisabled ? `Enable (${targetable.length})` : `Disable (${targetable.length})`,
                icon: allDisabled ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />,
                shortcut: ['D'],
                onSelect: () => {
                    targetable.forEach((n) => updateStep(n.id, { disabled: !allDisabled }));
                },
            });
        }
        items.push({ type: 'separator' });
        items.push({
            type: 'item',
            label: `Delete (${selNodes.length})`,
            icon: <Trash2 className="h-3.5 w-3.5" />,
            shortcut: ['backspace'],
            destructive: true,
            onSelect: () => contextMenu.nodeIds.forEach(deleteNodeById),
        });
        return items;
    };

    let element: ReactElement | null = null;
    if (contextMenu) {
        const items = buildItems();
        if (items) {
            const targetKey = contextMenu.kind === 'node' ? contextMenu.nodeId : contextMenu.kind === 'selection' ? contextMenu.nodeIds.join(',') : 'pane';
            const key = `${contextMenu.kind}:${targetKey}:${contextMenu.px.x},${contextMenu.px.y}`;
            element = <CanvasContextMenu key={key} position={contextMenu.px} items={items} onClose={closeContextMenu} />;
        }
    }

    return { handlePaneContextMenu, handleNodeContextMenu, handleSelectionContextMenu, element };
}
