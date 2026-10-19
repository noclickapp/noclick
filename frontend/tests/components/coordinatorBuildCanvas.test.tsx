// @vitest-environment jsdom
// A build draws its automation on the canvas, with no list of its parts under it. An automation's canvas draws once
// in a thread, on its newest card: an earlier build of it folds to one line (its name, how it stands, Open canvas),
// with the builder's question still under it when it asks one.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import type { CanvasProps } from '~/components/coordinator/inline/canvas';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));
vi.mock('~/hooks/useAttentionActions', () => ({ useAttentionActions: () => ({}) }));
vi.mock('~/components/dashboard/AskAnswer', () => ({
    AskAnswer: ({ item }: { item: { title: string; meta: { conversationId: string } } }) => (
        <p data-testid="ask" data-conversation={item.meta.conversationId}>
            {item.title}
        </p>
    ),
}));

import { CoordinatorTranscript } from '~/components/coordinator/CoordinatorTranscript';
import { registerCoordinatorCanvas } from '~/components/coordinator/inline/canvas';
import type { AgentChatMessage } from '~/hooks/useAgentChat';

registerCoordinatorCanvas(({ blob }: CanvasProps) => <div data-testid="canvas">{blob.nodes.length} steps</div>);

const INBOX = '11111111-1111-4111-8111-111111111111';
const DIGEST = '22222222-2222-4222-8222-222222222222';
const NODES = [
    { id: 'gmail', type: 'automation-gmail', position: { x: 0, y: 0 }, config: { label: 'New Gmail Inbox Email' } },
    { id: 'agent', type: 'agent', position: { x: 300, y: 0 }, config: { label: 'Email Draft Assistant' } },
];

afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

/** The socket: the coordinator's jobs, each workflow's graph, and the builder's parked questions. */
function serve(jobs: Record<string, Record<string, unknown>>, runs: Record<string, unknown>[] = []) {
    sendEventAsync.mockImplementation(async (req: { event_name: string; job_ids?: string[]; workflow_id?: string }) => {
        if (req.event_name === 'coordinator:jobs') return { jobs: (req.job_ids ?? []).flatMap((id) => (jobs[id] ? [{ job_id: id, kind: 'build', ...jobs[id] }] : [])) };
        if (req.event_name === 'workflow:get') return { workflow: { name: req.workflow_id === INBOX ? 'Email Reply Draft Assistant' : 'Daily digest', workflow_data: { nodes: NODES, edges: [] } } };
        if (req.event_name === 'workflow:builder:list_pending') return { data: { runs: runs.filter((r) => r.workflow_id === req.workflow_id) } };
        return {};
    });
}

function build(id: string, job: string, workflow: string, text: string): AgentChatMessage {
    return {
        isUser: false,
        text,
        isComplete: true,
        steps: [
            {
                id,
                kind: 'tool',
                status: 'completed',
                startedAt: 0,
                title: `Calling request_build(${JSON.stringify({ workflow_id: workflow, instructions: 'Draft replies' })})`,
                detail: JSON.stringify({ success: true, job_id: job, kind: 'build', workflow_id: workflow, builder_conversation_id: `builder-request:${job}`, status: 'queued' }),
            },
        ],
    };
}

const thread = (messages: AgentChatMessage[]) => <CoordinatorTranscript isStreaming={false} errorReason={null} messages={messages} />;

describe('a build’s card', () => {
    it('draws the automation on its canvas, with no list of its parts', async () => {
        serve({ j1: { status: 'completed' } });
        render(thread([build('c1', 'j1', INBOX, 'Built it.')]));
        const card = await screen.findByTestId('coordinator-build-card');
        await waitFor(() => expect(within(card).getByTestId('canvas').textContent).toBe('2 steps'));
        expect(card.textContent).toContain('Email Reply Draft Assistant');
        expect(card.textContent).not.toContain('New Gmail Inbox Email');
        expect(card.querySelector('ul')).toBeNull();
        // It opens from the canvas's own corner, with no "Open canvas" under it.
        expect(within(card).getByRole('button', { name: /^Open$/ })).toBeTruthy();
        expect(within(card).queryByRole('button', { name: /Open canvas/ })).toBeNull();
    });

    it('draws an automation’s canvas on its newest card and folds the earlier ones, keeping their questions', async () => {
        serve({ j1: { status: 'waiting' }, j2: { status: 'completed' }, j3: { status: 'completed' } }, [
            { conversation_id: 'builder-request:j1', workflow_id: INBOX, pending_ask: { ask_id: 'ask-1', title: 'Which Gmail label?' } },
        ]);
        render(thread([build('c1', 'j1', INBOX, 'Building it.'), build('c2', 'j2', DIGEST, 'And the digest.'), build('c3', 'j3', INBOX, 'Fixed it.')]));
        await waitFor(() => expect(screen.getAllByTestId('canvas')).toHaveLength(2));
        const [first, digest, newest] = screen.getAllByTestId('coordinator-build-card');

        // The first build of the inbox automation is one line now, its question still under it.
        expect(first.hasAttribute('data-folded')).toBe(true);
        expect(within(first).queryByTestId('canvas')).toBeNull();
        await waitFor(() => expect(first.textContent).toContain('Email Reply Draft Assistant'));
        expect(first.textContent).toContain('Needs you');
        expect(within(first).getByRole('button', { name: /Open canvas/ })).toBeTruthy();
        const ask = await within(first).findByTestId('ask');
        expect(ask.textContent).toBe('Which Gmail label?');
        expect(ask.dataset.conversation).toBe('builder-request:j1');

        // Another automation keeps its own canvas, and the inbox automation's is on its newest card.
        expect(digest.hasAttribute('data-folded')).toBe(false);
        expect(within(digest).getByTestId('canvas')).toBeTruthy();
        expect(newest.hasAttribute('data-folded')).toBe(false);
        expect(within(newest).getByTestId('canvas')).toBeTruthy();
        expect(newest.textContent).toContain('Built');
    });
});
