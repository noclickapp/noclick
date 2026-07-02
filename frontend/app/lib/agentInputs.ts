// Groups an agent response's resolved input deliveries (from the
// workflow:get_agent_inputs socket call) into per-node groups for the run-results
// inputs rail. Each group is one distinct node that ran across the consumed
// deliveries, carrying its per-delivery runs so the rail can show a ×N badge and
// cycle between the outputs. Added for the "what fed this response" sidebar.

export interface AgentInputRun {
    executionId: string;
    status: string | null;
    output: unknown;
}

export interface AgentInputGroup {
    nodeId: string;
    label: string;
    iconHtml?: string;
    iconColor?: string;
    nodeType: string;
    /** One entry per delivery this node ran in (length > 1 → the ×N + cycling case). */
    runs: AgentInputRun[];
}

interface RawInput {
    execution_id: string;
    nodes: Array<{ node_id: string; status: string | null; output: unknown }>;
}
interface GraphNodeLite {
    id: string;
    type?: string;
    data?: { label?: string };
}
type IconMeta = { label?: string; iconHtml?: string; iconColor?: string } | undefined;

/** Fold the raw per-delivery node lists into per-node groups, enriching each with
 *  label/icon from the current graph (a node deleted since the run falls back to its
 *  id). Preserves delivery order within each group so cycling is chronological. */
export function groupAgentInputs(
    inputs: RawInput[],
    nodes: GraphNodeLite[],
    getMeta: (type: string) => IconMeta,
): AgentInputGroup[] {
    const byNode = new Map<string, AgentInputGroup>();
    for (const inp of inputs || []) {
        for (const n of inp.nodes || []) {
            let group = byNode.get(n.node_id);
            if (!group) {
                const gn = nodes.find(x => x.id === n.node_id);
                const type = gn?.type || '';
                const meta = getMeta(type);
                group = {
                    nodeId: n.node_id,
                    nodeType: type,
                    label: gn?.data?.label || meta?.label || type || n.node_id,
                    iconHtml: meta?.iconHtml,
                    iconColor: meta?.iconColor,
                    runs: [],
                };
                byNode.set(n.node_id, group);
            }
            group.runs.push({ executionId: inp.execution_id, status: n.status, output: n.output });
        }
    }
    return Array.from(byNode.values());
}
