// @vitest-environment happy-dom
// The one live conversation hook every page uses, over the fake /v1 through the real SDK: what the Chat page's own
// hook did that Work's didn't, now for both. A send NoClick turns down because the account ran out keeps the message
// and ends on the refusal, with what its card draws; a turn that fails for no reason ends on the failure line its
// history keeps; what a message points at goes as the line naming it and comes back as chips, and files alone still
// say something; a page that can read the history by name draws it before the agent's lookup answers.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { WorkProviders } from '../agents/fixtures/providers';
import { AGENT_ID, fakeWorkAgent } from '../conversation/fixtures/workAgent';
import { TURN_FAILED_LINE } from '@/lib/agentThread/messages';
import { Agent, type Attachment } from 'noclick';
import { toMessage } from '@/sdk/source';
import { useAgentThread } from './useAgentThread';

afterEach(cleanup);

const at = (s: number) => new Date(Date.parse('2026-11-14T09:00:00Z') + s * 1000).toISOString();
const OUT_OF_FUNDS = { said: 'You’re out of funds, so I can’t start that. Add funds and I’ll pick it up.', invite_url: 'https://noclick.com/i/abc' };

function open(fake: ReturnType<typeof fakeWorkAgent>, caller: (client: ReturnType<typeof fakeWorkAgent>['client']) => Agent = (client) => Agent.fromId(AGENT_ID, { client }), readFirst?: () => Promise<ReturnType<typeof toMessage>[] | null>) {
    const wrapper = ({ children }: { children: ReactNode }) => <WorkProviders client={fake.client}>{children}</WorkProviders>;
    const agent = caller(fake.client);
    return renderHook(() => useAgentThread(agent, 'main', { key: AGENT_ID, readFirst }), { wrapper });
}

const turns = (result: { current: ReturnType<typeof useAgentThread> }) => result.current.thread.entries.filter((e) => e.kind === 'turn');
const users = (result: { current: ReturnType<typeof useAgentThread> }) => result.current.thread.entries.filter((e) => e.kind === 'user');

describe('useAgentThread', () => {
    it('keeps a message NoClick turned down because the account ran out, and ends on its refusal', async () => {
        const fake = fakeWorkAgent({ histories: { main: [] }, turn: () => ({ refused: { message: 'Payment required.', out_of_funds: OUT_OF_FUNDS } }) });
        const { result } = open(fake);
        await waitFor(() => expect(result.current.ready).toBe(true));
        let went = false;
        await act(async () => {
            went = await result.current.send({ text: 'Build me a site' });
        });
        expect(went).toBe(true);
        expect(users(result)).toMatchObject([{ text: 'Build me a site', pending: false }]);
        expect(turns(result)).toMatchObject([{ status: 'done', reply: OUT_OF_FUNDS.said, outOfFunds: OUT_OF_FUNDS }]);
        expect(result.current.error).toBeNull();
    });

    it('ends a turn that failed for no reason a person can act on on the failure line its history keeps', async () => {
        const fake = fakeWorkAgent({ histories: { main: [] }, turn: () => ({ error: 'The model stopped.' }) });
        const { result } = open(fake);
        await waitFor(() => expect(result.current.ready).toBe(true));
        await act(async () => void (await result.current.send({ text: 'Hi' })));
        await waitFor(() => expect(turns(result)).toMatchObject([{ status: 'failed', reply: TURN_FAILED_LINE }]));
    });

    it('sends what a message points at as the line naming it, draws it as chips, and says something for files alone', async () => {
        const fake = fakeWorkAgent({ histories: { main: [] } });
        const { result } = open(fake);
        await waitFor(() => expect(result.current.ready).toBe(true));
        const references = [{ kind: 'automation' as const, id: 'wf-1', label: 'Morning brief' }];
        await act(async () => void (await result.current.send({ text: 'Why did this fail?', references })));
        expect(fake.requests.filter((r) => r.method === 'POST' && r.path.endsWith('/messages')).map((r) => (r.body as { text: string }).text)).toEqual(['Why did this fail?\n\n(About the automation “Morning brief” (workflow wf-1).)']);
        await waitFor(() => expect(users(result)).toMatchObject([{ text: 'Why did this fail?', references, pending: false }]));
        const pdf = { id: 'att-1', name: 'brief.pdf', mimeType: 'application/pdf', sizeBytes: 1, kind: 'file', url: 'https://files.test/brief.pdf', voice: false, durationMs: null, peaks: null, raw: {} } as Attachment;
        await waitFor(() => expect(result.current.working).toBe(false));
        await act(async () => void (await result.current.send({ text: '', files: [pdf] })));
        expect((fake.requests.filter((r) => r.method === 'POST' && r.path.endsWith('/messages')).at(-1)!.body as { text: string }).text).toBe('(Files attached.)');
    });

    it('draws the history read by name before the agent’s lookup answers', async () => {
        const fake = fakeWorkAgent({ histories: { main: [] } });
        const early = [toMessage({ role: 'user', text: 'Hi', created_at: at(0) }), toMessage({ role: 'assistant', text: 'Hello, from before the lookup.', created_at: at(1) })];
        // A lookup that hasn't answered yet.
        const waiting = (client: ReturnType<typeof fakeWorkAgent>['client']) => Object.assign(Agent.fromName('coordinator', { client }), { hydrate: () => new Promise<never>(() => undefined) });
        const { result } = open(fake, waiting, async () => early);
        await waitFor(() => expect(turns(result)).toMatchObject([{ reply: 'Hello, from before the lookup.' }]));
        expect(result.current.ready).toBe(false);
    });
});
