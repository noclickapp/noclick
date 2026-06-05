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
