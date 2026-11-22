// Which connections the canvas accepts: each rule of connectionRules.ts on a workflow holding one step of each kind.
import type { Connection, Edge, Node } from '@xyflow/react';
import { describe, expect, it } from 'vitest';
import { connectionAllowed, feedsAgentTools, normalizeConnection, type ConnectionRoles } from './connectionRules';

const TOOLS = new Set(['automation-slack', 'automation-gmail', 'automation-serverless-function']);
const roles: ConnectionRoles = {
    trigger: (type, operation) => !!type && (type.startsWith('trigger-') || (type === 'automation-slack' && operation === 'on_channel_message')),
    tool: (type) => !!type && TOOLS.has(type),
    connectionless: (type) => type === 'interface-html-react',
};

const step = (id: string, type: string, data: Record<string, unknown> = {}): Node => ({ id, type, position: { x: 0, y: 0 }, data });
const NODES: Node[] = [
    step('hook', 'trigger-webhook'),
    step('agent', 'agent'),
    step('gmail', 'automation-gmail'),
    step('slack', 'automation-slack'),
    step('listener', 'automation-slack', { operation: 'on_channel_message' }),
    step('log', 'log'),
    step('tool', 'tool'),
    step('mcp', 'mcp-server'),
    step('theirs', 'mcp-server', { config: { server_url: 'https://mcp.example.test' } }),
    step('page', 'interface-html-react'),
];
const EDGES: Edge[] = [
    { id: 'e1', source: 'hook', target: 'agent' },
    { id: 'e2', source: 'gmail', sourceHandle: 'top', target: 'agent', targetHandle: 'bottom' },
];

const allowed = (source: string, sourceHandle: string | null, target: string, targetHandle: string | null, edges = EDGES) =>
    connectionAllowed({ source, sourceHandle, target, targetHandle } as Connection, NODES, edges, roles);

describe('the connections a canvas accepts', () => {
    it('takes a step after another, and never the same connection twice', () => {
        expect(allowed('hook', null, 'log', null)).toBe(true);
        expect(allowed('hook', null, 'agent', null)).toBe(false);
        expect(allowed('ghost', null, 'log', null)).toBe(false);
    });

    it('flows nothing into a trigger, nor to or from a step that talks through the SDK', () => {
        expect(allowed('log', null, 'hook', null)).toBe(false);
        expect(allowed('log', null, 'listener', null)).toBe(false);
        expect(allowed('page', null, 'log', null)).toBe(false);
        expect(allowed('log', null, 'page', null)).toBe(false);
    });

    it('wires a tool into an agent from its top, and an integration into an MCP server it hosts', () => {
        expect(allowed('slack', 'top', 'agent', 'bottom')).toBe(true);
        expect(allowed('tool', 'top', 'agent', 'bottom')).toBe(true);
        expect(allowed('slack', 'top', 'mcp', 'bottom')).toBe(true);
        // Not into a server pointed at one of its own, not a tool step (no operations to host), nowhere else from the top.
        expect(allowed('slack', 'top', 'theirs', 'bottom')).toBe(false);
        expect(allowed('tool', 'top', 'mcp', 'bottom')).toBe(false);
        expect(allowed('slack', 'top', 'log', null)).toBe(false);
        // Nothing else into an agent's bottom, or into an MCP server.
        expect(allowed('log', null, 'agent', 'bottom')).toBe(false);
        expect(allowed('log', 'top', 'agent', 'bottom')).toBe(false);
        expect(allowed('log', null, 'mcp', null)).toBe(false);
    });

    it('keeps a step an agent’s tools or a step in the flow, never both, and never a tool while it starts runs', () => {
        expect(allowed('listener', 'top', 'agent', 'bottom')).toBe(false);
        expect(allowed('gmail', null, 'log', null)).toBe(false);
        const flowing = [...EDGES, { id: 'e3', source: 'slack', target: 'log' }];
        expect(allowed('slack', 'top', 'agent', 'bottom', flowing)).toBe(false);
        expect(allowed('slack', null, 'log', null)).toBe(true);
    });

    it('reads a connection dragged from a step’s stub as from the step’s own handle', () => {
        expect(normalizeConnection({ source: 'a', sourceHandle: 'default__hint', target: 'b', targetHandle: null })).toEqual({ source: 'a', sourceHandle: null, target: 'b', targetHandle: null });
        expect(normalizeConnection({ source: 'a', sourceHandle: 'true__hint', target: 'b', targetHandle: null }).sourceHandle).toBe('true');
        expect(allowed('log', 'default__hint', 'slack', null)).toBe(true);
        expect(allowed('hook', 'default__hint', 'agent', null)).toBe(false);
    });

    it('knows NoClick’s own tool steps beside the integrations that offer their operations', () => {
        expect(['tool', 'mcp-server', 'alarm', 'filesystem', 'noclick', 'automation-slack'].map((t) => feedsAgentTools(t, roles))).toEqual([true, true, true, true, true, true]);
        expect(feedsAgentTools('log', roles)).toBe(false);
        expect(feedsAgentTools(undefined, roles)).toBe(false);
    });
});
