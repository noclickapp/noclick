import { describe, expect, it } from 'vitest';
import type { Edge, Node } from '@xyflow/react';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import {
    prepareNodeExecution,
    serializeGraphForExecution,
} from '~/utils/workflowNodeExecution';

describe('workflowNodeExecution replay graph serialization', () => {
    it('keeps interface nodes in replay graph when single-node execution uses a subset graph', () => {
        const slack = createWorkflowNode('slack-1', 'automation-slack', { x: 100, y: 100 }, {
            label: 'Slack Notification',
            message: 'Customer feedback received',
        });
        const app = createWorkflowNode('app-1', 'interface-html-react', { x: 100, y: 420 }, {
            label: 'Customer Feedback Portal',
            operation: 'render_jsx_react_interface',
            fullscreen: 'true',
            jsx_source: "import { nodes } from '@noclick/sdk';\nawait nodes.getOutput('slack-1');",
        });
        app.style = { width: 1150, height: 800 };
        const nodes: Node[] = [slack, app];
        const edges: Edge[] = [];

        const execution = prepareNodeExecution('slack-1', nodes, edges);
        expect(execution.success).toBe(true);
        if (!execution.success) throw new Error(execution.error);

        const replay = serializeGraphForExecution(nodes, edges);

        expect(execution.nodes.map((n) => n.id)).toEqual(['slack-1']);
        expect(replay.nodes.map((n) => n.id)).toEqual(['slack-1', 'app-1']);
        expect(replay.nodes.find((n) => n.id === 'app-1')?.config).toMatchObject({
            operation: 'render_jsx_react_interface',
            jsx_source: expect.stringContaining("nodes.getOutput('slack-1')"),
        });
        expect(replay.nodes.find((n) => n.id === 'app-1')).toMatchObject({
            width: 1150,
            height: 800,
        });
    });
});

describe('single-node run of a tool provider', () => {
    // 2026-09-07: "Run" on a Facebook node wired into an MCP Server's
    // bottom handle sent just the node — cut out of its wiring it was parsed
    // as a plain node and failed with "'operation' field is required".
    const provider = () =>
        createWorkflowNode('slack-1', 'automation-slack', { x: 0, y: 0 }, {
            label: 'Slack',
            agent_tool_operations: ['send_message'],
        });
    const bottomEdge = (target: string): Edge => ({
        id: `slack-1-${target}`,
        source: 'slack-1',
        target,
        sourceHandle: 'top',
        targetHandle: 'bottom',
    });

    it('refuses a provider wired into an agent and names the caller', () => {
        const agent = createWorkflowNode('agent-1', 'agent', { x: 0, y: 200 }, { message: 'hi' });
        const result = prepareNodeExecution('slack-1', [provider(), agent], [bottomEdge('agent-1')]);
        expect(result).toEqual({
            success: false,
            error: 'This node provides tools. Its actions run when the agent calls them.',
        });
    });

    it('refuses a provider hosted by an MCP Server node', () => {
        const mcp = createWorkflowNode('mcp-1', 'mcp-server', { x: 0, y: 200 }, {});
        const result = prepareNodeExecution('slack-1', [provider(), mcp], [bottomEdge('mcp-1')]);
        expect(result.success).toBe(false);
        if (result.success) throw new Error('expected refusal');
        expect(result.error).toContain('your MCP client');
    });

    it('still runs the same node when it is wired as plain dataflow', () => {
        const agent = createWorkflowNode('agent-1', 'agent', { x: 0, y: 200 }, { message: 'hi' });
        const dataflow: Edge = { id: 'e', source: 'slack-1', target: 'agent-1' };
        const result = prepareNodeExecution('slack-1', [provider(), agent], [dataflow]);
        expect(result.success).toBe(true);
    });
});
