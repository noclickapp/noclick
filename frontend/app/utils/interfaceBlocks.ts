// Shared utilities for deriving interface blocks from workflow nodes/edges.
// Used by both FlowCanvas (editor) and PublicWorkflowView (read-only share page)
// to ensure consistent block filtering logic.

import { getBlockTypeForNodeType } from '~/components/interface/blockRegistry';

interface MinimalNode {
    id: string;
    type?: string;
    data?: Record<string, unknown>;
    config?: Record<string, unknown>;
}

interface MinimalEdge {
    source: string;
    target: string;
}

export interface InterfaceBlockEntry {
    id: string;
    blockType: string;
    nodeData: Record<string, unknown> | undefined;
}

/** Read a config field from either node shape (frontend nested at data.config.X, backend flat at config.X). */
function readConfigField(n: MinimalNode, key: string): unknown {
    const nested = (n.data?.config as Record<string, unknown> | undefined)?.[
        key
    ];
    if (nested !== undefined) return nested;
    return (n.config as Record<string, unknown> | undefined)?.[key];
}

/** An agent renders its chat in the Interface tab UNLESS `show_in_interface` is
 *  explicitly turned off (`"false"` / `false`). Absent, `"true"`, or a real
 *  boolean `true` all mean shown — so every agent is chattable by default and the
 *  user turns it off manually. Shared by all interface-block derivation sites. */
export function agentShowsInInterface(value: unknown): boolean {
    return value !== 'false' && value !== false;
}

/** The Test Run screen renders inside an agent's interface chat block, so a
 *  test-run hand-off into a workflow whose agents are all hidden would arm
 *  sticky flags nothing can consume (and the rehearsal would fire whenever a
 *  chat next mounts). Returns the agent to un-hide when the workflow has
 *  agents but none is shown, else null. */
export function hiddenAgentToRevealForTestRun(
    nodes: MinimalNode[]
): string | null {
    const agents = nodes.filter((n) => n.type === 'agent');
    if (agents.length === 0) return null;
    const anyVisible = agents.some((n) =>
        agentShowsInInterface(readConfigField(n, 'show_in_interface'))
    );
    return anyVisible ? null : agents[0].id;
}

/**
 * Derive interface blocks from workflow nodes.
 * Accepts both frontend format (node.data) and backend format (node.config).
 *
 * Includes:
 *   - All `interface-*` nodes (the original block surface).
 *   - Agent nodes shown in the interface (`show_in_interface` not explicitly
 *     `"false"`) — rendered as an agent-chat block driven directly by the config.
 */
export function deriveInterfaceBlocks(
    nodes: MinimalNode[],
    edges: MinimalEdge[]
): InterfaceBlockEntry[] {
    return nodes
        .filter((n) => {
            if (n.type?.startsWith('interface-')) return true;
            if (n.type === 'agent')
                return agentShowsInInterface(
                    readConfigField(n, 'show_in_interface')
                );
            return false;
        })
        .map((n) => ({
            id: n.id,
            blockType:
                getBlockTypeForNodeType(n.type!) ??
                n.type!.replace('interface-', ''),
            nodeData: (n.data ?? n.config) as
                | Record<string, unknown>
                | undefined,
        }));
}
