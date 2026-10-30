// Undo walks back the person's own edits, never a written server change (an API edit, the coordinator's, a
// restore, NoClick filling in a trigger's webhook and schedule fields): each change the canvas takes from the server
// is applied to every state in its undo history, and a conflict or re-read that takes the server's graph wholesale
// starts the history again from the graph as it then stands. Otherwise an undo after such a write would restore the
// steps as they were before it, and the canvas's three-way merge would save that as the person's change.
import { useEffect } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { snapshot } from 'valtio';
import { graphRecords, onServerChange } from '~/lib/liveGraphStore';
import { serverEdgesAfter, serverNodesAfter } from '~/lib/serverGraphEvents';

type State = { nodes: Node[]; edges: Edge[] };

export function useUndoKeepsServerWrites(
    workflowId: string | undefined,
    rebaseHistory: (change: (state: State) => State) => void,
    resetBaseline: (nodes: Node[], edges: Edge[]) => void,
): void {
    useEffect(() => {
        if (!workflowId) return;
        return onServerChange((changed, change) => {
            if (changed !== workflowId) return;
            if (change) {
                const { eventType, data } = change;
                rebaseHistory((state) => ({
                    nodes: serverNodesAfter(state.nodes, eventType, data),
                    edges: serverEdgesAfter(state.edges, eventType, data),
                }));
                return;
            }
            const rec = graphRecords[workflowId];
            if (!rec) return;
            const { nodes, edges } = snapshot(rec);
            resetBaseline(nodes as Node[], edges as Edge[]);
        });
    }, [workflowId, rebaseHistory, resetBaseline]);
}
