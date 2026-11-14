// An agent's own flow is the agent's, not an automation: `workflow:get` names the agent a workflow belongs to, and
// the app opens that agent where it would have opened the canvas. The deployment that keeps agents registers where.
import type { WorkflowAgentRef } from '~/types/socket-events.generated';

let opener: ((agentId: string) => void) | null = null;

/** Where the deployment opens one of the account's agents (Work, on the hosted service). */
export function registerAgentOpener(open: (agentId: string) => void): void {
    opener = open;
}

/** How `agent` opens in its flow's place: the viewer's own agent, where agents open; else null (it can't be). */
export function agentOpenerFor(agent: WorkflowAgentRef): (() => void) | null {
    const open = opener;
    return agent.yours && open ? () => open(agent.id) : null;
}
