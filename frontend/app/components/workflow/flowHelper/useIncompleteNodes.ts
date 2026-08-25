import { useCallback, useEffect, useMemo, useState } from 'react';
import { Node } from '@xyflow/react';

interface UseIncompleteNodesParams {
    nodes: Node[];
    selectedNode: Node | null;
    /** Invoked when the user navigates via prev/next. */
    onSelectNode?: (nodeId: string) => void;
}

// Bundles the "which nodes are misconfigured + which one is currently focused"
// concern used by the full-screen incomplete-node navigator. Reads
// node.data.configValid (pre-computed upstream, avoids re-validating on drag)
// and keeps its internal index synced with the selection outside.
export function useIncompleteNodes({ nodes, selectedNode, onSelectNode }: UseIncompleteNodesParams) {
    const [incompleteNodeIndex, setIncompleteNodeIndex] = useState(0);

    const incompleteNodes = useMemo(
        () =>
            nodes.filter((node) => {
                if (node.id.startsWith('cursor-')) return false;
                return node.data?.configValid === false;
            }),
        [nodes]
    );

    // When the user selects an incomplete node via some other path (clicking on
    // the canvas, etc.), move our cursor to match so prev/next feel anchored.
    useEffect(() => {
        if (selectedNode && incompleteNodes.length > 0) {
            const idx = incompleteNodes.findIndex((n) => n.id === selectedNode.id);
            if (idx !== -1 && idx !== incompleteNodeIndex) {
                setIncompleteNodeIndex(idx);
            }
        }
    }, [selectedNode?.id, incompleteNodes, incompleteNodeIndex]);

    // Clamp the cursor if nodes were resolved and the list shrank past us.
    useEffect(() => {
        if (incompleteNodeIndex >= incompleteNodes.length) {
            setIncompleteNodeIndex(Math.max(0, incompleteNodes.length - 1));
        }
    }, [incompleteNodes.length, incompleteNodeIndex]);

    const prev = useCallback(() => {
        if (incompleteNodes.length === 0 || !onSelectNode) return;
        const newIndex = incompleteNodeIndex === 0 ? incompleteNodes.length - 1 : incompleteNodeIndex - 1;
        setIncompleteNodeIndex(newIndex);
        onSelectNode(incompleteNodes[newIndex].id);
    }, [incompleteNodes, incompleteNodeIndex, onSelectNode]);

    const next = useCallback(() => {
        if (incompleteNodes.length === 0 || !onSelectNode) return;
        const newIndex = incompleteNodeIndex === incompleteNodes.length - 1 ? 0 : incompleteNodeIndex + 1;
        setIncompleteNodeIndex(newIndex);
        onSelectNode(incompleteNodes[newIndex].id);
    }, [incompleteNodes, incompleteNodeIndex, onSelectNode]);

    return { incompleteNodes, incompleteNodeIndex, prev, next };
}
