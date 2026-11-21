// @vitest-environment happy-dom
// What the canvas's slots hold where no host fills them: a builder that builds the workflow over the platform API
// (its question answered on NoClick, its words when it's done), nobody else on the canvas, and the Interface tab, an
// agent's chat and sharing each saying where on NoClick they're done, with the way there.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { NoClick } from 'noclick';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { ClientProvider } from '@/sdk/client';
import { standing } from '@/slots';
import { AGENT_CHAT, BUILDER, INTERFACE, PRESENCE, SHARE, type CanvasBuilderProps } from './slots';

afterEach(cleanup);

const WORKFLOW = 'wf_7f3a';
const BUILD = { object: 'operation', id: 'op_build', kind: 'workflow.build', status: 'running', workflow_id: WORKFLOW };
const QUESTION = { id: 'ask_1', title: 'Which Slack channel should it post in?', inputs: [], answer_url: 'https://noclick.test/b/ask_1' };

/** A client whose builds go as `waits` says, one answer per wait on the build (each a promise the test may hold); every
 *  call is kept in `sent`. */
function builds(waits: Array<Promise<Record<string, unknown>>>) {
    const sent: { method: string; path: string; body: unknown }[] = [];
    const client = new NoClick({
        apiKey: 'held-by-this-app-server',
        baseUrl: 'http://app.test/api',
        maxRetries: 0,
        fetch: async (input, init) => {
            const path = new URL(String(input)).pathname.replace(/^\/api/, '');
            const method = init?.method ?? 'GET';
            sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
            if (method === 'POST' && path === `/v1/workflows/${WORKFLOW}/builds`) return Response.json(BUILD, { status: 201 });
            if (method === 'GET' && path === `/v1/operations/${BUILD.id}/wait`) {
                const next = waits.shift();
                if (!next) throw new Error('The test has no more answers for the build.');
                return Response.json(await next);
            }
            return Response.json({ error: { type: 'not_found', message: `No ${method} ${path} here.` } }, { status: 404 });
        },
    });
    return { client, sent };
}

function drawBuilder(client: NoClick, props: Partial<CanvasBuilderProps> = {}) {
    const Builder = standing(BUILDER);
    const onOpenChange = vi.fn();
    const onWidthChange = vi.fn();
    render(
        <ClientProvider client={client}>
            <Builder workflowId={WORKFLOW} open phone={false} onOpenChange={onOpenChange} onWidthChange={onWidthChange} {...props} />
        </ClientProvider>
    );
    return { onOpenChange, onWidthChange };
}

describe('the builder beside the canvas', () => {
    it('builds what’s asked for, shows the question it asks with its page on NoClick, then what it did', async () => {
        let finish!: (view: Record<string, unknown>) => void;
        const { client, sent } = builds([
            Promise.resolve({ ...BUILD, status: 'awaiting_human', question: QUESTION }),
            new Promise((resolve) => (finish = resolve)),
        ]);
        const { onWidthChange } = drawBuilder(client);

        const box = await screen.findByRole('textbox', { name: 'What to build' });
        expect(onWidthChange).toHaveBeenCalledWith(400);
        const send = screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement;
        expect(send.disabled).toBe(true);
        fireEvent.change(box, { target: { value: '  Post urgent emails to Slack  ' } });
        fireEvent.click(send);

        expect(screen.getByText('Post urgent emails to Slack')).toBeTruthy();
        expect(await screen.findByText('Which Slack channel should it post in?')).toBeTruthy();
        const answer = screen.getByRole('link', { name: /Answer on NoClick/ });
        expect(answer.getAttribute('href')).toBe(QUESTION.answer_url);
        expect(answer.getAttribute('target')).toBe('_blank');
        // One build at a time: nothing more is sent while this one waits.
        expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);

        await act(async () => finish({ ...BUILD, status: 'succeeded', result: { summary: 'Added a Slack step that posts urgent emails to #support.', built: true } }));
        expect(await screen.findByText('Added a Slack step that posts urgent emails to #support.')).toBeTruthy();
        expect(screen.getByText('Built')).toBeTruthy();
        expect(screen.queryByText('Which Slack channel should it post in?')).toBeNull();
        expect(sent.filter((call) => call.method === 'POST')).toEqual([{ method: 'POST', path: `/v1/workflows/${WORKFLOW}/builds`, body: { instructions: 'Post urgent emails to Slack' } }]);
    });

    it('says the API’s refusal in its own words, with its next step', async () => {
        const client = new NoClick({
            apiKey: 'held-by-this-app-server',
            baseUrl: 'http://app.test/api',
            maxRetries: 0,
            fetch: async () =>
                Response.json({ error: { type: 'conflict', message: 'This workflow is already being built.', next_step: 'Wait for that build to finish.' } }, { status: 409 }),
        });
        drawBuilder(client);
        fireEvent.change(await screen.findByRole('textbox', { name: 'What to build' }), { target: { value: 'Add a step' } });
        fireEvent.keyDown(screen.getByRole('textbox', { name: 'What to build' }), { key: 'Enter' });
        expect((await screen.findByRole('alert')).textContent).toBe('This workflow is already being built. Wait for that build to finish.');
    });

    it('asks for an open automation, closes itself, and is drawn on a laptop only while open', async () => {
        const { client, sent } = builds([]);
        const { onOpenChange } = drawBuilder(client, { workflowId: null });
        expect(await screen.findByText('Open an automation to build it.')).toBeTruthy();
        expect((screen.getByRole('textbox', { name: 'What to build' }) as HTMLTextAreaElement).disabled).toBe(true);
        fireEvent.click(screen.getByRole('button', { name: 'Close the builder' }));
        expect(onOpenChange).toHaveBeenCalledWith(false);
        cleanup();

        drawBuilder(client, { open: false });
        await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Build with NoClick' })).toBeNull());
        expect(sent).toEqual([]);
    });
});

describe('other people on the canvas', () => {
    it('is nobody, and what the canvas tells it goes nowhere', () => {
        const presence = standing(PRESENCE);
        const { result, rerender } = renderHook(() => presence.usePresence({ workflowId: WORKFLOW, enabled: true }));
        const first = result.current;
        expect(first.collaborators).toEqual([]);
        expect(first.nodeSelections.size).toBe(0);
        first.updateLocalCursor({ x: 1, y: 2 });
        first.broadcastNodeDrag('agent', { x: 3, y: 4 });
        rerender();
        // The same value every time, so what depends on it never runs again for nothing.
        expect(result.current).toBe(first);

        const { Layer, Cursors, Avatars } = presence;
        render(
            <Layer collaborators={[]} nodeSelections={new Map()}>
                <p>The steps</p>
            </Layer>
        );
        expect(screen.getByText('The steps')).toBeTruthy();
        const { container } = render(
            <>
                <Cursors collaborators={[]} />
                <Avatars collaborators={[]} />
            </>
        );
        expect(container.innerHTML).toBe('');
    });
});

describe('what’s done on NoClick', () => {
    it('opens the workflow on NoClick from the Interface tab', () => {
        const Interface = standing(INTERFACE);
        render(<Interface workflowId={WORKFLOW} />);
        expect(screen.getByText('The interface is laid out on NoClick')).toBeTruthy();
        expect(screen.getByRole('link', { name: /Open on NoClick/ }).getAttribute('href')).toBe(workflowUrl(NOCLICK_SITE, WORKFLOW));
    });

    it('names the agent whose chat is on NoClick', () => {
        const AgentChat = standing(AGENT_CHAT);
        render(<AgentChat id="agent" config={{ label: 'Support triage' }} isSelected={false} onConfigChange={() => undefined} workflowId={WORKFLOW} />);
        expect(screen.getByText('Talk to Support triage on NoClick')).toBeTruthy();
        expect(screen.getByRole('link', { name: /Open on NoClick/ }).getAttribute('href')).toBe(workflowUrl(NOCLICK_SITE, WORKFLOW));
    });

    it('shares the workflow on NoClick, and closes', () => {
        const Share = standing(SHARE);
        const onOpenChange = vi.fn();
        render(<Share open onOpenChange={onOpenChange} workflow={{ id: WORKFLOW, name: 'Support triage' }} />);
        expect(screen.getByRole('dialog', { name: 'Share this automation' })).toBeTruthy();
        expect(screen.getByRole('link', { name: /Share on NoClick/ }).getAttribute('href')).toBe(workflowUrl(NOCLICK_SITE, WORKFLOW));
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onOpenChange).toHaveBeenCalledWith(false);
    });
});
