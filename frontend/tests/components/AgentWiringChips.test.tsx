// @vitest-environment happy-dom
// The trigger and tool chips under an agent's Message field. × unhooks the node from the agent and, when nothing else
// connects to it, removes the node too: left on the canvas, it sat unseen under the next one added in its place.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReactFlowProvider, useEdges, useNodes, type Edge, type Node } from '@xyflow/react';
import { afterEach, describe, expect, it } from 'vitest';
import { AgentWiringChips } from '~/components/workflow/AgentWiringChips';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { getAgentToolProviders, getAgentTriggerSources } from '~/utils/nodeSchemas';

afterEach(cleanup);

const at = { x: 0, y: 0 };
const agent = (id: string) => createWorkflowNode(id, 'agent', at, {});
const whatsapp = (id: string) => createWorkflowNode(id, 'automation-whatsapp', at, {}, { operation: 'receive_message' });
const tasks = (id: string) => createWorkflowNode(id, 'automation-google-tasks', at, { agent_tool_operations: ['list_tasks_in_list'] });
const triggerEdge = (source: string, target: string): Edge => ({ id: `${source}->${target}`, source, target, targetHandle: 'left' });
const toolEdge = (source: string, target: string): Edge => ({ id: `${source}->${target}`, source, target, sourceHandle: 'top', targetHandle: 'bottom' });

/** The agent's chips, derived from the live graph the way the config panel derives them. */
function Panel() {
    const nodes = useNodes();
    const edges = useEdges();
    return (
        <>
            <AgentWiringChips triggers={getAgentTriggerSources('agent', nodes, edges)} tools={getAgentToolProviders('agent', nodes, edges, () => false)} />
            <output data-testid="graph">{JSON.stringify({ nodes: nodes.map((n) => n.id), edges: edges.map((e) => e.id) })}</output>
        </>
    );
}

const renderPanel = (nodes: Node[], edges: Edge[]) =>
    render(
        <ReactFlowProvider defaultNodes={nodes} defaultEdges={edges}>
            <Panel />
        </ReactFlowProvider>
    );
const graph = () => JSON.parse(screen.getByTestId('graph').textContent ?? '') as { nodes: string[]; edges: string[] };

describe('agent wiring chip ×', () => {
    it('removes a trigger nothing else connects to, along with its link', async () => {
        renderPanel([agent('agent'), whatsapp('wa')], [triggerEdge('wa', 'agent')]);
        fireEvent.click(screen.getByTitle('Disconnect this trigger from the agent'));
        await waitFor(() => expect(graph()).toEqual({ nodes: ['agent'], edges: [] }));
    });

    it('keeps a trigger that still has another link, unhooking it from this agent only', async () => {
        renderPanel([agent('agent'), agent('other'), whatsapp('wa')], [triggerEdge('wa', 'agent'), triggerEdge('wa', 'other')]);
        fireEvent.click(screen.getByTitle('Disconnect this trigger from the agent'));
        await waitFor(() => expect(graph().edges).toEqual(['wa->other']));
        expect(graph().nodes).toEqual(['agent', 'other', 'wa']);
    });

    it('removes a tool provider nothing else connects to, along with its link', async () => {
        renderPanel([agent('agent'), tasks('tasks')], [toolEdge('tasks', 'agent')]);
        fireEvent.click(screen.getByTitle('Disconnect this tool from the agent'));
        await waitFor(() => expect(graph()).toEqual({ nodes: ['agent'], edges: [] }));
    });
});
