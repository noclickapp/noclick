// Regression test for the agent-scaffold autolayout bug: provider (tool) nodes
// wired into the agent's bottom handle must be laid out BELOW the agent, not as
// upstream dataflow to its left. The bug was that the autolayout provider-edge
// fallback only recognized `tool`/`mcp-server` source types, so an integration
// provider (automation-slack) whose `targetHandle` was dropped in the builder
// round-trip got mislaid out. Runs in the browser (autolayout imports the node
// registry, so it can't be a vitest unit test).
import { buildAgentScaffold } from '~/lib/agentScaffold';
import { autolayout } from '~/utils/autolayout';
import type { Node, Edge } from '@xyflow/react';

export default async function () {
    const intent = buildAgentScaffold({
        harnessModel: 'claude-code',
        harnessLabel: 'Claude Code',
        message: 'go',
        triggers: [{ type: 'trigger-webhook', label: 'Webhook' }],
        integrations: [
            { type: 'automation-slack', label: 'Slack' },
            { type: 'automation-linear', label: 'Linear' },
        ],
    });

    const nodes = intent.workflowData.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: { config: n.config },
    })) as unknown as Node[];
    const edges = intent.workflowData.edges as unknown as Edge[];
    const toolIds = nodes.filter((n) => n.type?.startsWith('automation-')).map((n) => n.id);

    const toolsBelowAgent = (laid: Node[]) => {
        const pos = new Map(laid.map((n) => [n.id, n.position]));
        const agentY = pos.get('agent')?.y ?? 0;
        return toolIds.every((id) => (pos.get(id)?.y ?? 0) > agentY + 50);
    };

    // Handles intact (what the scaffold emits) -> tools below the agent.
    if (!toolsBelowAgent(autolayout(structuredClone(nodes), structuredClone(edges)))) {
        throw new Error('Provider tools not laid out below agent with intact handles');
    }

    // targetHandle stripped (simulating a serialization hop dropping it) -> the
    // sourceHandle === 'top' fallback must still place tools below the agent.
    const stripped = (structuredClone(edges) as Edge[]).map((e) =>
        e.target === 'agent' && e.sourceHandle === 'top' ? { ...e, targetHandle: undefined } : e,
    );
    if (!toolsBelowAgent(autolayout(structuredClone(nodes), stripped))) {
        throw new Error('Provider tools not laid out below agent when targetHandle is missing (fallback failed)');
    }

    return { passed: true, toolIds };
}
