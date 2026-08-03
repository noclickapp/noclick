import { describe, expect, it } from 'vitest';
import { CronTriggerNode } from '~/components/workflow/nodes/CronTriggerNode';
import { WebhookTriggerNode } from '~/components/workflow/nodes/WebhookTriggerNode';
import { InboundEmailTriggerNode } from '~/components/workflow/nodes/InboundEmailTriggerNode';
import { AlarmNode } from '~/components/workflow/nodes/AlarmNode';
import { LinearNode } from '~/components/workflow/nodes/LinearNode';
import { SlackNode } from '~/components/workflow/nodes/SlackNode';
import { GoogleSheetsNode } from '~/components/workflow/nodes/GoogleSheetsNode';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import {
    filterNodeServices,
    scoreNodeService,
    type NodeServiceTarget,
} from '~/utils/nodeServiceSearch';

// Real NodeDefinitions (imported individually — the palette rows are built from
// these, so the test pins the authored label/keywords too, not just the scorer).
const target = (node: NodeDefinition): NodeServiceTarget => ({
    nodeType: node.type,
    label: node.label,
    description: node.description,
    keywords: node.keywords,
});

const TRIGGERS = [
    CronTriggerNode,
    WebhookTriggerNode,
    InboundEmailTriggerNode,
    SlackNode,
    LinearNode,
].map(target);

const TOOLS = [AlarmNode, SlackNode, LinearNode, GoogleSheetsNode].map(target);

const search = (
    items: NodeServiceTarget[],
    q: string,
    role: 'trigger' | 'tool' = 'trigger'
) => filterNodeServices(items, q, role).map((s) => s.nodeType);

describe('wiring palette service search', () => {
    it('finds the schedule trigger by the word users actually type', () => {
        // The regression: rows matched only the type-derived label ("Trigger
        // Cron"), so the Schedule trigger was unreachable by any natural query.
        expect(search(TRIGGERS, 'schedule')[0]).toBe('trigger-cron');
        expect(search(TRIGGERS, 'every day')[0]).toBe('trigger-cron');
        expect(search(TRIGGERS, 'recurring')[0]).toBe('trigger-cron');
        expect(search(TRIGGERS, 'timer')[0]).toBe('trigger-cron');
    });

    it('still finds it by its type and description wording', () => {
        expect(search(TRIGGERS, 'cron')[0]).toBe('trigger-cron');
        expect(search(TRIGGERS, 'trigger cron')[0]).toBe('trigger-cron');
    });

    it('finds the other dedicated triggers by their aliases', () => {
        expect(search(TRIGGERS, 'http endpoint')[0]).toBe('trigger-webhook');
        expect(search(TRIGGERS, 'incoming mail')[0]).toBe('trigger-email');
    });

    it('ranks a service matched by name above one matched by its actions', () => {
        // "message" is in Slack's own trigger names and in other services' too;
        // a node whose identity matches must never be buried by them.
        const bySelf = scoreNodeService(target(SlackNode), 'trigger', 'slack');
        const byAction = scoreNodeService(
            target(SlackNode),
            'trigger',
            'reaction added'
        );
        expect(bySelf).not.toBeNull();
        expect(byAction).not.toBeNull();
        expect(bySelf!).toBeGreaterThan(byAction!);
    });

    it('surfaces a service by an action it exposes', () => {
        // Neither word appears in Linear's label, type or description.
        expect(search(TOOLS, 'create issue', 'tool')).toContain(
            'automation-linear'
        );
        expect(search(TOOLS, 'append row', 'tool')).toContain(
            'automation-google-sheets'
        );
    });

    it('handles a query that mixes the service name with an action', () => {
        expect(search(TOOLS, 'linear issue', 'tool')).toEqual([
            'automation-linear',
        ]);
    });

    it('scopes actions to the role — tool actions never match in the trigger list', () => {
        // "Send Message" is a Slack TOOL action, not one of its triggers.
        expect(search(TRIGGERS, 'send message')).not.toContain(
            'automation-slack'
        );
        expect(search(TOOLS, 'send message', 'tool')).toContain(
            'automation-slack'
        );
    });

    it('drops services that match no token at all', () => {
        expect(search(TOOLS, 'zzzz nonexistent', 'tool')).toEqual([]);
    });

    it('returns the list untouched for an empty query', () => {
        expect(search(TRIGGERS, '   ')).toEqual(
            TRIGGERS.map((t) => t.nodeType)
        );
    });
});
