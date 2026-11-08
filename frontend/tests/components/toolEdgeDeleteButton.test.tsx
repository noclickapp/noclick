// @vitest-environment happy-dom
// A tool link's "N tools" label stays put on hover, and the delete button appears beside it as its own target. The
// button used to take the label's place, so a click aimed at the label deleted the link.
import { useLayoutEffect } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Position, ReactFlowProvider, useEdges, useStoreApi, type Edge, type EdgeProps } from '@xyflow/react';
import { afterEach, describe, expect, it } from 'vitest';
import AnimatedWorkflowEdge from '~/components/workflow/edges/AnimatedWorkflowEdge';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

afterEach(cleanup);

const at = { x: 0, y: 0 };
const LINK: Edge = { id: 'tasks->mcp', source: 'tasks', target: 'mcp', sourceHandle: 'top', targetHandle: 'bottom' };
const OPS = ['create_new_task', 'list_tasks_in_list', 'update_task_in_list'];

/** Stands in for <ReactFlow>'s pane: EdgeLabelRenderer portals into the canvas's label layer. */
function LabelLayer() {
    const store = useStoreApi();
    useLayoutEffect(() => {
        const pane = document.createElement('div');
        pane.innerHTML = '<div class="react-flow__edgelabel-renderer"></div>';
        document.body.appendChild(pane);
        store.setState({ domNode: pane });
        return () => pane.remove();
    }, [store]);
    return null;
}

function Links() {
    return <output data-testid="links">{useEdges().map((e) => e.id).join(',')}</output>;
}

function renderLink() {
    const props = {
        id: LINK.id,
        source: LINK.source,
        target: LINK.target,
        sourceX: 0,
        sourceY: 200,
        targetX: 0,
        targetY: 0,
        sourcePosition: Position.Top,
        targetPosition: Position.Bottom,
        sourceHandleId: 'top',
        targetHandleId: 'bottom',
        data: {},
    } as unknown as EdgeProps<Edge<{ isAnimating?: boolean }>>;
    render(
        <ReactFlowProvider
            defaultNodes={[
                createWorkflowNode('mcp', 'mcp-server', at, {}),
                createWorkflowNode('tasks', 'automation-google-tasks', { x: 0, y: 200 }, { agent_tool_operations: OPS }),
            ]}
            defaultEdges={[LINK]}
        >
            <LabelLayer />
            <svg>
                <AnimatedWorkflowEdge {...props} />
            </svg>
            <Links />
        </ReactFlowProvider>
    );
}

const links = () => screen.getByTestId('links').textContent;

describe('tool link delete button', () => {
    it('appears beside the label on hover, never in its place', async () => {
        renderLink();
        const label = await screen.findByTestId('tool-edge-label');
        expect(label.textContent).toBe('3 tools');
        expect(screen.queryByTitle('Delete edge')).toBeNull();

        fireEvent.mouseEnter(label);
        const remove = screen.getByTitle('Delete edge');
        expect(getComputedStyle(label).visibility).not.toBe('hidden');
        expect(screen.getByTestId('tool-edge-label').textContent).toBe('3 tools');
        expect(label.contains(remove) || remove.contains(label)).toBe(false);

        // The label keeps no click action; only the button deletes.
        fireEvent.click(label);
        expect(links()).toBe(LINK.id);
        fireEvent.click(remove);
        await waitFor(() => expect(links()).toBe(''));
    });
});
