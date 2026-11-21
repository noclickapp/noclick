// @vitest-environment happy-dom
// The canvas's drawing where no host fills its slots: what a step is by its type, read from the platform API once a
// session; a step with no drawing of its own drawn plain, with a handle for each connection it holds; any type drawn as
// it's met; a sticky note as a note, its text as a README is drawn; and a build from elsewhere opening a step's card.
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider, type Edge, type Node, type NodeProps } from '@xyflow/react';
import { NoClick } from 'noclick';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { standing } from '@/slots';
import { createWorkflowNode } from './applyNodeUpdate';
import { useV1StepRoles } from './drawingStandards';
import { graphFetch } from './graph/fixtures';
import { buildLazyNodeTypes } from './nodes/lazyNodeTypes';
import { STEP_DRAWING, STEP_EDITING } from './slots';

afterEach(cleanup);

function clientAsking(asked: string[]): NoClick {
    return new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: graphFetch({ actsAs: 'key', observe: (method, path) => asked.push(`${method} ${path}`) }),
    });
}

const provided = (client: NoClick) => ({ children }: { children: ReactNode }) => <ClientProvider client={client}>{children}</ClientProvider>;

describe('what a step is, by its type', () => {
    it('is read from the API the first time it’s asked about, once, and drawn again when it lands', async () => {
        const asked: string[] = [];
        const { result } = renderHook(() => useV1StepRoles(), { wrapper: provided(clientAsking(asked)) });
        // Not read yet: neither a trigger nor a tool.
        expect(result.current.trigger('trigger-webhook', null)).toBe(false);
        expect(result.current.tool('automation-slack')).toBe(false);
        expect(result.current.canonical('trigger-form-input')).toBe('trigger-form-input');
        expect(result.current.tool('nothing-like-it')).toBe(false);
        await waitFor(() => expect(result.current.trigger('trigger-webhook', null)).toBe(true));
        await waitFor(() => expect(result.current.canonical('trigger-form-input')).toBe('interface-form'));
        const roles = result.current;
        expect(roles.trigger('automation-slack', 'on_channel_message')).toBe(true);
        expect(roles.trigger('automation-slack', 'send_message')).toBe(false);
        expect(roles.trigger('automation-slack', null)).toBe(false);
        expect(roles.tool('automation-slack')).toBe(true);
        expect(roles.tool('trigger-webhook')).toBe(false);
        expect(roles.trigger(undefined, null)).toBe(false);
        // A type the API doesn't describe stays plain, under its own name.
        expect(roles.tool('nothing-like-it')).toBe(false);
        expect(roles.canonical('nothing-like-it')).toBe('nothing-like-it');
        expect(asked.sort()).toEqual([
            'GET /v1/step_types/automation-slack',
            'GET /v1/step_types/nothing-like-it',
            'GET /v1/step_types/trigger-form-input',
            'GET /v1/step_types/trigger-webhook',
        ]);
    });
});

describe('a step with no drawing of its own', () => {
    const at = (x: number) => ({ x, y: 0 });
    const sized = (node: Node, handles: NonNullable<Node['handles']> = []): Node => ({ ...node, width: 90, height: 90, handles });

    it('draws its card, the catalog’s name for it, and a handle for each connection it holds', async () => {
        const asked: string[] = [];
        const nodes = [
            sized(createWorkflowNode('hook', 'trigger-webhook', at(0), { label: 'Hook' })),
            sized(createWorkflowNode('branch', 'example-branch', at(200), { label: 'Branch' })),
            sized(createWorkflowNode('yes', 'log', at(400), { label: 'Yes' })),
            sized(createWorkflowNode('no', 'log', at(400), { label: 'No' })),
            sized(createWorkflowNode('agent', 'agent', at(600), { label: 'Agent' })),
            sized(createWorkflowNode('slack', 'automation-slack', at(600), { label: 'Slack' })),
        ];
        const edges: Edge[] = [
            { id: 'hook-branch', source: 'hook', target: 'branch' },
            { id: 'branch-yes', source: 'branch', target: 'yes', sourceHandle: 'true' },
            { id: 'branch-no', source: 'branch', target: 'no', sourceHandle: 'false', targetHandle: 'in-b' },
            { id: 'slack-agent', source: 'slack', target: 'agent', sourceHandle: 'top', targetHandle: 'bottom' },
        ];
        const { container } = render(
            <ClientProvider client={clientAsking(asked)}>
                <div style={{ width: 1000, height: 600 }}>
                    <ReactFlowProvider>
                        <ReactFlow nodes={nodes} edges={edges} nodeTypes={buildLazyNodeTypes()} />
                    </ReactFlowProvider>
                </div>
            </ClientProvider>
        );
        // One read for each type: the webhook, the branch (a type the API doesn't describe), the logs, the agent, Slack.
        await waitFor(() => expect(asked.length).toBe(5));
        await act(() => new Promise<void>((done) => setTimeout(done, 50)));
        const handles = (id: string) =>
            [...container.querySelectorAll(`.react-flow__node[data-id="${id}"] .react-flow__handle`)].map(
                (h) => `${h.getAttribute('data-handlepos')}:${h.getAttribute('data-handleid') ?? '-'}`
            );
        // Its branches, each a handle of its own down its right side.
        expect(handles('branch')).toEqual(['left:-', 'right:-', 'right:true', 'right:false']);
        // A connection into a handle the card doesn't draw gets one on its left.
        expect(handles('no')).toEqual(['left:-', 'right:-', 'left:in-b']);
        // An agent takes tools in from below; Slack, a tool, wires in from its top; the webhook takes nothing in.
        expect(handles('agent')).toEqual(['left:-', 'right:-', 'bottom:bottom']);
        expect(handles('slack')).toEqual(['left:-', 'right:-', 'top:top']);
        expect(handles('hook')).toEqual(['right:-']);
        expect(container.querySelector('.react-flow__node[data-id="hook"] [title^="Trigger"]')).not.toBeNull();
        // Its name: the label it was given, else the type's own words.
        expect(standing(STEP_DRAWING).definition('example-branch')?.label).toBe('Example Branch');
        expect(screen.getByText('Branch')).toBeTruthy();
    });

    it('is drawn for any type, as it’s met, and a note as a note', () => {
        const types = buildLazyNodeTypes({ mine: () => null });
        expect(typeof types['automation-anything']).toBe('function');
        expect(types['automation-anything']).toBe(types['automation-anything']);
        expect(types.mine).toBeTypeOf('function');
        // A promise's or React's checks never make a type.
        expect((types as Record<string, unknown>).then).toBeUndefined();
        expect(standing(STEP_DRAWING).definition('stickyNote')?.label).toBe('Sticky Note');
        expect(standing(STEP_DRAWING).useLoaded(['anything'])).toBe(true);
    });

    it('draws a note’s text as a README is drawn', async () => {
        const Note = buildLazyNodeTypes().stickyNote;
        render(
            <ClientProvider client={clientAsking([])}>
                <ReactFlowProvider>
                    <Note {...({ id: 'note', type: 'stickyNote', data: { content: 'Runs **daily**' }, selected: false } as unknown as NodeProps)} />
                </ReactFlowProvider>
            </ClientProvider>
        );
        expect((await screen.findByText('daily')).tagName).toBe('STRONG');
    });
});

describe('a build working on a step', () => {
    it('is known to the canvas only from the step’s own data: a build it follows marks the steps it adds', async () => {
        expect(standing(STEP_EDITING).editing('agent')).toBeNull();
        const asked: string[] = [];
        const node = { ...createWorkflowNode('log-1', 'log', { x: 0, y: 0 }, { label: 'Log' }), width: 90, height: 90 };
        node.data = { ...node.data, mcpAnimationState: 'adding' };
        render(
            <ClientProvider client={clientAsking(asked)}>
                <div style={{ width: 600, height: 400 }}>
                    <ReactFlowProvider>
                        <ReactFlow nodes={[node]} edges={[]} nodeTypes={buildLazyNodeTypes()} />
                    </ReactFlowProvider>
                </div>
            </ClientProvider>
        );
        expect(await screen.findByText('Adding...')).toBeTruthy();
    });
});
