// Tidying the canvas: the steps laid out (autolayout.ts) as one step back in the undo history, then the workflow
// brought into view. A layout that would move nothing writes nothing and says so; the view is fitted either way, since
// bringing the whole workflow into view is the button's other job.
import { useCallback, type RefObject } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { toast } from 'sonner';
import { useNextFrame } from '@/lib/useLater';
import { autolayout } from './autolayout';

export interface TidyLayoutOptions {
    /** The graph as it stands when the layout is asked for. */
    nodesRef: RefObject<Node[]>;
    edgesRef: RefObject<Edge[]>;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    /** The undo history: the layout is one step in it. */
    history: { startBatch: () => void; endBatch: (nodes: Node[], edges: Edge[]) => void };
    /** Brings the whole workflow into view, a frame after the layout so the canvas has taken the new places. */
    fit: () => void;
}

export function useTidyLayout({ nodesRef, edgesRef, setNodes, history, fit }: TidyLayoutOptions): () => void {
    const { startBatch, endBatch } = history;
    const nextFrame = useNextFrame();
    return useCallback(() => {
        const nodes = nodesRef.current ?? [];
        const edges = edgesRef.current ?? [];
        if (nodes.length === 0) return;

        const laidOut = autolayout(nodes, edges);
        // The layout keeps the steps' order, so each is compared with its own new place (half a pixel is no move).
        const moved = laidOut.some((node, i) => Math.abs(node.position.x - nodes[i].position.x) > 0.5 || Math.abs(node.position.y - nodes[i].position.y) > 0.5);
        if (moved) {
            startBatch();
            setNodes(() => laidOut);
            endBatch(laidOut, edges);
        } else {
            toast.info('Already laid out', { description: 'Your workflow is already neatly arranged.', duration: 3000 });
        }
        nextFrame(fit);
    }, [nodesRef, edgesRef, setNodes, startBatch, endBatch, fit, nextFrame]);
}
