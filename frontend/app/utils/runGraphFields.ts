import type { serializeGraphForExecution } from '~/utils/workflowNodeExecution';

type RunGraph = ReturnType<typeof serializeGraphForExecution>;

/** The graph a workflow:execute request carries. An editor runs the canvas as
 *  drawn; someone who can only view the workflow runs it as saved, so their
 *  request names no graph (the server refuses one from a viewer). */
export function runGraphFields(
    canEdit: boolean,
    executed: RunGraph,
    replay: RunGraph = executed
): Partial<{
    nodes: RunGraph['nodes'];
    edges: RunGraph['edges'];
    replay_nodes: RunGraph['nodes'];
    replay_edges: RunGraph['edges'];
}> {
    if (!canEdit) return {};
    return {
        nodes: executed.nodes,
        edges: executed.edges,
        replay_nodes: replay.nodes,
        replay_edges: replay.edges,
    };
}
