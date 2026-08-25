// @vitest-environment jsdom
//
// Tests for deriveUnmetConnections' same-type merge: two WhatsApp nodes (a
// trigger + a reply-tools provider) need ONE service account, so readiness
// must surface ONE card — headlined by the trigger consequence, covering both
// node ids — instead of asking twice (the 2026-08-10 duplicate-ask report).

import { beforeAll, describe, expect, test, vi } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
// The registry pulls every canvas node component; the merge only needs the
// display-name seam.
vi.mock('~/components/workflow/nodes/nodeRegistry', () => ({
    getNodeDisplayName: (type: string) =>
        ({
            'automation-whatsapp': 'WhatsApp',
            'automation-telegram': 'Telegram',
            'automation-discord': 'Discord',
        })[type] ?? type,
}));

let deriveUnmetConnections: typeof import('~/components/workflow/setup/readiness').deriveUnmetConnections;

beforeAll(async () => {
    ({ deriveUnmetConnections } = await import(
        '~/components/workflow/setup/readiness'
    ));
}, 30000);

function makeNode(id: string, type: string, data: Record<string, unknown> = {}): Node {
    return {
        id,
        type,
        position: { x: 0, y: 0 },
        data: { config: {}, credentialIds: {}, ...data },
    } as Node;
}

function makeEdge(source: string, target: string, targetHandle?: string): Edge {
    return { id: `${source}-${target}`, source, target, targetHandle } as Edge;
}

describe('deriveUnmetConnections same-type merge', () => {
    test('trigger + tool of one service become ONE card covering both nodes', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
            }),
            makeNode('wa-out', 'automation-whatsapp', {
                config: { agent_tool_operations: ['send_message'] },
            }),
        ];
        const edges = [
            makeEdge('wa-in', 'agent1'),
            makeEdge('wa-out', 'agent1', 'bottom'),
        ];
        const items = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-whatsapp'
        );
        expect(items).toHaveLength(1);
        const [item] = items;
        // Trigger member is the representative — Connect jumps to the step
        // whose consequence is strongest (a workflow that never wakes).
        expect(item.nodeId).toBe('wa-in');
        expect(item.role).toBe('trigger');
        expect(new Set(item.nodeIds)).toEqual(new Set(['wa-in', 'wa-out']));
        expect(item.label).toBe('WhatsApp');
        expect(item.headline).toContain('nothing will wake your agent');
        expect(item.body).toContain('One connection powers both');
    });

    test('a lone unmet node keeps its per-node card untouched', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
            }),
        ];
        const edges = [makeEdge('wa-in', 'agent1')];
        const items = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-whatsapp'
        );
        expect(items).toHaveLength(1);
        expect(items[0].nodeIds).toEqual(['wa-in']);
        expect(items[0].role).toBe('trigger');
    });

    test('a dataflow input into an agent is NOT a trigger — no wake claim', () => {
        // Four dataflow inputs each claimed "nothing will wake your agent"
        // (2026-08-10): the role must come from the real trigger predicate
        // (x-is-trigger operation / trigger- type), not from edge shape.
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('dc1', 'automation-discord'),
        ];
        const edges = [makeEdge('dc1', 'agent1')];
        const items = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-discord'
        );
        expect(items).toHaveLength(1);
        expect(items[0].role).toBe('node');
        expect(items[0].headline).toContain('this step will fail');
        expect(items[0].headline).not.toContain('wake');
    });

    test('with several triggers wired, no single one claims "nothing will wake"', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
            }),
            makeNode('tg-in', 'automation-telegram', {
                operation: 'receive_webhook_messages',
            }),
        ];
        const edges = [makeEdge('wa-in', 'agent1'), makeEdge('tg-in', 'agent1')];
        const items = deriveUnmetConnections(nodes, edges).filter((u) =>
            ['automation-whatsapp', 'automation-telegram'].includes(u.nodeType)
        );
        expect(items).toHaveLength(2);
        for (const item of items) {
            expect(item.role).toBe('trigger');
            expect(item.soleWakePath).toBeFalsy();
            expect(item.headline).toContain('events will never reach your agent');
            expect(item.headline).not.toContain('nothing will wake');
        }
    });

    test('a working credential-less trigger demotes the wake claim to the channel', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('hook', 'trigger-webhook'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
            }),
        ];
        const edges = [makeEdge('hook', 'agent1'), makeEdge('wa-in', 'agent1')];
        const items = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-whatsapp'
        );
        expect(items).toHaveLength(1);
        expect(items[0].soleWakePath).toBeFalsy();
        expect(items[0].headline).toBe(
            'WhatsApp events will never reach your agent.'
        );
    });

    test('the sole wake path keeps the strong claim, flagged for summaries', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
            }),
        ];
        const edges = [makeEdge('wa-in', 'agent1')];
        const [item] = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-whatsapp'
        );
        expect(item.soleWakePath).toBe(true);
        expect(item.headline).toContain('nothing will wake your agent');
    });

    test('a connected twin does not join the merge', () => {
        const nodes = [
            makeNode('agent1', 'agent'),
            makeNode('wa-in', 'automation-whatsapp', {
                operation: 'receive_message',
                credentialIds: { whatsapp_qr: 'cred-1' },
            }),
            makeNode('wa-out', 'automation-whatsapp', {
                config: { agent_tool_operations: ['send_message'] },
            }),
        ];
        const edges = [
            makeEdge('wa-in', 'agent1'),
            makeEdge('wa-out', 'agent1', 'bottom'),
        ];
        const items = deriveUnmetConnections(nodes, edges).filter(
            (u) => u.nodeType === 'automation-whatsapp'
        );
        expect(items).toHaveLength(1);
        expect(items[0].nodeIds).toEqual(['wa-out']);
        expect(items[0].role).toBe('tool');
    });
});
