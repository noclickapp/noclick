import type { Edge, Node } from '@xyflow/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ReadinessCard, adaptBlobGraph, deriveUnmetConnections, type StepReadiness } from './readiness';

const node = (id: string, type: string, data: Record<string, unknown> = {}): Node => ({ id, type, position: { x: 0, y: 0 }, data }) as Node;
const edge = (source: string, target: string, targetHandle?: string): Edge => ({ id: `${source}-${target}`, source, target, targetHandle }) as Edge;

/** Steps whose type is in `unconnected` still need an account; `*-in` types (and trigger-*) wake the workflow. */
const steps = (unconnected: string[]): StepReadiness => ({
    needsConnection: (n) => unconnected.includes(n.type!),
    isTriggerSource: (type, operation) => type.startsWith('trigger-') || operation === 'receive',
    nameOf: (type) => ({ chat: 'Chat', mail: 'Mail' })[type] ?? type,
});

describe('deriveUnmetConnections', () => {
    it('says nothing will wake the agent when its one trigger has no account, and merges the tool of the same app', () => {
        const nodes = [node('agent', 'agent'), node('in', 'chat', { operation: 'receive' }), node('out', 'chat')];
        const edges = [edge('in', 'agent'), edge('out', 'agent', 'bottom')];
        expect(deriveUnmetConnections(nodes, edges, steps(['chat']))).toEqual([
            {
                nodeId: 'in',
                nodeType: 'chat',
                label: 'Chat',
                role: 'trigger',
                nodeIds: ['in', 'out'],
                soleWakePath: true,
                headline: 'Without Chat, nothing will wake your agent.',
                body: 'It will never run on its own — and even when it does run, every Chat reply will fail. One connection powers both.',
            },
        ]);
    });

    it("scopes a trigger's claim to its own events when another trigger works", () => {
        const nodes = [node('agent', 'agent'), node('hook', 'trigger-webhook'), node('in', 'chat', { operation: 'receive' })];
        const [item] = deriveUnmetConnections(nodes, [edge('hook', 'agent'), edge('in', 'agent')], steps(['chat']));
        expect(item.soleWakePath).toBe(false);
        expect(item.headline).toBe('Chat events will never reach your agent.');
    });

    it("puts triggers first, names a tool by its consequence and a step by its label, and skips the agent's own model", () => {
        const nodes = [
            node('agent', 'agent'),
            node('send', 'mail', { label: 'Send the reply' }),
            node('tool', 'chat'),
            node('in', 'trigger-mail'),
        ];
        const edges = [edge('agent', 'send'), edge('tool', 'agent', 'bottom'), edge('in', 'agent')];
        const out = deriveUnmetConnections(nodes, edges, steps(['agent', 'mail', 'chat', 'trigger-mail']));
        expect(out.map((u) => [u.nodeId, u.role, u.headline])).toEqual([
            ['in', 'trigger', 'Without trigger-mail, nothing will wake your agent.'],
            ['send', 'node', 'Without Send the reply, this step will fail.'],
            ['tool', 'tool', "Without Chat, your agent can't act."],
        ]);
    });
});

describe('adaptBlobGraph', () => {
    it("reads a saved workflow's steps as the canvas holds them", () => {
        expect(adaptBlobGraph({ nodes: [{ id: 'a', type: 'mail', config: { label: 'A', operation: 'send', credentialIds: { m: 'c' } } }, { id: 'b', type: 'chat' }] })).toEqual({
            nodes: [
                { id: 'a', type: 'mail', position: { x: 0, y: 0 }, data: { label: 'A', operation: 'send', config: { label: 'A', operation: 'send', credentialIds: { m: 'c' } }, credentialIds: { m: 'c' } } },
                { id: 'b', type: 'chat', position: { x: 0, y: 0 }, data: { label: undefined, operation: undefined, config: {}, credentialIds: {} } },
            ],
            edges: [],
        });
    });
});

describe('ReadinessCard', () => {
    const item = (id: string, role: 'trigger' | 'tool' | 'node', soleWakePath?: boolean) => ({
        nodeId: id,
        nodeType: id,
        label: id.toUpperCase(),
        role,
        headline: `${id} headline`,
        body: `${id} body`,
        nodeIds: [id],
        soleWakePath,
    });

    it('draws nothing when everything is connected', () => {
        expect(renderToStaticMarkup(<ReadinessCard unmet={[]} onConnect={() => undefined} />)).toBe('');
    });

    it('draws a card per connection, up to two', () => {
        const html = renderToStaticMarkup(<ReadinessCard unmet={[item('a', 'tool'), item('b', 'node')]} onConnect={() => undefined} />);
        expect(html).toContain('a headline');
        expect(html).toContain('Connect B');
    });

    it('collapses three or more into one summary', () => {
        const html = renderToStaticMarkup(<ReadinessCard unmet={[item('a', 'trigger', true), item('b', 'tool'), item('c', 'node')]} onConnect={() => undefined} />);
        expect(html).toContain('Not connected yet: A, B, C.');
        expect(html).toContain('Nothing will wake your agent, and unconnected steps fail on real runs.');
        expect(html).not.toContain('a headline');
    });
});
