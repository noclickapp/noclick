// Unit tests for the agent-harness scaffold builder. Verifies the workflow blob
// the /agents one-click button hands to WorkflowCreateRequest: an agent node
// configured to the harness, near-bare provider nodes (no operation / allowlist)
// and integration trigger nodes carrying their default trigger op (so they fire
// and render the trigger bolt; the internal AI builder refines them post-open),
// tools edges wired top -> bottom (the signal the backend reads to treat a node
// as a tool provider), trigger edges into the agent's left handle, and a
// builderPrompt that guides the user through choosing the trigger + tool operations.

import { describe, it, expect } from 'vitest';
import { buildAgentScaffold } from '~/lib/agentScaffold';

describe('buildAgentScaffold', () => {
    it('wires a single provider into the agent bottom handle, with no operation pre-selected', () => {
        const { name, workflowData, builderPrompt } = buildAgentScaffold({
            harnessModel: 'claude-code',
            harnessLabel: 'Claude Code',
            message: 'Help me with Slack.',
            integrations: [{ type: 'automation-slack', label: 'Slack' }],
        });
        const { nodes, edges } = workflowData;

        expect(nodes).toHaveLength(2);

        const agent = nodes.find((n) => n.type === 'agent')!;
        expect(agent).toBeTruthy();
        // model drives backend infer_model_type -> the harness; message is required.
        expect(agent.config.model).toBe('claude-code');
        expect(agent.config.message).toBe('Help me with Slack.');
        // show_in_interface isn't seeded — agents show by default (shown unless
        // explicitly "false"), so the scaffold leaves the field unset.
        expect(agent.config.show_in_interface).toBeUndefined();

        const provider = nodes.find((n) => n.type === 'automation-slack')!;
        expect(provider).toBeTruthy();
        expect(provider.config.label).toBe('Slack');
        // Bare scaffold: operation + allowlist are left for the builder to set.
        expect(provider.config.operation).toBeUndefined();
        expect(provider.config.agent_tool_operations).toBeUndefined();

        expect(edges).toHaveLength(1);
        expect(edges[0]).toMatchObject({
            source: provider.id,
            target: agent.id,
            sourceHandle: 'top',
            targetHandle: 'bottom',
        });

        expect(name).toBe('Claude Code + Slack');
        // The builder gets a non-empty guiding message referencing the selected app.
        expect(builderPrompt).toContain('Slack');
        expect(builderPrompt.length).toBeGreaterThan(0);
        // The over-asking fix: bias toward a quick question or two, then focus
        // on credentials + wiring — no guessed goal, no step-by-step interrogation.
        expect(builderPrompt).toMatch(/a question or two/);
        expect(builderPrompt).toContain('getting the accounts connected');
        expect(builderPrompt).not.toContain('one step at a time');
        expect(builderPrompt).not.toContain('First ask me what I want');
    });

    it('wires multiple providers, each into the agent bottom handle', () => {
        const { name, workflowData } = buildAgentScaffold({
            harnessModel: 'codex',
            harnessLabel: 'Codex',
            message: 'Work across my tools.',
            integrations: [
                { type: 'automation-slack', label: 'Slack' },
                { type: 'automation-linear', label: 'Linear' },
            ],
        });
        const { nodes, edges } = workflowData;

        expect(nodes).toHaveLength(3); // 1 agent + 2 providers
        const agent = nodes.find((n) => n.type === 'agent')!;

        expect(edges).toHaveLength(2);
        for (const edge of edges) {
            expect(edge.target).toBe(agent.id);
            expect(edge.sourceHandle).toBe('top');
            expect(edge.targetHandle).toBe('bottom');
        }
        // Edge sources must match the provider node ids exactly.
        const providerIds = nodes
            .filter((n) => n.type !== 'agent')
            .map((n) => n.id)
            .sort();
        expect(edges.map((e) => e.source).sort()).toEqual(providerIds);

        expect(name).toBe('Codex + Slack and Linear');
    });

    it('leaves every provider node bare (no operation / allowlist)', () => {
        const { workflowData } = buildAgentScaffold({
            harnessModel: 'opencode',
            harnessLabel: 'OpenCode',
            message: 'go',
            integrations: [
                { type: 'automation-slack', label: 'Slack' },
                { type: 'automation-linear', label: 'Linear' },
            ],
        });
        for (const provider of workflowData.nodes.filter(
            (n) => n.type !== 'agent'
        )) {
            expect(provider.config.operation).toBeUndefined();
            expect(provider.config.agent_tool_operations).toBeUndefined();
        }
    });

    it('produces unique node ids and edge ids derived from them', () => {
        const { workflowData } = buildAgentScaffold({
            harnessModel: 'hermes',
            harnessLabel: 'Hermes',
            message: 'go',
            integrations: [
                { type: 'automation-slack', label: 'Slack' },
                { type: 'automation-linear', label: 'Linear' },
            ],
        });
        const ids = workflowData.nodes.map((n) => n.id);
        expect(new Set(ids).size).toBe(ids.length);
        // Edge ids use the backend's canonical add_edge format so a builder
        // round-trip reconciles instead of adding a duplicate overlapping edge.
        for (const edge of workflowData.edges) {
            expect(edge.id).toBe(`e_${edge.source}_${edge.target}`);
        }
    });

    it('wires triggers into the agent left handle, alongside tools at the bottom', () => {
        const { workflowData, builderPrompt } = buildAgentScaffold({
            harnessModel: 'claude-code',
            harnessLabel: 'Claude Code',
            message: 'go',
            triggers: [
                { type: 'trigger-webhook', label: 'Webhook' },
                {
                    type: 'automation-slack',
                    label: 'Slack',
                    operation: 'slack_on_message',
                },
            ],
            integrations: [{ type: 'automation-linear', label: 'Linear' }],
        });
        const { nodes, edges } = workflowData;

        // agent + 2 triggers + 1 provider
        expect(nodes).toHaveLength(4);
        const agent = nodes.find((n) => n.type === 'agent')!;

        // Built-in trigger types are triggers by type, so they stay operation-less.
        const webhook = nodes.find((n) => n.id === 'trigger-webhook-1')!;
        expect(webhook.type).toBe('trigger-webhook');
        expect(webhook.config.operation).toBeUndefined();
        // Integration triggers carry their default trigger op so they fire and
        // render the trigger bolt (a bare integration trigger does neither).
        const slackTrigger = nodes.find((n) => n.id === 'trigger-slack-2')!;
        expect(slackTrigger.type).toBe('automation-slack');
        expect(slackTrigger.config.operation).toBe('slack_on_message');

        // Trigger edges target the agent's LEFT handle; the tool edge targets BOTTOM.
        const triggerEdges = edges.filter((e) => e.targetHandle === 'left');
        expect(triggerEdges.map((e) => e.source).sort()).toEqual([
            'trigger-slack-2',
            'trigger-webhook-1',
        ]);
        triggerEdges.forEach((e) => expect(e.target).toBe(agent.id));
        const toolEdges = edges.filter((e) => e.targetHandle === 'bottom');
        expect(toolEdges).toHaveLength(1);
        expect(toolEdges[0].sourceHandle).toBe('top');

        // The guiding prompt references both the trigger(s) and the tool(s).
        expect(builderPrompt).toContain('Webhook');
        expect(builderPrompt).toContain('Linear');
    });
});

describe('wizard preset allowlists', () => {
    it('setup intent survives the JSON stash round-trip', () => {
        const intent = buildAgentScaffold({
            harnessModel: 'codex',
            harnessLabel: 'Codex',
            message: 'Help me',
            integrations: [{ type: 'automation-slack', label: 'Slack' }],
        });
        intent.setup = {
            runtime: 'cloud',
            presetIds: { 'automation-slack': 'messaging' },
        };
        // The stash is sessionStorage JSON — what matters is that the intent
        // (setup included) is JSON-stable across the auth round-trip.
        const revived = JSON.parse(JSON.stringify(intent)) as typeof intent;
        expect(revived.setup).toEqual(intent.setup);
        expect(revived.workflowData).toEqual(intent.workflowData);
    });
});
