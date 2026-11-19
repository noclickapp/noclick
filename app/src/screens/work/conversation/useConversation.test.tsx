// @vitest-environment happy-dom
// Work's conversation hook over the fake /v1, through the real SDK, across a dropped stream: the stream is taken up
// again and the history read afresh, but only the first connection replays what the stream keeps, so a turn at work
// when it dropped keeps its words and its commands' output once, and a turn that ended while it was down still ends.
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { WorkProviders } from '../agents/fixtures/providers';
import { AGENT_ID, fakeWorkAgent, type LiveEvent } from './fixtures/workAgent';
import { liveTurn, stepsOf, type Thread } from '@/lib/agentThread/thread';
import { useConversation } from './useConversation';

afterEach(cleanup);

const WAKE = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a02';
const at = (s: number) => new Date(Date.parse('2026-11-14T09:00:00Z') + s * 1000).toISOString();
// The first reconnection waits a second.
const RECONNECTED = { timeout: 4000 };

async function open(fake: ReturnType<typeof fakeWorkAgent>) {
    const wrapper = ({ children }: { children: ReactNode }) => <WorkProviders client={fake.client}>{children}</WorkProviders>;
    const hook = renderHook(() => useConversation(AGENT_ID, 'main'), { wrapper });
    await waitFor(() => expect(fake.watching()).toBe(1));
    return hook;
}

const watches = (fake: ReturnType<typeof fakeWorkAgent>) => fake.requests.filter((r) => r.path.endsWith('/conversations/main/events')).map((r) => r.query.get('replay'));

/** The turn at work's words and its command's output, as the page holds them. */
function atWork(thread: Thread) {
    const turn = liveTurn(thread)!;
    return { words: turn.parts.flatMap((p) => (p.kind === 'text' ? [p.text] : [])).join(''), output: stepsOf(turn)[0]?.output };
}

const working = (op: string): LiveEvent[] => [
    { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'npm test' }, kind: 'command', command: 'npm test', operation_id: op },
    { type: 'output', id: 'toolu_01', text: 'PASS a.test.ts\n', operation_id: op },
    { type: 'text', id: 'msg_01:0', text: 'Running the tests.', operation_id: op },
];

describe('a page opened mid-turn', () => {
    it('draws the turn at work from what the stream replays, and nothing of the turns its history holds', async () => {
        const QUIET = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a05';
        const RUN = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a06';
        const fake = fakeWorkAgent({
            histories: {
                main: [
                    // A wake-up that checked something and said nothing: no reply, so history draws no turn for it.
                    { id: 'm0', role: 'user', text: 'Check the deploy.', created_at: at(0), trigger: { kind: 'wakeup', id: 'wk-1' }, operation_id: QUIET },
                    { id: 'm1', role: 'user', text: 'Why is the build red?', created_at: at(60), operation_id: RUN },
                ],
            },
            operations: [
                { object: 'operation', id: QUIET, kind: 'agent.message', status: 'succeeded', conversation: 'main', created_at: at(0) },
                { object: 'operation', id: RUN, kind: 'agent.message', status: 'running', conversation: 'main', created_at: at(60), started_at: at(60) },
            ],
        });
        // What the stream keeps of the last hour, sent before the page opened.
        fake.emit([...working(QUIET), { type: 'turn_end', status: 'succeeded', text: '', operation_id: QUIET }, ...working(RUN)]);
        const { result } = await open(fake);
        expect(watches(fake)).toEqual(['1']);
        await waitFor(() => expect(atWork(result.current.thread)).toEqual({ words: 'Running the tests.', output: 'PASS a.test.ts\n' }));
        expect(result.current.thread.entries.map((e) => (e.kind === 'turn' ? `turn ${e.operationId}` : e.kind))).toEqual(['user', 'user', `turn ${RUN}`]);
    });
});

describe('a dropped stream', () => {
    it('keeps the words and output of the turn at work once when the stream drops mid-turn', async () => {
        const fake = fakeWorkAgent({ turn: (op) => ({ events: working(op), hold: true }) });
        const { result } = await open(fake);
        await act(async () => void (await result.current.send({ text: 'Why is the build red?' })));
        await waitFor(() => expect(atWork(result.current.thread)).toEqual({ words: 'Running the tests.', output: 'PASS a.test.ts\n' }));

        act(() => fake.drop());
        await waitFor(() => expect(watches(fake)).toHaveLength(2), RECONNECTED);
        await waitFor(() => expect(fake.watching()).toBe(1));
        // What comes next continues the turn, once.
        act(() =>
            fake.emit([
                { type: 'output', id: 'toolu_01', text: 'FAIL b.test.ts\n', operation_id: 'op-turn-1' },
                { type: 'text', id: 'msg_01:0', text: ' One fails.', operation_id: 'op-turn-1' },
            ])
        );
        await waitFor(() => expect(atWork(result.current.thread).words).toContain('One fails.'));
        expect(atWork(result.current.thread)).toEqual({ words: 'Running the tests. One fails.', output: 'PASS a.test.ts\nFAIL b.test.ts\n' });
        expect(result.current.thread.entries.map((e) => e.kind)).toEqual(['user', 'turn']);
    });

    it('replays only on the first connection', async () => {
        const fake = fakeWorkAgent();
        await open(fake);
        act(() => fake.drop());
        await waitFor(() => expect(watches(fake)).toEqual(['1', null]), RECONNECTED);
    });

    it('ends a turn no one here started that ended while the stream was down, as its operation says', async () => {
        const fake = fakeWorkAgent({ operations: [{ object: 'operation', id: WAKE, kind: 'agent.message', status: 'running', conversation: 'main', created_at: at(0) }] });
        const { result } = await open(fake);
        const woken = { id: 'm0', role: 'user', text: 'The deployment finished. Read its result.', created_at: at(0), trigger: { kind: 'wakeup', id: 'wk-1' }, operation_id: WAKE };
        fake.histories.get('main')!.push(woken);
        act(() => fake.emit([{ type: 'message', ...woken }, ...working(WAKE)]));
        await waitFor(() => expect(liveTurn(result.current.thread)?.operationId).toBe(WAKE));

        act(() => fake.drop());
        // It said nothing, so it saved no reply: only its turn_end, sent while no one watched, says it ended.
        fake.settle(WAKE, 'succeeded', { result: { text: '', conversation: 'main', tool_calls: [], operation_id: WAKE } });
        await waitFor(() => expect(liveTurn(result.current.thread)).toBeNull(), RECONNECTED);
        expect(result.current.working).toBe(false);
        expect(result.current.thread.entries.at(-1)).toMatchObject({ kind: 'turn', operationId: WAKE, status: 'done' });
    });
});
