// Unit tests for getTriggerlessAgents — the decision that drives the post-build
// "chat with your agent" walkthrough and the show_in_interface default. An agent
// with no trigger wired into its input handle is chat-driven; one fed by a
// trigger runs on that event. Added alongside the FlowCanvas post-build feature.

import { describe, it, expect } from 'vitest';
import { getTriggerlessAgents } from '~/utils/nodeSchemas';

type N = { id: string; type?: string; data?: Record<string, any> };
type E = { id: string; source: string; target: string; targetHandle?: string | null };

const agent = (id: string): N => ({ id, type: 'agent', data: {} });
const webhookTrigger = (id: string): N => ({ id, type: 'trigger-webhook', data: {} });
const edge = (source: string, target: string, targetHandle?: string): E => ({
    id: `e_${source}_${target}`,
    source,
    target,
    targetHandle,
});

describe('getTriggerlessAgents', () => {
    it('returns an agent with no incoming edges', () => {
        const nodes = [agent('a1')];
        const result = getTriggerlessAgents(nodes, []);
        expect(result.map((n) => n.id)).toEqual(['a1']);
    });

    it('excludes an agent fed by a trigger on its input handle', () => {
        const nodes = [agent('a1'), webhookTrigger('t1')];
        const edges = [edge('t1', 'a1', 'left')];
        expect(getTriggerlessAgents(nodes, edges)).toEqual([]);
    });

    it('still counts an agent as triggerless when the trigger feeds its bottom (tools) handle', () => {
        // Bottom-handle edges are tool/alarm providers, not triggers — the agent
        // has no firing trigger, so it stays chat-driven.
        const nodes = [agent('a1'), webhookTrigger('t1')];
        const edges = [edge('t1', 'a1', 'bottom')];
        expect(getTriggerlessAgents(nodes, edges).map((n) => n.id)).toEqual(['a1']);
    });

    it('ignores non-agent nodes', () => {
        const nodes: N[] = [{ id: 'n1', type: 'automation-slack', data: {} }, webhookTrigger('t1')];
        expect(getTriggerlessAgents(nodes, [])).toEqual([]);
    });

    it('partitions a mixed graph — only the un-triggered agent is returned', () => {
        const nodes = [agent('chat'), agent('evented'), webhookTrigger('t1')];
        const edges = [edge('t1', 'evented', 'left')];
        expect(getTriggerlessAgents(nodes, edges).map((n) => n.id)).toEqual(['chat']);
    });
});
