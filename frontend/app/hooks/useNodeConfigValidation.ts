import { useEffect, useRef } from 'react';
import type { Node } from '@xyflow/react';
import { applyNodeUpdate } from '~/lib/applyNodeUpdate';
import { validateNode, type NodeValidationContext } from '~/utils/workflowNodeValidation';

interface UseNodeConfigValidationParams {
    nodes: Node[];
    /** Precomputed, content-stable wiring context (agent tool-provider mode).
     *  Stable identity matters: it's an effect dep, and edges churn (e.g.
     *  selection) must not retrigger validation passes. */
    validationContext?: NodeValidationContext;
    setNodes: (updater: (prev: Node[]) => Node[]) => void;
    /** When true, skip validation entirely — run will resume on drag end. */
    isDraggingRef: React.MutableRefObject<boolean>;
}

// Runs validateNode on every non-cursor node and updates its configValid
// flag (used to paint the yellow "incomplete" border on the canvas).
//
// Each pass compares validateNode's result against the node's *current*
// data.configValid and only writes the nodes that actually differ — so a
// clean pass produces no setNodes call and no array churn.
//
// It is important to compare against the live node data, NOT a cached prior
// result: a workflow:get re-sync (or cache-restore) replaces every node object
// with backend state, and configValid — a runtime-only field — is absent on
// those. A value-vs-value cache would compute the same isComplete result,
// conclude "nothing changed", and never re-write the flag, leaving every node
// stuck with configValid === undefined.
//
// Validation is skipped entirely while dragging (configValid can't change
// mid-drag, and running validateNode in the drag's raf loop tanks framerate).
export function useNodeConfigValidation({ nodes, validationContext, setNodes, isDraggingRef }: UseNodeConfigValidationParams) {
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        if (isDraggingRef.current) return;

        if (timeoutRef.current) clearTimeout(timeoutRef.current);

        // Debounce so rapid sequential node updates only trigger one validation pass
        timeoutRef.current = setTimeout(() => {
            const updates: Array<{ id: string; configValid: boolean }> = [];

            for (const node of nodes) {
                if (node.id.startsWith('cursor-')) continue;
                const configValid = validateNode(node, validationContext).isComplete;
                if (node.data?.configValid !== configValid) {
                    updates.push({ id: node.id, configValid });
                }
            }

            if (updates.length > 0) {
                setNodes((prevNodes) =>
                    prevNodes.map((n) => {
                        const update = updates.find((u) => u.id === n.id);
                        return update ? applyNodeUpdate(n, { configValid: update.configValid }) : n;
                    })
                );
            }
        }, 100);

        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [nodes, validationContext, setNodes, isDraggingRef]);
}
