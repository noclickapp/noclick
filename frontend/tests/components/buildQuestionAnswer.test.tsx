// @vitest-environment jsdom
// Answering a build's question on its card: the question gives way to the build at once, so it's answered once; the
// builder's next question shows when it asks one, though the build read back still names the question answered; and an
// answer the builder refuses puts the question back.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { CanvasProps } from '~/components/coordinator/inline/canvas';
import type { AttentionItem } from '~/components/dashboard/types';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));
vi.mock('~/components/dashboard/AskAnswer', async () => {
    const { useDashboardActions } = await vi.importActual<typeof import('~/components/dashboard/primitives')>('~/components/dashboard/primitives');
    return {
        AskAnswer: ({ item }: { item: AttentionItem }) => {
            const { answerAsk } = useDashboardActions();
            return (
                <button type="button" data-testid="ask" onClick={() => answerAsk(item, { ask_0: 'cred-1' })}>
                    {item.title}
                </button>
            );
        },
    };
});

import { WorkflowBuild } from '~/components/coordinator/cards/BuildCard';
import { registerCoordinatorCanvas } from '~/components/coordinator/inline/canvas';
import { CoordinatorJobsContext, type CoordinatorJob } from '~/hooks/useCoordinatorJobs';

registerCoordinatorCanvas(({ blob }: CanvasProps) => <div data-testid="canvas">{blob.nodes.length} steps</div>);

const WORKFLOW = '11111111-1111-4111-8111-111111111111';
const CONVERSATION = 'builder-request:job-1';

afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

/** The socket: the workflow, the builder's parked question, and answers held until the test says how they went. */
function serve(ask: { ask_id: string; title: string }) {
    const state = { ask, answers: [] as ((reply: Record<string, unknown>) => void)[] };
    sendEventAsync.mockImplementation(async (req: { event_name: string; workflow_id?: string }) => {
        if (req.event_name === 'workflow:get') return { workflow: { name: 'Confluence and Monday.com', workflow_data: { nodes: [], edges: [] } } };
        if (req.event_name === 'workflow:builder:list_pending') return { data: { runs: [{ conversation_id: CONVERSATION, workflow_id: WORKFLOW, pending_ask: state.ask }] } };
        if (req.event_name === 'workflow:builder:input_response') return new Promise((resolve) => state.answers.push(resolve));
        return {};
    });
    return state;
}

/** A build the platform API started: it names its question, never the builder's conversation. */
function card() {
    const job: CoordinatorJob = { job_id: 'op-1', kind: 'workflow.build', status: 'waiting', question: { id: 'ask-1' }, created_at: '', updated_at: '' };
    return render(
        <CoordinatorJobsContext.Provider value={{ live: true, get: (id) => (id === 'op-1' ? job : undefined) }}>
            <WorkflowBuild callId="c1" workflowId={WORKFLOW} jobId="op-1" />
        </CoordinatorJobsContext.Provider>
    );
}

const status = () => screen.getAllByTestId('build-status').at(-1)?.dataset.state;
const answers = () => sendEventAsync.mock.calls.filter(([req]) => req.event_name === 'workflow:builder:input_response');

describe('answering a build’s question on its card', () => {
    it('steps aside for the build at once, then shows the builder’s next question', async () => {
        const server = serve({ ask_id: 'ask-1', title: 'Connect Anthropic' });
        card();
        fireEvent.click(await screen.findByText('Connect Anthropic'));

        // Sent: the build goes on with it, and there's nothing left to answer twice.
        await waitFor(() => expect(screen.queryByTestId('ask')).toBeNull());
        expect(status()).toBe('building');
        expect(answers()).toHaveLength(1);

        // The builder asks again before the build is read back, still naming the question answered.
        server.ask = { ask_id: 'ask-2', title: 'Connect Confluence and Monday.com' };
        await act(async () => server.answers[0]({ data: { success: true } }));
        expect((await screen.findByTestId('ask')).textContent).toBe('Connect Confluence and Monday.com');
        expect(status()).toBe('waiting');
    });

    it('puts the question back when the builder refuses the answer', async () => {
        const server = serve({ ask_id: 'ask-1', title: 'Connect Anthropic' });
        card();
        fireEvent.click(await screen.findByText('Connect Anthropic'));
        await waitFor(() => expect(screen.queryByTestId('ask')).toBeNull());

        await act(async () => server.answers[0]({ error: 'This build is not waiting for that answer, or has already resumed.' }));
        expect((await screen.findByTestId('ask')).textContent).toBe('Connect Anthropic');
        expect(status()).toBe('waiting');
    });
});
