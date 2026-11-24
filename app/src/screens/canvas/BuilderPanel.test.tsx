// @vitest-environment happy-dom
// The builder panel starts a build of the open workflow over the platform API: from its own box, from a request
// another part of the page sends (it opens itself to show it), and from one held while it wasn't drawn. While the build
// works the page hears so, and its end shows where no thread holds the builder's words. A build's message to the
// builder reads as the person's words alone.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NoClick } from 'noclick';
import { ClientProvider } from '@/sdk/client';
import BuilderPanel, { askedIn, SUBMIT_EVENT } from './BuilderPanel';
import { holdRequest, isBuilding, WORKING_EVENT } from './builderRequests';

type Json = Record<string, unknown>;

const BUILD = { object: 'operation', id: 'op_build', kind: 'workflow.build', status: 'running', workflow_id: 'wf_1' };

function platform() {
    const builds: Json[] = [];
    let finish: () => void = () => undefined;
    const finished = new Promise<void>((resolve) => (finish = resolve));
    const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });
    const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        const method = init?.method ?? 'GET';
        if (method === 'GET' && url.pathname === '/v1/workflows/wf_1/builder') {
            return json({ object: 'workflow_builder', workflow_id: 'wf_1', agent_id: null, conversation: null, build: null });
        }
        if (method === 'POST' && url.pathname === '/v1/workflows/wf_1/builds') {
            builds.push(JSON.parse(String(init?.body)));
            return json(BUILD, 202);
        }
        if (url.pathname.startsWith('/v1/operations/op_build')) {
            await finished;
            return json({ ...BUILD, status: 'succeeded', result: { workflow_id: 'wf_1', summary: 'Added a Slack step.', built: true } });
        }
        return json({ error: { type: 'not_found', message: 'Not found.' } }, 404);
    }) as typeof window.fetch;
    return { client: new NoClick({ apiKey: 'nk_test', baseUrl: 'https://api.test', maxRetries: 0, fetch }), builds, finish };
}

function panel(client: NoClick, onOpenChange = vi.fn()) {
    render(
        <ClientProvider client={client}>
            <BuilderPanel workflowId="wf_1" open={false} onOpenChange={onOpenChange} phone={false} offsetLeft={0} />
        </ClientProvider>
    );
    return onOpenChange;
}

afterEach(cleanup);

describe('the builder panel', () => {
    it('starts a build asked for elsewhere on the page, opening itself, and says when it works', async () => {
        const { client, builds, finish } = platform();
        const heard: boolean[] = [];
        const listen = (e: Event) => heard.push((e as CustomEvent<{ working: boolean }>).detail.working);
        document.addEventListener(WORKING_EVENT, listen);
        const onOpenChange = panel(client);
        await act(async () => void document.dispatchEvent(new CustomEvent(SUBMIT_EVENT, { detail: { prompt: 'Post new orders to Slack' } })));
        expect(onOpenChange).toHaveBeenCalledWith(true);
        await vi.waitFor(() => expect(builds).toEqual([{ instructions: 'Post new orders to Slack' }]));
        await vi.waitFor(() => expect(isBuilding('wf_1')).toBe(true));
        await act(async () => finish());
        await vi.waitFor(() => expect(isBuilding('wf_1')).toBe(false));
        expect(heard).toEqual([true, false]);
        document.removeEventListener(WORKING_EVENT, listen);
    });

    it('starts a build held for it before it was drawn', async () => {
        const { client, builds, finish } = platform();
        holdRequest('Add a Slack step for urgent emails');
        const onOpenChange = panel(client);
        await vi.waitFor(() => expect(builds).toEqual([{ instructions: 'Add a Slack step for urgent emails' }]));
        expect(onOpenChange).toHaveBeenCalledWith(true);
        finish();
    });

    it('builds from its own box and shows where the build ended when no thread holds the builder’s words', async () => {
        const { client, builds, finish } = platform();
        render(
            <ClientProvider client={client}>
                <BuilderPanel workflowId="wf_1" open onOpenChange={vi.fn()} phone={false} offsetLeft={0} />
            </ClientProvider>
        );
        fireEvent.change(screen.getByLabelText('What to build'), { target: { value: 'Add a Slack step' } });
        fireEvent.keyDown(screen.getByLabelText('What to build'), { key: 'Enter' });
        await vi.waitFor(() => expect(builds).toEqual([{ instructions: 'Add a Slack step' }]));
        expect(await screen.findByLabelText('Stop the build')).toBeTruthy();
        await act(async () => finish());
        expect(await screen.findByText('Added a Slack step.')).toBeTruthy();
        expect(screen.getByText('Built')).toBeTruthy();
    });
});

describe('a build’s message to the builder', () => {
    it('reads as the person’s words alone', () => {
        expect(askedIn('Build request for workflow "Orders" (id wf_1).\n\nPost new orders to Slack')).toBe('Post new orders to Slack');
        expect(
            askedIn('Build request for workflow "Orders" (id wf_1).\n\nPost new orders to Slack\n\nAsk nothing in this build: assume.')
        ).toBe('Post new orders to Slack');
    });

    it('is no ask when NoClick sent a finished build back', () => {
        expect(askedIn('The build left settings a run refuses.')).toBeNull();
    });
});
