/**
 * Custom hook for workflow canvas undo/redo functionality with keyboard shortcuts.
 * Tracks combined nodes + edges state as single history entries and batches rapid updates like drag operations.
 */
import { useCallback, useRef, useEffect, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';

interface WorkflowState {
    nodes: Node[];
    edges: Edge[];
}

interface HistoryState {
    past: WorkflowState[];
    present: WorkflowState;
    future: WorkflowState[];
}

interface UseWorkflowUndoRedoOptions {
    historyLimit?: number;
    onNodesChange: (nodes: Node[]) => void;
    onEdgesChange: (edges: Edge[]) => void;
    /** Collaboration callbacks for broadcasting changes to other users */
    onNodeAdded?: (node: Node) => void;
    onNodeRemoved?: (nodeId: string) => void;
    onEdgeAdded?: (edge: Edge) => void;
    onEdgeRemoved?: (edgeId: string) => void;
    /** Callback for broadcasting node position changes (for undo/redo of drag operations) */
    onNodePositionChange?: (nodeId: string, position: { x: number; y: number }) => void;
}

interface UseWorkflowUndoRedoReturn {
    undo: () => void;
    redo: () => void;
    canUndo: boolean;
    canRedo: boolean;
    captureState: (nodes: Node[], edges: Edge[]) => void;
    startBatch: () => void;
    endBatch: (nodes: Node[], edges: Edge[]) => void;
    resetBaseline: (nodes: Node[], edges: Edge[]) => void;
}

/**
 * Custom hook for managing undo/redo functionality in workflow canvas
 *
 * Features:
 * - Tracks combined nodes + edges state as single history entries
 * - Batches rapid updates (like drag operations) to prevent history spam
 * - Keyboard shortcuts: Cmd+Z/Ctrl+Z (undo), Cmd+Shift+Z/Ctrl+Shift+Z (redo)
 * - Configurable history limit to prevent memory issues
 */
export function useWorkflowUndoRedo(
    initialNodes: Node[],
    initialEdges: Edge[],
    options: UseWorkflowUndoRedoOptions
): UseWorkflowUndoRedoReturn {
    const {
        historyLimit = 50,
        onNodesChange,
        onEdgesChange,
        onNodeAdded,
        onNodeRemoved,
        onEdgeAdded,
        onEdgeRemoved,
        onNodePositionChange,
    } = options;

    // History state
    const historyRef = useRef<HistoryState>({
        past: [],
        present: { nodes: initialNodes, edges: initialEdges },
        future: [],
    });

    // Track if we're currently in a batch operation (e.g., dragging)
    const isBatchingRef = useRef(false);

    // Track if we're applying a history state (to prevent adding it back to history)
    const isApplyingHistoryRef = useRef(false);

    // Force re-render when canUndo/canRedo state changes
    const [, forceUpdate] = useState({});

    const canUndo = historyRef.current.past.length > 0;
    const canRedo = historyRef.current.future.length > 0;

    /**
     * Check if two states are identical (deep comparison for nodes/edges)
     */
    const areStatesEqual = useCallback((state1: WorkflowState, state2: WorkflowState): boolean => {
        if (state1.nodes.length !== state2.nodes.length || state1.edges.length !== state2.edges.length) {
            return false;
        }

        // Compare nodes by ID and position (ignore other changes during drag).
        // Optional-chained: a position-less node must compare, not throw —
        // this comparator runs on EVERY state capture, and one bad node used
        // to crash undo snapshotting for the whole session (2026-08-04).
        const nodesEqual = state1.nodes.every((node, i) => {
            const node2 = state2.nodes[i];
            return node.id === node2.id &&
                   node.position?.x === node2.position?.x &&
                   node.position?.y === node2.position?.y &&
                   node.type === node2.type;
        });

        // Compare edges by connections
        const edgesEqual = state1.edges.every((edge, i) => {
            const edge2 = state2.edges[i];
            return edge.id === edge2.id &&
                   edge.source === edge2.source &&
                   edge.target === edge2.target;
        });

        return nodesEqual && edgesEqual;
    }, []);

    /**
     * Capture current state to history (unless we're batching or applying history)
     */
    const captureState = useCallback((nodes: Node[], edges: Edge[]) => {
        // Don't capture if we're applying history or batching
        if (isApplyingHistoryRef.current || isBatchingRef.current) {
            return;
        }

        const newState = { nodes: [...nodes], edges: [...edges] };

        // Don't add a history entry when nothing structural changed. BUT still
        // refresh `present` so it tracks the latest node objects: areStatesEqual
        // compares only id/position/type, so config-only edits (operation,
        // credentials, field values) don't qualify as a new entry — yet `present`
        // MUST reflect them. Otherwise the next structural change (e.g. deleting
        // the node) snapshots a STALE pre-config version, and undo brings the node
        // back with its operation/credentials wiped.
        if (areStatesEqual(newState, historyRef.current.present)) {
            historyRef.current.present = newState;
            return;
        }

        // Add current present to past
        const newPast = [...historyRef.current.past, historyRef.current.present];

        // Limit history size
        if (newPast.length > historyLimit) {
            newPast.shift(); // Remove oldest entry
        }

        // Update history
        historyRef.current = {
            past: newPast,
            present: newState,
            future: [], // Clear future on new action
        };

        forceUpdate({});
    }, [historyLimit, areStatesEqual]);

    /**
     * Re-anchor history at the given state: it becomes `present` with no
     * past/future. Called after the authoritative workflow:get load so undo
     * can never walk below the loaded graph — the hook mounts with an empty
     * canvas. Without this reset, that empty state sits at the bottom of
     * the stack and repeated undo can delete every loaded node. Also drops
     * history from a
     * previously-viewed workflow when the canvas switches ids in place.
     */
    const resetBaseline = useCallback((nodes: Node[], edges: Edge[]) => {
        historyRef.current = {
            past: [],
            present: { nodes: [...nodes], edges: [...edges] },
            future: [],
        };
        forceUpdate({});
    }, []);

    /**
     * Start a batch operation (e.g., drag start)
     */
    const startBatch = useCallback(() => {
        isBatchingRef.current = true;
    }, []);

    /**
     * End a batch operation and capture final state (e.g., drag end)
     */
    const endBatch = useCallback((nodes: Node[], edges: Edge[]) => {
        isBatchingRef.current = false;
        captureState(nodes, edges);
    }, [captureState]);

    /**
     * Broadcast collaboration changes when transitioning between states
     */
    const broadcastChanges = useCallback((oldState: WorkflowState, newState: WorkflowState) => {
        // Build maps for efficient lookup
        const oldNodesMap = new Map(oldState.nodes.map(n => [n.id, n]));
        const newNodesMap = new Map(newState.nodes.map(n => [n.id, n]));
        const oldNodeIds = new Set(oldState.nodes.map(n => n.id));
        const newNodeIds = new Set(newState.nodes.map(n => n.id));

        // Find removed nodes (in old but not in new)
        oldState.nodes.forEach(node => {
            if (!newNodeIds.has(node.id)) {
                onNodeRemoved?.(node.id);
            }
        });

        // Find added nodes (in new but not in old)
        newState.nodes.forEach(node => {
            if (!oldNodeIds.has(node.id)) {
                onNodeAdded?.(node);
            }
        });

        // Find nodes with changed positions (exist in both but position differs)
        newState.nodes.forEach(newNode => {
            const oldNode = oldNodesMap.get(newNode.id);
            if (oldNode && (oldNode.position.x !== newNode.position.x || oldNode.position.y !== newNode.position.y)) {
                onNodePositionChange?.(newNode.id, newNode.position);
            }
        });

        // Find removed edges (in old but not in new)
        const oldEdgeIds = new Set(oldState.edges.map(e => e.id));
        const newEdgeIds = new Set(newState.edges.map(e => e.id));

        oldState.edges.forEach(edge => {
            if (!newEdgeIds.has(edge.id)) {
                onEdgeRemoved?.(edge.id);
            }
        });

        // Find added edges (in new but not in old)
        newState.edges.forEach(edge => {
            if (!oldEdgeIds.has(edge.id)) {
                onEdgeAdded?.(edge);
            }
        });
    }, [onNodeAdded, onNodeRemoved, onEdgeAdded, onEdgeRemoved, onNodePositionChange]);

    /**
     * Undo to previous state
     */
    const undo = useCallback(() => {
        if (!canUndo) return;

        const oldPresent = historyRef.current.present;
        const newPast = [...historyRef.current.past];
        const newPresent = newPast.pop()!;
        const newFuture = [oldPresent, ...historyRef.current.future];

        historyRef.current = {
            past: newPast,
            present: newPresent,
            future: newFuture,
        };

        // Apply the state without capturing it back to history
        isApplyingHistoryRef.current = true;
        // Strip transition styles to ensure instant position change (no animation)
        const nodesWithoutTransition = newPresent.nodes.map(node => {
            if (node.style?.transition) {
                const { transition, ...restStyle } = node.style;
                return { ...node, style: Object.keys(restStyle).length > 0 ? restStyle : undefined };
            }
            return node;
        });
        onNodesChange(nodesWithoutTransition);
        onEdgesChange(newPresent.edges);

        // Broadcast changes to collaborators
        broadcastChanges(oldPresent, newPresent);

        setTimeout(() => {
            isApplyingHistoryRef.current = false;
        }, 0);

        forceUpdate({});
    }, [canUndo, onNodesChange, onEdgesChange, broadcastChanges]);

    /**
     * Redo to next state
     */
    const redo = useCallback(() => {
        if (!canRedo) return;

        const oldPresent = historyRef.current.present;
        const newFuture = [...historyRef.current.future];
        const newPresent = newFuture.shift()!;
        const newPast = [...historyRef.current.past, oldPresent];

        historyRef.current = {
            past: newPast,
            present: newPresent,
            future: newFuture,
        };

        // Apply the state without capturing it back to history
        isApplyingHistoryRef.current = true;
        // Strip transition styles to ensure instant position change (no animation)
        const nodesWithoutTransition = newPresent.nodes.map(node => {
            if (node.style?.transition) {
                const { transition, ...restStyle } = node.style;
                return { ...node, style: Object.keys(restStyle).length > 0 ? restStyle : undefined };
            }
            return node;
        });
        onNodesChange(nodesWithoutTransition);
        onEdgesChange(newPresent.edges);

        // Broadcast changes to collaborators
        broadcastChanges(oldPresent, newPresent);

        setTimeout(() => {
            isApplyingHistoryRef.current = false;
        }, 0);

        forceUpdate({});
    }, [canRedo, onNodesChange, onEdgesChange, broadcastChanges]);

    /**
     * Keyboard shortcuts for undo/redo
     */
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            // Typing surfaces own their undo: hijacking Cmd+Z from a chat
            // box / config field / CodeMirror into a CANVAS undo both breaks
            // text editing and can silently rip nodes out of the graph.
            const target = event.target as HTMLElement | null;
            if (
                target &&
                (target.isContentEditable ||
                    target.closest?.(
                        'input, textarea, select, [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]'
                    ))
            ) {
                return;
            }
            const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
            const isCtrlOrCmd = isMac ? event.metaKey : event.ctrlKey;

            // Undo: Cmd+Z or Ctrl+Z
            if (isCtrlOrCmd && event.key === 'z' && !event.shiftKey) {
                event.preventDefault();
                undo();
            }
            // Redo: Cmd+Shift+Z or Ctrl+Shift+Z
            else if (isCtrlOrCmd && event.key === 'z' && event.shiftKey) {
                event.preventDefault();
                redo();
            }
            // Alternative Redo: Cmd+Y or Ctrl+Y
            else if (isCtrlOrCmd && event.key === 'y') {
                event.preventDefault();
                redo();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [undo, redo]);

    return {
        undo,
        redo,
        canUndo,
        canRedo,
        captureState,
        startBatch,
        endBatch,
        resetBaseline,
    };
}
