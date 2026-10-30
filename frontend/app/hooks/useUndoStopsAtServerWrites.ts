// Undo walks back the person's own edits, never a written server change (an API edit, the coordinator's, a
// restore): when the workflow's room says a write landed, the canvas's undo history starts again from the graph as
// it now stands. Otherwise an undo after such a write would restore the steps as they were before it, and the
// canvas's three-way merge would save that as the person's change, putting the write back.
import { useEffect } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { snapshot } from 'valtio';
import { graphRecords } from '~/lib/liveGraphStore';
import { onSocketEvent } from '~/lib/socket-receiver';

export function useUndoStopsAtServerWrites(
    workflowId: string | undefined,
    resetBaseline: (nodes: Node[], edges: Edge[]) => void,
): void {
    useEffect(() => {
        if (!workflowId) return;
        return onSocketEvent('workflow:graph_changed', (data) => {
            const rec = graphRecords[workflowId];
            if (data?.workflow_id !== workflowId || !rec) return;
            const { nodes, edges } = snapshot(rec);
            resetBaseline(nodes as Node[], edges as Edge[]);
        });
    }, [workflowId, resetBaseline]);
}
