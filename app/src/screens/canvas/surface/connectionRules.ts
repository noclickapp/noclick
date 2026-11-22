// Which connections the canvas accepts between two steps, judged on the steps and connections it holds and what each
// step is by its type (the `canvas.step.roles` slot): the same rules the platform holds a workflow's edits to.
// - Nothing flows into a trigger, or to or from a step that talks through the SDK instead.
// - A connection is never doubled.
// - A step's top handle wires it into an agent's bottom as the agent's tools (an integration that offers its operations,
//   or one of NoClick's own tool steps), or an integration into an MCP server hosting its operations as tools. An agent's
//   bottom takes nothing else, and nothing else connects into an MCP server.
// - A step is an agent's tools or a step in the flow, never both, and never a tool while its operation starts runs.
import type { Connection, Edge, Node } from '@xyflow/react';
import { STRUCTURAL_TOOL_TYPES } from '../agentWiring';
import { fromHintHandleId } from '../nodes/NextStepHint';
import type { StepRoles } from '../slots';

export type ConnectionRoles = Pick<StepRoles, 'trigger' | 'tool' | 'connectionless'>;

/** Whether a step of `type` can wire its top into an agent's bottom as the agent's tools. */
export function feedsAgentTools(type: string | null | undefined, roles: Pick<StepRoles, 'tool'>): boolean {
    return (!!type && STRUCTURAL_TOOL_TYPES.has(type)) || roles.tool(type);
}

/** A connection dragged from a step's "what comes next" stub names the stub's handle: this names the step's own. */
export function normalizeConnection(connection: Connection): Connection {
    const real = fromHintHandleId(connection.sourceHandle);
    return real === undefined ? connection : { ...connection, sourceHandle: real };
}

const operationOf = (node: Node) => (node.data as { operation?: string } | undefined)?.operation;

/** Whether the canvas accepts `raw` among `nodes` and `edges` (the module's rules). */
export function connectionAllowed(raw: Connection | Edge, nodes: readonly Node[], edges: readonly Edge[], roles: ConnectionRoles): boolean {
    const connection = normalizeConnection(raw as Connection);
    const source = nodes.find((n) => n.id === connection.source);
    const target = nodes.find((n) => n.id === connection.target);
    if (!source || !target) return false;

    if (roles.connectionless(source.type) || roles.connectionless(target.type)) return false;

    // Two of the same connection would draw two chips and count the dependency twice.
    const same = (e: Edge) =>
        e.source === connection.source &&
        e.target === connection.target &&
        (e.sourceHandle ?? null) === (connection.sourceHandle ?? null) &&
        (e.targetHandle ?? null) === (connection.targetHandle ?? null);
    if (edges.some(same)) return false;

    // A trigger is where a run starts: its input isn't drawn, but a drop with no handle still lands on its body.
    if (roles.trigger(target.type, operationOf(target))) return false;

    if (feedsAgentTools(source.type, roles) && connection.sourceHandle === 'top') {
        const intoAgent = target.type === 'agent' && connection.targetHandle === 'bottom';
        // An MCP server hosts integrations' operations only (not another server, nor a tool step, whose tools aren't
        // operations), and only while it isn't pointed at a server of its own.
        const intoMcpHost =
            target.type === 'mcp-server' &&
            connection.targetHandle === 'bottom' &&
            roles.tool(source.type) &&
            !((target.data as { config?: { server_url?: string } } | undefined)?.config?.server_url || '').trim();
        if (!intoAgent && !intoMcpHost) return false;
        if (roles.trigger(source.type, operationOf(source))) return false;
        // Its output becomes the tools' description, which a step after it couldn't read.
        return !edges.some((e) => e.source === source.id && e.sourceHandle !== 'top');
    }

    // The same either-or from the other side: a step wired as an agent's tools takes no step after it.
    if (
        roles.tool(source.type) &&
        connection.sourceHandle !== 'top' &&
        edges.some((e) => e.source === source.id && e.sourceHandle === 'top' && e.targetHandle === 'bottom')
    ) {
        return false;
    }

    if (target.type === 'agent' && connection.targetHandle === 'bottom') {
        return feedsAgentTools(source.type, roles) && connection.sourceHandle === 'top';
    }

    // Nothing else connects into an MCP server: what it hosts wires into its bottom, and it takes no input in the flow.
    if (target.type === 'mcp-server') return false;

    return true;
}
