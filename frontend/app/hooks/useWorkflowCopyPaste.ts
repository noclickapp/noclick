/**
 * useWorkflowCopyPaste - Handles copy/paste operations for workflow nodes and edges.
 * Supports multiple clipboard formats via the extensible clipboard parser system:
 * - NoClick's native workflow format
 * - n8n workflow imports (routed to backend for AI-powered conversion)
 * - Google Sheets URLs (auto-creates a pre-configured node)
 * Manages clipboard operations with intelligent positioning at cursor location.
 */
import { useCallback, useEffect, useRef, type MutableRefObject, type RefObject } from 'react';
import { Node, Edge } from '@xyflow/react';
import { toast } from 'sonner';
import { parseClipboardContent, detectN8nWorkflow } from '~/utils/clipboard-parsers';
import { autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelect';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';
import { getBlockTypeForNodeType } from '~/components/interface/blockRegistry';
import type { InterfaceGridState, WorkflowInterfaceHandle } from '~/components/interface/WorkflowInterface';

interface UseWorkflowCopyPasteProps {
    nodes: Node[];
    edges: Edge[];
    activeTab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources';
    setNodes: (setter: (prevNodes: Node[]) => Node[]) => void;
    setEdges: (setter: (prevEdges: Edge[]) => Edge[]) => void;
    screenToFlowPosition?: (position: { x: number; y: number }) => { x: number; y: number };
    captureState: (nodes: Node[], edges: Edge[]) => void;
    /**
     * Optional callback for handling n8n workflow paste.
     * When provided, n8n workflows will be routed to this callback for AI-powered
     * backend conversion instead of local conversion.
     * The callback receives the raw n8n JSON string.
     */
    onN8nWorkflowPaste?: (n8nJson: string) => void;
    /**
     * Optional callback to broadcast pasted nodes to collaborators.
     * Called for each node after it's added to the local state.
     */
    broadcastNodeAdd?: (node: Node) => void;
    /**
     * Optional callback to broadcast pasted edges to collaborators.
     * Called for each edge after it's added to the local state.
     */
    broadcastEdgeAdd?: (edge: Edge) => void;
    /** Ref to the current interface grid state (for including layout in copy) */
    interfaceGridStateRef?: MutableRefObject<InterfaceGridState | null>;
    /** Ref to the WorkflowInterface component (for applying layout on paste) */
    workflowInterfaceRef?: RefObject<WorkflowInterfaceHandle | null>;
}

export interface WorkflowCopyPasteApi {
    /** Serialize nodes/edges to the OS clipboard. With no args, copies the
     *  currently selected nodes (Cmd+C semantics). With overrideNodeIds, copies
     *  only the listed nodes (right-click "Copy" on a single node). */
    copySelection: (overrideNodeIds?: string[]) => Promise<void>;
    /** Read OS clipboard and apply to canvas. Optional positionPx overrides
     *  the tracked mouse position (use the context-menu click coordinates). */
    pasteFromClipboard: (positionPx?: { x: number; y: number }) => Promise<void>;
}

export const useWorkflowCopyPaste = ({
    nodes,
    edges,
    activeTab,
    setNodes,
    setEdges,
    screenToFlowPosition,
    captureState,
    onN8nWorkflowPaste,
    broadcastNodeAdd,
    broadcastEdgeAdd,
    interfaceGridStateRef,
    workflowInterfaceRef,
}: UseWorkflowCopyPasteProps): WorkflowCopyPasteApi => {
    // Track mouse position for paste positioning
    const mousePositionRef = useRef<{ x: number; y: number } | null>(null);

    // Track mouse position globally
    useEffect(() => {
        const handleMouseMove = (event: MouseEvent) => {
            mousePositionRef.current = { x: event.clientX, y: event.clientY };
        };

        window.addEventListener('mousemove', handleMouseMove);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
        };
    }, []);

    // Imperative copy: serialize nodes/edges to clipboard. Used by both the
    // Cmd+C event listener and the right-click context menu. With no args,
    // takes the currently selected nodes; with overrideNodeIds, takes exactly
    // those (right-click on a single node).
    const copySelection = useCallback(async (overrideNodeIds?: string[]) => {
        const selectedNodes = overrideNodeIds
            ? nodes.filter(node => overrideNodeIds.includes(node.id))
            : nodes.filter(node => node.selected);
        if (selectedNodes.length === 0) return;

        const selectedNodeIds = new Set(selectedNodes.map(n => n.id));
        const selectedEdges = edges.filter(edge =>
            selectedNodeIds.has(edge.source) && selectedNodeIds.has(edge.target)
        );

        const interfaceLayoutItems = interfaceGridStateRef?.current?.layout
            ?.filter(item => selectedNodeIds.has(item.i)) ?? [];

        const clipboardData: Record<string, unknown> = {
            type: 'noclick-workflow',
            version: '1.0',
            nodes: selectedNodes.map(node => {
                const config = buildSaveConfig(node);
                return {
                    id: node.id,
                    type: node.type,
                    position: node.position,
                    config,
                    // Preserve canvas dimensions for resizable nodes (interface blocks, sticky notes)
                    ...((node.width ?? (node.style as { width?: number } | undefined)?.width) ? { width: node.width ?? (node.style as { width?: number } | undefined)?.width } : {}),
                    ...((node.height ?? (node.style as { height?: number } | undefined)?.height) ? { height: node.height ?? (node.style as { height?: number } | undefined)?.height } : {}),
                };
            }),
            edges: selectedEdges.map(edge => ({
                id: edge.id,
                source: edge.source,
                target: edge.target,
                sourceHandle: edge.sourceHandle,
                targetHandle: edge.targetHandle,
                type: edge.type
            })),
            ...(interfaceLayoutItems.length > 0 ? { interface: { layout: interfaceLayoutItems } } : {}),
        };

        try {
            await navigator.clipboard.writeText(JSON.stringify(clipboardData, null, 2));
            const nodeLabel = `${selectedNodes.length} node${selectedNodes.length === 1 ? '' : 's'}`;
            const edgeLabel = selectedEdges.length > 0
                ? ` and ${selectedEdges.length} edge${selectedEdges.length === 1 ? '' : 's'}`
                : '';
            toast.success(`Copied ${nodeLabel}${edgeLabel}`);
        } catch (err) {
            console.error('Failed to copy to clipboard:', err);
            toast.error('Failed to copy to clipboard');
        }
    }, [nodes, edges, interfaceGridStateRef]);

    // Imperative paste: apply clipboard text to canvas. Used by both the
    // Cmd+V event listener and the right-click context menu. Returns silently
    // on parse failure (matching the event-listener behavior).
    const applyClipboardText = useCallback((clipboardText: string, positionPx?: { x: number; y: number }) => {
        const result = parseClipboardContent(clipboardText);
        if (!result) return;

        console.log(`Pasting ${result.nodes.length} nodes and ${result.edges.length} edges`);

        let minX = Infinity;
        let minY = Infinity;
        result.nodes.forEach((node) => {
            minX = Math.min(minX, node.position.x);
            minY = Math.min(minY, node.position.y);
        });

        let targetFlowPosition = { x: 100, y: 100 };
        const sourcePx = positionPx ?? mousePositionRef.current;
        if (sourcePx && screenToFlowPosition) {
            targetFlowPosition = screenToFlowPosition(sourcePx);
        }

        const offsetX = targetFlowPosition.x - minX;
        const offsetY = targetFlowPosition.y - minY;

        const repositionedNodes = result.nodes.map((node) => ({
            ...node,
            position: { x: node.position.x + offsetX, y: node.position.y + offsetY },
        }));

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

        if (broadcastNodeAdd) repositionedNodes.forEach(node => broadcastNodeAdd(node));
        if (broadcastEdgeAdd) result.edges.forEach(edge => broadcastEdgeAdd(edge));

        setTimeout(() => captureState(newNodes, newEdges), 0);

        // Auto-select credentials for pasted nodes. null workflowId → the open workflow.
        repositionedNodes.forEach((node) => autoSelectCredentialsForNewNode(node, setNodes, null));

        if (result.interface?.layout?.length && interfaceGridStateRef) {
            const existingLayout = interfaceGridStateRef.current?.layout ?? [];
            const merged = [...existingLayout, ...result.interface.layout];
            interfaceGridStateRef.current = { layout: merged };
            workflowInterfaceRef?.current?.setFullState({ layout: merged });
        }

        repositionedNodes.forEach((node) => {
            if (node.type?.startsWith('interface-')) {
                const blockType = getBlockTypeForNodeType(node.type);
                if (blockType) workflowInterfaceRef?.current?.addBlock(node.id, blockType);
            }
        });

        console.log(`Positioned nodes at cursor (offset: ${offsetX.toFixed(0)}, ${offsetY.toFixed(0)})`);
    }, [setNodes, setEdges, screenToFlowPosition, captureState, broadcastNodeAdd, broadcastEdgeAdd, interfaceGridStateRef, workflowInterfaceRef]);

    const pasteFromClipboard = useCallback(async (positionPx?: { x: number; y: number }) => {
        let clipboardText = '';
        try {
            clipboardText = await navigator.clipboard.readText();
        } catch (err) {
            console.error('Failed to read clipboard:', err);
            toast.error('Failed to read clipboard');
            return;
        }
        if (!clipboardText) return;
        if (onN8nWorkflowPaste && detectN8nWorkflow(clipboardText)) {
            onN8nWorkflowPaste(clipboardText);
            return;
        }
        applyClipboardText(clipboardText, positionPx);
    }, [applyClipboardText, onN8nWorkflowPaste]);

    // Handle copy for selected nodes/edges (Cmd/Ctrl+C). Editable-element /
    // text-selection guards live here so the imperative copySelection() doesn't
    // inherit them (a menu click is unambiguously a canvas-copy intent).
    useEffect(() => {
        const handleCopy = async (event: ClipboardEvent) => {
            if (activeTab !== 'canvas') return;

            const activeElement = document.activeElement;
            const isEditableElement = activeElement instanceof HTMLInputElement ||
                activeElement instanceof HTMLTextAreaElement ||
                activeElement?.getAttribute('contenteditable') === 'true';
            const selection = window.getSelection();
            const hasTextSelection = selection && selection.toString().length > 0;
            if (isEditableElement || hasTextSelection) return;

            const selectedNodes = nodes.filter(node => node.selected);
            if (selectedNodes.length === 0) return;

            event.preventDefault();
            await copySelection();
        };

        window.addEventListener('copy', handleCopy);
        return () => window.removeEventListener('copy', handleCopy);
    }, [activeTab, nodes, copySelection]);

    // Handle clipboard paste for all supported formats (NoClick, n8n, Google Sheets URLs, etc.).
    useEffect(() => {
        const handlePaste = (event: ClipboardEvent) => {
            if (activeTab !== 'canvas') return;

            const clipboardText = event.clipboardData?.getData('text/plain');
            if (!clipboardText) return;

            // n8n workflow paste: intercept even inside inputs so the JSON
            // doesn't dump into the field as raw text — we replace it with
            // the import pill and kick off the agentic conversion.
            if (onN8nWorkflowPaste && detectN8nWorkflow(clipboardText)) {
                event.preventDefault();
                event.stopPropagation();
                console.log('[useWorkflowCopyPaste] Detected n8n workflow, routing to backend for AI conversion');
                onN8nWorkflowPaste(clipboardText);
                return;
            }

            const activeElement = document.activeElement;
            const isEditableElement = activeElement instanceof HTMLInputElement ||
                activeElement instanceof HTMLTextAreaElement ||
                activeElement?.getAttribute('contenteditable') === 'true';
            if (isEditableElement) return;

            const result = parseClipboardContent(clipboardText);
            if (!result) return;

            event.preventDefault();
            applyClipboardText(clipboardText);
        };

        // Use the capture phase so the handler runs BEFORE an input's native
        // text-insertion when the user pastes n8n JSON into a focused field —
        // otherwise the JSON would land in the input as raw text before we
        // get a chance to preventDefault.
        window.addEventListener('paste', handlePaste, true);
        return () => window.removeEventListener('paste', handlePaste, true);
    }, [activeTab, onN8nWorkflowPaste, applyClipboardText]);

    return { copySelection, pasteFromClipboard };
};
