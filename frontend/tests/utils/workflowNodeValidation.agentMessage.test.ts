// @vitest-environment jsdom
//
// An agent's Message is required unless a trigger feeds the agent: the
// delivered event is then the turn. The schema can't express this (the field
// defaults to empty so a trigger-wired agent parses — a length rule fired
// before the event could be composed and dropped real inboxes' mail), so the
// canvas judges it from the graph, mirroring the backend's
// workflow_ops.agent_message_error.

import { beforeAll, describe, expect, test } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

let validateNode: typeof import('~/utils/workflowNodeValidation').validateNode;
let buildNodeValidationContext: typeof import('~/utils/workflowNodeValidation').buildNodeValidationContext;
let computeWiredProviderIdsKey: typeof import('~/utils/workflowNodeValidation').computeWiredProviderIdsKey;
let contextFromWiringKey: typeof import('~/utils/workflowNodeValidation').contextFromWiringKey;

beforeAll(async () => {
    ({ validateNode, buildNodeValidationContext, computeWiredProviderIdsKey, contextFromWiringKey } =
        await import('~/utils/workflowNodeValidation'));
}, 30000);

function node(id: string, type: string, data: Record<string, unknown>): Node {
    return { id, type, position: { x: 0, y: 0 }, data } as Node;
}

// openrouter/* runs on the platform key — no credential ask muddies the verdict.
const agent = (message: string) =>
    node('agent1', 'agent', { config: { model: 'openrouter/openai/gpt-4o-mini', message } });
const cron = node('cron1', 'trigger-cron', { config: { schedules: [] } });
const slackTrigger = node('slack1', 'automation-slack', {
    operation: 'on_channel_message', credentialIds: { slack: 'c1' }, config: { channel: 'C1' },
});
const slackProvider = node('slack2', 'automation-slack', {
    credentialIds: { slack: 'c1' }, config: { agent_tool_operations: ['send_message_to_channel'] },
});
const edge = (source: string, target: string, targetHandle?: string): Edge =>
    ({ id: `${source}-${target}`, source, target, targetHandle } as Edge);

const messageIssue = (n: Node, ctx?: ReturnType<typeof contextFromWiringKey>) =>
    validateNode(n, ctx).issues.find((i) => i.fieldKey === 'message');

describe('an agent with an empty Message', () => {
    test('is incomplete on its own — nothing would ever run it', () => {
        const issue = messageIssue(agent(''));
        expect(issue).toEqual({ type: 'missing_required_field', message: 'Message is required', fieldKey: 'message' });
    });

    test('is complete once a trigger feeds it (a dedicated trigger node)', () => {
        const ctx = buildNodeValidationContext([agent(''), cron], [edge('cron1', 'agent1')]);
        expect(messageIssue(agent(''), ctx)).toBeUndefined();
        expect(validateNode(agent(''), ctx).isComplete).toBe(true);
    });

    test('is complete once a trigger feeds it (an integration node on a trigger operation)', () => {
        const ctx = buildNodeValidationContext([agent(''), slackTrigger], [edge('slack1', 'agent1')]);
        expect(messageIssue(agent(''), ctx)).toBeUndefined();
    });

    test('a tool provider on the bottom handle is not a trigger', () => {
        const ctx = buildNodeValidationContext([agent(''), slackProvider], [edge('slack2', 'agent1', 'bottom')]);
        expect(messageIssue(agent(''), ctx)).toBeDefined();
        expect(ctx.wiredProviderIds.has('slack2')).toBe(true);
    });

    test('a filled Message needs no trigger', () => {
        expect(messageIssue(agent('Reply like a helpful agent.'))).toBeUndefined();
    });
});

describe('the wiring key', () => {
    test('carries both halves content-stably and round-trips through the context', () => {
        const nodes = [agent(''), cron, slackProvider];
        const edges = [edge('cron1', 'agent1'), edge('slack2', 'agent1', 'bottom')];
        const key = computeWiredProviderIdsKey(nodes, edges);
        expect(key).toBe('slack2#agent1');
        expect(computeWiredProviderIdsKey(nodes, [...edges].reverse())).toBe(key);
        const ctx = contextFromWiringKey(key);
        expect([...ctx.wiredProviderIds]).toEqual(['slack2']);
        expect([...ctx.triggerFedAgentIds]).toEqual(['agent1']);
        expect(contextFromWiringKey('')).toEqual({ wiredProviderIds: new Set(), triggerFedAgentIds: new Set() });
    });
});
