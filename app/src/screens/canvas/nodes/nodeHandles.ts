// nodeHandles — single source of truth for a node's handle topology (which of the
// four connection points exist on a node). Both the xyflow node components
// (AutomationNode derives showInput/showProvider from it) and xyflow-free
// canvases (which have no <Handle> to lean on) read from here, so the handle set
// — and therefore the connection dots + edge endpoints — can't drift between them.
// What a step is by its type (a trigger, an agent's tool) is handed in: the canvas's
// roles (`canvas.step.roles`), or a host's own reading of them.

import type { StepRoles } from '../slots';

export interface NodeHandleLayout {
    /** Left, target — normal dataflow input. */
    input: boolean;
    /** Right, source — normal dataflow output. */
    output: boolean;
    /** Top, source — wires this node into an agent/MCP-server bottom handle as a
     *  tool provider. */
    provider: boolean;
    /** Bottom, target — accepts tool providers (the agent node + hosting-mode
     *  MCP-server node). */
    agentTarget: boolean;
}

/**
 * Resolve which handles a node exposes, from its type + selected operation.
 * Mirrors the per-component <Handle> logic: the agent node (left/right/bottom),
 * the MCP-server node (top/bottom only, no dataflow), trigger nodes (output only —
 * the input is replaced by the amber bolt), tool-provider integrations
 * (left/right/top), and plain integration nodes (left/right).
 */
export function getNodeHandleLayout(
    type: string | undefined | null,
    operation: string | null | undefined,
    opts: { hideLeft?: boolean; hideRight?: boolean } | undefined,
    roles: Pick<StepRoles, 'trigger' | 'tool'>,
): NodeHandleLayout {
    if (type === 'agent') {
        return { input: true, output: true, provider: false, agentTarget: true };
    }
    if (type === 'mcp-server') {
        return { input: false, output: false, provider: true, agentTarget: true };
    }
    // Triggers are entry points: nothing flows in, and trigger/provider are
    // either-or, so only the output handle remains.
    if (roles.trigger(type, operation ?? null)) {
        return { input: false, output: !opts?.hideRight, provider: false, agentTarget: false };
    }
    return {
        input: !opts?.hideLeft,
        output: !opts?.hideRight,
        provider: roles.tool(type),
        agentTarget: false,
    };
}
