// An agent conversation's reducer, pinned on recorded sequences of the /v1 conversation stream: each frame is what the
// API's stream sends (its event name, then its data, empty fields left out), read through the SDK's own parser, and
// each history message is what GET …/conversations/{key} returns.
import { describe, expect, it } from 'vitest';
import { composeMessage, TURN_FAILED_LINE } from './messages';
import type { AgentEvent, JsonObject } from 'noclick';
import { toAgentEvent, toMessage } from '@/sdk/source';
import { applyEvent, EMPTY_THREAD, ended, failureOf, failuresTold, fromHistory, liveTurn, pendingRequests, reread, runningTurn, sent, started, stepsOf, subagentsOf, unanswered, unsent, withFailure, type Step, type Thread, type TurnEntry } from './thread';

const AT = Date.parse('2026-11-14T09:00:00Z');
const iso = (s: number) => new Date(AT + s * 1000).toISOString();

const ASK = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a01';
const WAKE = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a02';
const TEXTED = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a03';
const EARLIER = '7c1f3e2a-5b4d-4e6f-8a9b-0c1d2e3f4a04';

type Frame = JsonObject & { type: string };

/** The frames as the SDK reads them off the stream. */
const heard = (frames: readonly Frame[]): AgentEvent[] => frames.map(({ type, ...data }) => toAgentEvent(type, data));

/** The thread after `frames`, a second apart from `from`. */
const play = (thread: Thread, frames: readonly Frame[], from = AT): Thread => heard(frames).reduce((t, e, i) => applyEvent(t, e, from + i * 1000), thread);

const history = (...messages: JsonObject[]): Thread => ({ ...EMPTY_THREAD, entries: fromHistory(messages.map(toMessage), AT) });

const stepLine = (s: Step): string =>
    [s.tool, s.running ? '…' : null, s.output ? `› ${s.output.trim()}` : null, s.exitCode !== null ? `exit ${s.exitCode}` : null, s.said ? `says “${s.said}”` : null, s.children.length ? `[${s.children.map(stepLine).join('; ')}]` : null].filter(Boolean).join(' ');

/** What each entry draws: a person's words, a turn's status, its parts in order and its reply. */
function drawn(thread: Thread): unknown[] {
    return thread.entries.map((e) => {
        if (e.kind === 'user') return `${e.pending ? 'sending' : e.author?.type === 'person' ? e.author.name : e.trigger ? e.trigger.kind : 'user'}: ${e.text}`;
        if (e.kind === 'note') return `note: ${e.text}`;
        if (e.kind === 'marker') return `— ${e.text} —`;
        return { [e.status]: e.reply, parts: e.parts.map((p) => (p.kind === 'steps' ? p.steps.map(stepLine) : p.kind === 'text' ? p.text : `steer: ${p.entry.text}`)) };
    });
}

const turns = (thread: Thread) => thread.entries.filter((e): e is TurnEntry => e.kind === 'turn');

// ── Recorded sequences ──────────────────────────────────────────────────────

/** A turn on NoClick's own tools (the SDK harness): no call ids, the reply saved with its calls. */
const LOOKUP = { tool: 'noclick__api_call', arguments: { operation: 'workflows_runs_list', status: 'failed' }, result: '{"data": [{"workflow_name": "Inbox drafts"}], "total": 1}', is_error: false, created_at: iso(2) };
const OWN_TURN: Frame[] = [
    { type: 'message', id: '2', role: 'user', text: 'Which automations failed today?', created_at: iso(0), operation_id: ASK },
    { type: 'tool_call', tool: 'noclick__api_call', arguments: LOOKUP.arguments, operation_id: ASK },
    { type: 'tool_result', tool: 'noclick__api_call', is_error: false, result: LOOKUP.result, operation_id: ASK },
    { type: 'text', text: 'One: ', operation_id: ASK },
    { type: 'text', text: 'Inbox drafts.', operation_id: ASK },
    { type: 'message', id: '3', role: 'assistant', text: 'One: Inbox drafts.', created_at: iso(5), tool_calls: [LOOKUP], operation_id: ASK },
];

/** A wake-up the agent set, on a coding harness: its own shell (call ids, printed output, an exit code), its reply. */
const WAKEUP = { kind: 'wakeup', id: 'wk-1', title: 'The deployment finished' };
const WAKE_TURN: Frame[] = [
    { type: 'message', id: '4', role: 'user', text: 'The deployment finished. Read its result.', created_at: iso(60), trigger: WAKEUP, operation_id: WAKE },
    { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'gh run view 42', cwd: '/workspace' }, kind: 'command', command: 'gh run view 42', at: AT + 61_000, operation_id: WAKE },
    { type: 'output', id: 'toolu_01', text: '✓ deploy 42 · 1m 12s\n', at: AT + 62_000, operation_id: WAKE },
    { type: 'tool_result', id: 'toolu_01', tool: 'shell', source: 'harness', is_error: false, duration_ms: 1200, exit_code: 0, kind: 'command', at: AT + 62_000, operation_id: WAKE },
    { type: 'text', id: 'msg_01:1', text: 'Deploy 42 is live.', at: AT + 63_000, operation_id: WAKE },
];
const WAKE_REPLY: Frame = { type: 'message', id: '5', role: 'assistant', text: 'Deploy 42 is live.', created_at: iso(64), operation_id: WAKE };

const SETTLED_HISTORY: JsonObject[] = [
    { id: '0', role: 'user', text: 'Keep an eye on the deploys.', created_at: iso(-600), operation_id: EARLIER, author: { type: 'account', id: null, name: 'Sam Rivera' } },
    { id: '1', role: 'assistant', text: 'Will do.', created_at: iso(-590), operation_id: EARLIER },
];

describe('history', () => {
    it('reads each reply as a settled turn, a coding harness’s steps nested under the call they worked for', () => {
        const thread = history(
            ...SETTLED_HISTORY,
            { id: '2', role: 'user', text: 'Why do the tests flake?', created_at: iso(0), operation_id: ASK },
            {
                id: '3',
                role: 'assistant',
                text: 'test_retry races the clock.',
                created_at: iso(30),
                operation_id: ASK,
                tool_calls: [
                    { id: 'toolu_task', source: 'harness', kind: 'tool', tool: 'Task', arguments: { description: 'Find the flaky tests' }, output: 'test_retry flakes.', is_error: false, created_at: iso(1) },
                    { id: 'toolu_grep', source: 'harness', kind: 'search', tool: 'Grep', arguments: { pattern: 'sleep' }, query: 'sleep', result: 'Found 2 files', is_error: false, created_at: iso(2), parent: 'toolu_task' },
                    { id: 'toolu_run', source: 'harness', kind: 'command', tool: 'shell', arguments: { command: 'pytest -q' }, command: 'pytest -q', output: '1 failed\n', exit_code: 1, is_error: false, created_at: iso(20) },
                ],
            },
            { id: '4', role: 'note', text: 'Moved to the new machine.', created_at: iso(40) },
            { id: '5', role: 'person', text: 'I’ll take it from here.', created_at: iso(50), name: 'Priya' }
        );
        expect(drawn(thread)).toEqual([
            'user: Keep an eye on the deploys.',
            { done: 'Will do.', parts: [] },
            'user: Why do the tests flake?',
            { done: 'test_retry races the clock.', parts: [['Task › test_retry flakes. [Grep]', 'shell › 1 failed exit 1']] },
            'note: Moved to the new machine.',
            'Priya: I’ll take it from here.',
        ]);
        // Timed from the message it answers; nothing runs.
        expect(turns(thread)[1]).toMatchObject({ id: '3', operationId: ASK, startedAt: AT, endedAt: AT + 30_000 });
        expect(liveTurn(thread)).toBeNull();
        expect(unanswered(thread.entries)).toBeNull();
    });

    it('keeps why a failed reply failed, in its own words, without the provider’s raw answer', () => {
        const failure = { type: 'credential_disconnected', reason: 'provider_rejected', connection: 'credential:c1', connection_name: 'OpenRouter key', integration: 'openrouter', message: 'OpenRouter refused this key. Provider message: User not found.', provider_said: 'User not found.', next_step: 'Connect it again.' };
        const thread = history({ id: '0', role: 'user', text: 'Hi', created_at: iso(0), operation_id: ASK }, { id: '1', role: 'assistant', text: TURN_FAILED_LINE, created_at: iso(3), failed: true, failure, operation_id: ASK });
        expect(turns(thread)[0]).toMatchObject({
            status: 'failed',
            reply: TURN_FAILED_LINE,
            failure: { reason: 'provider_rejected', connection: 'credential:c1', connectionName: 'OpenRouter key', integration: 'openrouter', message: 'OpenRouter refused this key.', providerSaid: 'User not found.', nextStep: 'Connect it again.', billingUrl: null },
        });
        // A failure no person can act on carries no reason.
        expect(failureOf({ type: 'internal', message: 'Boom' })).toBeNull();
    });

    it('leaves the message nothing answered yet as the turn its operation may still run', () => {
        const entries = fromHistory([...SETTLED_HISTORY, { id: '2', role: 'user', text: 'Which automations failed today?', created_at: iso(0), operation_id: ASK }].map(toMessage), AT);
        expect(unanswered(entries)).toMatchObject({ text: 'Which automations failed today?', operationId: ASK });
    });
});

describe('a turn this page sent', () => {
    const sending = sent(history(...SETTLED_HISTORY), 'sent:1', 'Which automations failed today?', [], AT);

    it('draws the message and a running turn at once, then names both by the send’s operation', () => {
        expect(drawn(sending).slice(2)).toEqual(['sending: Which automations failed today?', { running: null, parts: [] }]);
        const named = started(sending, 'sent:1', ASK);
        expect(named.entries.slice(2).map((e) => (e.kind === 'user' || e.kind === 'turn' ? e.operationId : null))).toEqual([ASK, ASK]);
        expect(liveTurn(named)?.operationId).toBe(ASK);
    });

    it('fills the turn from the stream and settles it on its reply: steps from the saved calls, the reply’s words', () => {
        const live = play(started(sending, 'sent:1', ASK), OWN_TURN.slice(0, 5));
        expect(drawn(live).slice(2)).toEqual(['user: Which automations failed today?', { running: null, parts: [['noclick__api_call'], 'One: Inbox drafts.'] }]);
        // The message came back: it's the one sent, now with its id.
        expect(live.entries[2]).toMatchObject({ key: 'sent:1', id: '2', pending: false });

        const done = play(live, OWN_TURN.slice(5), AT + 5000);
        expect(drawn(done).slice(2)).toEqual(['user: Which automations failed today?', { done: 'One: Inbox drafts.', parts: [['noclick__api_call']] }]);
        expect(turns(done).at(-1)).toMatchObject({ id: '3', operationId: ASK, endedAt: AT + 5000 });
        expect(liveTurn(done)).toBeNull();
        // Its operation's wait answering after the stream settled it changes nothing.
        expect(ended(done, ASK, { status: 'done', reply: 'One: Inbox drafts.', at: AT + 9000 })).toBe(done);
    });

    it('settles on its operation’s wait when that answers first, and the reply that lands after names it', () => {
        const live = play(started(sending, 'sent:1', ASK), OWN_TURN.slice(0, 5));
        const waited = ended(live, ASK, { status: 'done', reply: 'One: Inbox drafts.', at: AT + 4000 });
        expect(drawn(waited).at(-1)).toEqual({ done: 'One: Inbox drafts.', parts: [['noclick__api_call'], 'One: Inbox drafts.'] });
        expect(turns(waited).at(-1)?.id).toBeNull();
        const named = play(waited, OWN_TURN.slice(5));
        expect(drawn(named).at(-1)).toEqual({ done: 'One: Inbox drafts.', parts: [['noclick__api_call']] });
        expect(turns(named).at(-1)?.id).toBe('3');
    });

    it('takes back a send that failed before any turn started', () => {
        expect(unsent(sending, 'sent:1')).toEqual(history(...SETTLED_HISTORY));
    });
});

describe('a turn no person started', () => {
    it('shows its message, then a turn from its first moment: commands with what they printed and how they exited', () => {
        const woken = play(history(...SETTLED_HISTORY), WAKE_TURN.slice(0, 1), AT + 60_000);
        // Nothing is at work until its first moment arrives.
        expect(drawn(woken).slice(2)).toEqual(['wakeup: The deployment finished. Read its result.']);
        expect(woken.entries[2]).toMatchObject({ trigger: WAKEUP, operationId: WAKE });
        expect(liveTurn(woken)).toBeNull();

        const working = play(woken, WAKE_TURN.slice(1, 3), AT + 61_000);
        expect(drawn(working).at(-1)).toEqual({ running: null, parts: [['shell … › ✓ deploy 42 · 1m 12s']] });
        expect(stepsOf(liveTurn(working)!)[0]).toMatchObject({ id: 'toolu_01', kind: 'command', source: 'harness', command: 'gh run view 42' });

        const done = play(working, [...WAKE_TURN.slice(3), WAKE_REPLY], AT + 62_000);
        expect(drawn(done).at(-1)).toEqual({ done: 'Deploy 42 is live.', parts: [['shell › ✓ deploy 42 · 1m 12s exit 0']] });
        expect(stepsOf(turns(done).at(-1)!)[0]).toMatchObject({ durationMs: 1200, isError: false });
        expect(liveTurn(done)).toBeNull();
    });
});

describe('the stream saying a turn ended', () => {
    // A wake-up that checked something and had nothing to say: it saves no reply, so only its turn_end closes it.
    const working = play(history(...SETTLED_HISTORY), WAKE_TURN.slice(0, 4), AT + 60_000);
    const end = (status: string, text?: string, operationId = WAKE): Frame => ({ type: 'turn_end', status, ...(text === undefined ? {} : { text }), operation_id: operationId });

    it('closes a turn no person started, as it ended: its words, the failure line, or nothing', () => {
        expect(liveTurn(working)).not.toBeNull();
        const quiet = play(working, [end('succeeded', '')]);
        expect(drawn(quiet).at(-1)).toEqual({ done: null, parts: [['shell › ✓ deploy 42 · 1m 12s exit 0']] });
        expect(liveTurn(quiet)).toBeNull();
        expect(drawn(play(working, [end('succeeded', 'Deploy 42 is live.')])).at(-1)).toMatchObject({ done: 'Deploy 42 is live.' });
        expect(drawn(play(working, [end('failed')])).at(-1)).toMatchObject({ failed: TURN_FAILED_LINE });
        expect(drawn(play(working, [end('canceled')])).at(-1)).toMatchObject({ stopped: null });
        expect(drawn(play(working, [end('expired')])).at(-1)).toMatchObject({ stopped: null });
        // Its reply landing after names it, as ever.
        expect(turns(play(quiet, [{ ...WAKE_REPLY, text: '' }])).at(-1)).toMatchObject({ id: '5', status: 'done' });
    });

    it('takes away a turn that drew nothing, as history reads it, and leaves its message', () => {
        const thinking = play(history(...SETTLED_HISTORY), [WAKE_TURN[0], { type: 'reasoning', text: 'Checking the deploy', operation_id: WAKE }], AT + 60_000);
        expect(liveTurn(thinking)).not.toBeNull();
        expect(drawn(play(thinking, [end('succeeded', '')]))).toEqual(drawn(history(...SETTLED_HISTORY)).concat('wakeup: The deployment finished. Read its result.'));
        // One whose harness asked a person keeps its place for that ask.
        const asked = play(thinking, [{ type: 'request', request: { id: 'req-1', kind: 'approval', status: 'expired', operation_id: WAKE }, operation_id: WAKE }]);
        expect(liveTurn(play(asked, [end('canceled')]))).toBeNull();
        expect(turns(play(asked, [end('canceled')])).at(-1)).toMatchObject({ operationId: WAKE, status: 'stopped' });
    });

    it('leaves a turn running for another turn’s end, or one naming none', () => {
        expect(play(working, [end('succeeded', 'Hi', EARLIER), { type: 'turn_end', status: 'succeeded', text: 'Hi' }])).toEqual(working);
    });

    it('closes this page’s own turn only once it succeeded: its wait says how it failed or stopped', () => {
        const mine = play(started(sent(EMPTY_THREAD, 'sent:1', 'Which automations failed today?', [], AT), 'sent:1', ASK), OWN_TURN.slice(0, 3));
        const following = new Set([ASK]);
        for (const status of ['failed', 'canceled', 'expired']) expect(applyEvent(mine, heard([end(status, undefined, ASK)])[0], AT, following)).toBe(mine);
        const done = applyEvent(mine, heard([end('succeeded', 'One: Inbox drafts.', ASK)])[0], AT + 5000, following);
        expect(drawn(done).at(-1)).toEqual({ done: 'One: Inbox drafts.', parts: [['noclick__api_call']] });
        // Even one that drew nothing stays, its message answered.
        const bare = started(sent(EMPTY_THREAD, 'sent:1', 'Hi', [], AT), 'sent:1', ASK);
        expect(drawn(applyEvent(bare, heard([end('succeeded', '', ASK)])[0], AT, following))).toEqual(['sending: Hi', { done: null, parts: [] }]);
    });
});

describe('a message that joins the turn under way', () => {
    const live = play(started(sent(EMPTY_THREAD, 'sent:1', 'Deploy it', [], AT), 'sent:1', ASK), [
        { type: 'message', id: '0', role: 'user', text: 'Deploy it', created_at: iso(0), operation_id: ASK },
        { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'make deploy' }, kind: 'command', command: 'make deploy', operation_id: ASK },
    ]);

    it('sits in that turn, the page’s own as sent, then as the conversation showed it back', () => {
        const steered = sent(live, 'sent:2', 'Use staging instead', [], AT + 3000, { steer: true });
        expect(drawn(steered).at(-1)).toEqual({ running: null, parts: [['shell …'], 'steer: Use staging instead'] });
        const shown = play(steered, [{ type: 'message', id: '1', role: 'user', text: 'Use staging instead', created_at: iso(3), operation_id: ASK }], AT + 4000);
        const steer = liveTurn(shown)!.parts.at(-1);
        expect(steer).toMatchObject({ kind: 'user', entry: { key: 'sent:2', id: '1', pending: false, steer: true } });
    });

    it('draws one from another app in the turn too, and keeps both around its reply', () => {
        const joined = play(live, [{ type: 'message', id: '1', role: 'user', text: 'Also check prod', via: 'whatsapp', created_at: iso(3), operation_id: ASK }], AT + 3000);
        expect(liveTurn(joined)!.parts.at(-1)).toMatchObject({ kind: 'user', entry: { text: 'Also check prod', via: 'whatsapp', steer: true } });
        const done = play(joined, [
            { type: 'tool_result', id: 'toolu_01', tool: 'shell', source: 'harness', is_error: false, exit_code: 0, kind: 'command', operation_id: ASK },
            { type: 'message', id: '2', role: 'assistant', text: 'Deployed to staging; prod is fine.', created_at: iso(9), operation_id: ASK },
        ]);
        expect(drawn(done).at(-1)).toEqual({ done: 'Deployed to staging; prod is fine.', parts: [['shell exit 0'], 'steer: Also check prod'] });
    });
});

describe('a harness subagent', () => {
    const TASK: Frame = { type: 'tool_call', id: 'toolu_task', tool: 'Task', source: 'harness', arguments: { description: 'Find the flaky tests', subagent_type: 'general-purpose' }, kind: 'tool', operation_id: ASK };
    const ITS_WORK: Frame[] = [
        { type: 'tool_call', id: 'toolu_grep', tool: 'Grep', source: 'harness', arguments: { pattern: 'sleep' }, kind: 'search', query: 'sleep', parent: 'toolu_task', operation_id: ASK },
        { type: 'tool_result', id: 'toolu_grep', tool: 'Grep', source: 'harness', is_error: false, duration_ms: 40, result: 'Found 2 files', kind: 'search', parent: 'toolu_task', operation_id: ASK },
        { type: 'text', id: 'msg_s1:0', text: 'test_retry ', parent: 'toolu_task', operation_id: ASK },
        { type: 'text', id: 'msg_s1:0', text: 'sleeps.', parent: 'toolu_task', operation_id: ASK },
    ];
    // Its end carries its last words as the call's output, before the call's own end.
    const ITS_END: Frame[] = [
        { type: 'output', id: 'toolu_task', text: 'test_retry sleeps on the wall clock.', operation_id: ASK },
        { type: 'tool_result', id: 'toolu_task', tool: 'Task', source: 'harness', is_error: false, duration_ms: 8000, kind: 'tool', operation_id: ASK },
    ];
    const asked = started(sent(EMPTY_THREAD, 'sent:1', 'Why do the tests flake?', [], AT), 'sent:1', ASK);

    it('nests its steps and words under the call it works for, never in the turn’s own', () => {
        const working = play(asked, [TASK, ...ITS_WORK]);
        expect(drawn(working).at(-1)).toEqual({ running: null, parts: [['Task … says “test_retry sleeps.” [Grep]']] });
        expect(subagentsOf(working).map((s) => s.id)).toEqual(['toolu_task']);
        const done = play(working, [...ITS_END, { type: 'message', id: '1', role: 'assistant', text: 'test_retry races the clock.', created_at: iso(12), operation_id: ASK }]);
        expect(drawn(done).at(-1)).toEqual({ done: 'test_retry races the clock.', parts: [['Task › test_retry sleeps on the wall clock. says “test_retry sleeps.” [Grep]']] });
        expect(subagentsOf(done)).toEqual([]);
    });

    it('outlives its turn’s reply when it works in the background, until its own end', () => {
        const replied = play(asked, [TASK, { type: 'message', id: '1', role: 'assistant', text: 'A subagent is on it.', created_at: iso(2), operation_id: ASK }]);
        expect(drawn(replied).at(-1)).toEqual({ done: 'A subagent is on it.', parts: [['Task …']] });
        expect(liveTurn(replied)).toBeNull();
        expect(subagentsOf(replied).map((s) => s.id)).toEqual(['toolu_task']);
        const later = play(replied, [...ITS_WORK, ...ITS_END], AT + 20_000);
        expect(stepsOf(turns(later).at(-1)!)[0]).toMatchObject({ id: 'toolu_task', running: false, said: 'test_retry sleeps.', children: [{ id: 'toolu_grep', running: false }] });
        expect(subagentsOf(later)).toEqual([]);
    });
});

describe('a turn that failed', () => {
    const TEXT_TURN: Frame[] = [
        { type: 'message', id: '2', role: 'user', text: 'Draft the reply to Sam', via: 'whatsapp', created_at: iso(0), operation_id: TEXTED },
        { type: 'tool_call', tool: 'gmail__get_thread', arguments: { thread_id: 't-9' }, operation_id: TEXTED },
        { type: 'tool_result', tool: 'gmail__get_thread', is_error: true, result: 'Gmail refused the token.', operation_id: TEXTED },
    ];
    // The stream's failed reply doesn't say why; its operation does.
    const FAILED: Frame = { type: 'message', id: '3', role: 'assistant', text: TURN_FAILED_LINE, created_at: iso(4), failed: true, operation_id: TEXTED };

    it('settles failed on the stream’s failed reply, its step marked an error, and takes why from its operation', () => {
        const failed = play(history(...SETTLED_HISTORY), [...TEXT_TURN, FAILED]);
        expect(drawn(failed).slice(2)).toEqual(['user: Draft the reply to Sam', { failed: TURN_FAILED_LINE, parts: [['gmail__get_thread']] }]);
        expect(stepsOf(turns(failed).at(-1)!)[0].isError).toBe(true);
        expect(turns(failed).at(-1)!.failure).toBeNull();
        const why = failureOf({ type: 'payment_required', reason: 'provider_out_of_funds', integration: 'openrouter', message: 'OpenRouter’s account is out of credit.', billing_url: 'https://openrouter.ai/settings/credits' })!;
        expect(turns(withFailure(failed, TEXTED, why)).at(-1)!.failure).toMatchObject({ reason: 'provider_out_of_funds', billingUrl: 'https://openrouter.ai/settings/credits' });
    });

    it('settles this page’s own turn failed when its operation’s wait fails, with why', () => {
        const asked = play(started(sent(EMPTY_THREAD, 'sent:1', 'Draft the reply to Sam', [], AT), 'sent:1', TEXTED), TEXT_TURN.slice(1));
        const why = failureOf({ type: 'credential_disconnected', reason: 'signed_out', connection: 'claude-plan', integration: 'anthropic', message: 'Your Claude sign-in ended.' })!;
        const failed = withFailure(ended(asked, TEXTED, { status: 'failed', failure: why, at: AT + 4000 }), TEXTED, why);
        expect(turns(failed)[0]).toMatchObject({ status: 'failed', reply: null, failure: { reason: 'signed_out' }, endedAt: AT + 4000 });
        // The stream's failed reply landing after keeps why.
        expect(turns(play(failed, [FAILED]))[0]).toMatchObject({ status: 'failed', id: '3', reply: TURN_FAILED_LINE, failure: { reason: 'signed_out' } });
    });
});

describe('a turn this page stopped', () => {
    const live = play(started(sent(EMPTY_THREAD, 'sent:1', 'Run the full suite', [], AT), 'sent:1', ASK), [
        { type: 'message', id: '0', role: 'user', text: 'Run the full suite', created_at: iso(0), operation_id: ASK },
        { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'pytest' }, kind: 'command', command: 'pytest', operation_id: ASK },
        { type: 'output', id: 'toolu_01', text: '....', operation_id: ASK },
    ]);

    it('ends stopped with nothing left running, and what its harness says after changes nothing', () => {
        const stopped = ended(live, ASK, { status: 'stopped', at: AT + 12_000 });
        expect(drawn(stopped).at(-1)).toEqual({ stopped: null, parts: [['shell › ....']] });
        expect(liveTurn(stopped)).toBeNull();
        const after = play(stopped, [
            { type: 'output', id: 'toolu_01', text: 'F', operation_id: ASK },
            { type: 'tool_result', id: 'toolu_01', tool: 'shell', source: 'harness', is_error: true, kind: 'command', operation_id: ASK },
            { type: 'text', text: 'Stopping.', operation_id: ASK },
        ]);
        expect(after).toEqual(stopped);
        // Its operation's wait, rejecting as canceled after, changes nothing either.
        expect(ended(stopped, ASK, { status: 'stopped', at: AT + 13_000 })).toBe(stopped);
    });
});

describe('what its harness asks a person', () => {
    it('keeps each request by id as it waits and as it ends', () => {
        const ask = { id: 'req-1', kind: 'approval', status: 'pending', action: 'command', title: 'Run rm -rf build/', detail: 'rm -rf build/', options: [{ option_id: 'allow', name: 'Allow', kind: 'allow_once' }], operation_id: ASK, created_at: iso(1) };
        const waiting = play(EMPTY_THREAD, [{ type: 'request', request: ask, operation_id: ASK }]);
        expect(pendingRequests(waiting).map((r) => [r.id, r.title, r.options.map((o) => o.optionId)])).toEqual([['req-1', 'Run rm -rf build/', ['allow']]]);
        const answered = play(waiting, [{ type: 'request', request: { ...ask, status: 'answered', decision: 'allow', answered_at: iso(2) }, operation_id: ASK }]);
        expect(pendingRequests(answered)).toEqual([]);
        expect(answered.requests['req-1']).toMatchObject({ status: 'answered', decision: 'allow' });
    });
});

describe('statuses between and within turns', () => {
    it('marks compaction and lost moments, and a machine downloading its harness', () => {
        const asked = started(sent(EMPTY_THREAD, 'sent:1', 'Go on', [], AT), 'sent:1', ASK);
        const compacting = play(asked, [{ type: 'status', status: 'compacting', operation_id: ASK }]);
        expect(liveTurn(compacting)!.compacting).toBe(AT);
        const downloading = play(compacting, [{ type: 'status', status: 'downloading', text: 'Getting Claude Code ready', downloaded_bytes: 10, total_bytes: 40, operation_id: ASK }]);
        expect(liveTurn(downloading)!.downloading).toEqual({ text: 'Getting Claude Code ready', bytes: 10, total: 40 });
        const after = play(downloading, [
            { type: 'status', status: 'downloaded', operation_id: ASK },
            { type: 'status', status: 'compacted', operation_id: ASK },
            { type: 'status', status: 'events_dropped', count: 3, operation_id: ASK },
            // The conversation's own status changes nothing here.
            { type: 'status', status: 'active' },
        ]);
        expect(liveTurn(after)).toMatchObject({ compacting: null, downloading: null });
        expect(drawn(after).slice(2)).toEqual(['— Context compacted —', '— 3 moments of its work didn’t reach this page —']);
    });

    it('starts a turn begun elsewhere from its compaction, which can be its first moment', () => {
        const texted = play(history(...SETTLED_HISTORY), [
            { type: 'message', id: '9', role: 'user', text: 'Anything new?', via: 'whatsapp', created_at: iso(0), operation_id: TEXTED },
            { type: 'status', status: 'compacting', operation_id: TEXTED },
        ]);
        expect(liveTurn(texted)).toMatchObject({ operationId: TEXTED, compacting: AT + 1000 });
        // A turn already settled isn't started again by a compaction replayed after it.
        const replayed = play(history(...SETTLED_HISTORY), [{ type: 'status', status: 'compacting', operation_id: EARLIER }]);
        expect(liveTurn(replayed)).toBeNull();
    });
});

describe('a file a turn makes', () => {
    const REPORT = { id: 'res-1', name: 'q3-report.pdf', mime_type: 'application/pdf', url: 'https://files.test/q3-report.pdf', size_bytes: 1258291 };

    it('goes on the turn as it’s made, once, and stays when its reply names none; one the person sent stays theirs', () => {
        const asked = started(sent(EMPTY_THREAD, 'sent:1', 'Make the report', [], AT), 'sent:1', ASK);
        const made = play(asked, [
            { type: 'file', role: 'user', file: { ...REPORT, url: 'https://files.test/theirs.pdf' }, operation_id: ASK },
            { type: 'file', role: 'assistant', file: REPORT, operation_id: ASK },
            { type: 'file', role: 'assistant', file: REPORT, operation_id: ASK },
        ]);
        expect(liveTurn(made)!.files.map((f) => f.name)).toEqual(['q3-report.pdf']);
        const replied = play(made, [{ type: 'message', id: '3', role: 'assistant', text: 'Here’s the report.', operation_id: ASK }]);
        expect(turns(replied)[0]).toMatchObject({ status: 'done', reply: 'Here’s the report.' });
        expect(turns(replied)[0].files.map((f) => f.url)).toEqual([REPORT.url]);
    });
});

describe('a dropped stream', () => {
    // A turn at work when the stream dropped: its words and a command still printing.
    const before = play(history(...SETTLED_HISTORY), [
        { type: 'message', id: '2', role: 'user', text: 'Why is the build red?', created_at: iso(0), operation_id: ASK },
        { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'npm test' }, kind: 'command', command: 'npm test', operation_id: ASK },
        { type: 'output', id: 'toolu_01', text: 'PASS a.test.ts\n', operation_id: ASK },
        { type: 'text', id: 'msg_01:0', text: 'Running the tests.', operation_id: ASK },
    ]);
    const RED = { id: '2', role: 'user', text: 'Why is the build red?', created_at: iso(0), operation_id: ASK };

    it('keeps the turn at work through the history read again, and what comes next continues it', () => {
        const again = reread(before, history(...SETTLED_HISTORY, RED).entries);
        expect(drawn(again)).toEqual(drawn(before));
        const next = play(again, [
            { type: 'output', id: 'toolu_01', text: 'FAIL b.test.ts\n', operation_id: ASK },
            { type: 'text', id: 'msg_01:0', text: ' One fails.', operation_id: ASK },
        ]);
        expect(drawn(next).at(-1)).toEqual({ running: null, parts: [['shell … › PASS a.test.ts\nFAIL b.test.ts'], 'Running the tests. One fails.'] });
    });

    it('takes the reply the history holds by then over the turn it kept', () => {
        const again = reread(before, history(...SETTLED_HISTORY, RED, { id: '3', role: 'assistant', text: 'b.test.ts fails.', created_at: iso(9), operation_id: ASK }).entries);
        expect(drawn(again).slice(2)).toEqual(['user: Why is the build red?', { done: 'b.test.ts fails.', parts: [] }]);
    });

    it('keeps a message this page is still sending, with its turn', () => {
        const sending = sent(history(...SETTLED_HISTORY), 'sent:1', 'Hello?', [], AT);
        expect(drawn(reread(sending, history(...SETTLED_HISTORY).entries))).toEqual(drawn(sending));
    });
});

describe('a page opened mid-turn', () => {
    const HELD = [...SETTLED_HISTORY, { id: '2', role: 'user', text: 'Why is the build red?', created_at: iso(0), operation_id: ASK }];

    it('draws the turn at work from what the stream replays, leaving out what it replays of turns already settled', () => {
        const read: Thread = { ...EMPTY_THREAD, entries: [...history(...HELD).entries, runningTurn(ASK, AT)] };
        const replayed = play(read, [
            { type: 'tool_call', tool: 'noclick__api_call', arguments: { operation: 'deploys_list' }, operation_id: EARLIER },
            { type: 'text', text: 'Will do.', operation_id: EARLIER },
            { type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'npm test' }, kind: 'command', command: 'npm test', operation_id: ASK },
            { type: 'text', id: 'msg_01:0', text: 'Running the tests.', operation_id: ASK },
        ]);
        expect(drawn(replayed)).toEqual([
            'user: Keep an eye on the deploys.',
            { done: 'Will do.', parts: [] },
            'user: Why is the build red?',
            { running: null, parts: [['shell …'], 'Running the tests.'] },
        ]);
        // Each call once, however often it's replayed.
        expect(play(replayed, [{ type: 'tool_call', id: 'toolu_01', tool: 'shell', source: 'harness', arguments: { command: 'npm test' }, kind: 'command', command: 'npm test', operation_id: ASK }])).toEqual(replayed);
    });
});

// ── The Chat page's conversation, read the same way ─────────────────────────
// What NoClick's own conversation carries that another agent's rarely does, ported from the Chat page's reducer so
// both pages read one thread: notes (an automation being set up, a space's news), what a message points at, and a turn
// turned down because the account ran out.

describe('a note added to the conversation', () => {
    const setup = { kind: 'mcp', workflow_id: 'wf-1', client: 'codex' };

    it('reads back as a note, its setup drawing the card under it; data that isn’t a setup draws none', () => {
        const thread = history({ role: 'user', text: 'Hi', created_at: iso(0) }, { role: 'note', text: 'Let’s finish setting up Inbox tools.', data: { setup }, created_at: iso(1) }, { role: 'assistant', text: 'Hello.', created_at: iso(2) });
        expect(drawn(thread)).toEqual(['user: Hi', 'note: Let’s finish setting up Inbox tools.', { done: 'Hello.', parts: [] }]);
        expect(thread.entries[1]).toMatchObject({ kind: 'note', setup, space: null });
        expect(history({ role: 'note', text: 'Plan changed.', data: { setup: { kind: 'other' } } }).entries[0]).toMatchObject({ kind: 'note', setup: null });
    });

    it('arriving live is drawn once, even when the page read it back first, and said again for a later ask is new', () => {
        const switched: Frame = { type: 'message', role: 'note', text: 'Inbox tools, set up for Codex.', data: { setup } };
        const opencode: Frame = { ...switched, text: 'Inbox tools, set up for OpenCode.', data: { setup: { ...setup, client: 'opencode' } } };
        let thread = play(EMPTY_THREAD, [switched, switched]);
        expect(drawn(thread)).toEqual(['note: Inbox tools, set up for Codex.']);
        thread = play(thread, [{ type: 'message', role: 'user', text: 'Make it OpenCode', operation_id: 'op-2' }, opencode, { type: 'message', role: 'user', text: 'Codex after all', operation_id: 'op-3' }, switched, switched]);
        expect(thread.entries.flatMap((e) => (e.kind === 'note' ? [e.setup?.client] : []))).toEqual(['codex', 'opencode', 'codex']);
    });

    it('added while a turn is at work, goes before that turn, where the conversation keeps it', () => {
        let thread = started(sent(EMPTY_THREAD, 'k1', 'Can I connect this to Codex instead?', [], AT), 'k1', ASK);
        thread = play(thread, [
            { type: 'tool_call', tool: 'noclick__api_call', arguments: { operation: 'agents_conversations_notes_create' }, operation_id: ASK },
            { type: 'message', role: 'note', text: 'Inbox tools, set up for Codex.', data: { setup } },
            { type: 'message', role: 'assistant', text: 'Switched it to Codex.', operation_id: ASK },
        ]);
        expect(drawn(thread)).toEqual(['sending: Can I connect this to Codex instead?', 'note: Inbox tools, set up for Codex.', { done: 'Switched it to Codex.', parts: [['noclick__api_call']] }]);
    });
});

describe('an app testing line', () => {
    const on = { state: 'on', lead: 'Atlas turned on app testing for this task', detail: 'about $0.44/hour while it works', reason: 'run the checkout tests' };

    it('reads back and arrives live as a note carrying its switch; data that isn’t one carries none', () => {
        const thread = history({ role: 'note', text: `${on.lead} · ${on.detail}`, data: { app_testing: on }, created_at: iso(0) });
        expect(thread.entries[0]).toMatchObject({ kind: 'note', appTesting: on });
        const live = play(EMPTY_THREAD, [{ type: 'message', role: 'note', text: 'Atlas turned app testing off · ran 18 min, $0.13', data: { app_testing: { state: 'off', lead: 'Atlas turned app testing off', detail: 'ran 18 min, $0.13' } } }]);
        expect(live.entries[0]).toMatchObject({ kind: 'note', appTesting: { state: 'off', lead: 'Atlas turned app testing off', detail: 'ran 18 min, $0.13', reason: null } });
        expect(history({ role: 'note', text: 'x', data: { app_testing: { state: 'sideways', lead: 'x' } } }).entries[0]).not.toHaveProperty('appTesting');
    });
});

describe('a workflow’s Approval step', () => {
    const asked = { id: 'wa_1', workflow_id: 'wf_1', workflow_name: 'Invoices', title: 'Pay invoice 1042' };

    it('reads back and arrives live as a note naming the step its card answers; data that isn’t one names none', () => {
        const note = { kind: 'note', workflowApproval: { id: 'wa_1', workflowId: 'wf_1', workflowName: 'Invoices', title: 'Pay invoice 1042' } };
        const text = 'Invoices is waiting for your approval: Pay invoice 1042.';
        expect(history({ role: 'note', text, data: { workflow_approval: asked }, created_at: iso(0) }).entries[0]).toMatchObject(note);
        expect(play(EMPTY_THREAD, [{ type: 'message', role: 'note', text, data: { workflow_approval: asked } }]).entries[0]).toMatchObject(note);
        const untitled = history({ role: 'note', text: 'x', data: { workflow_approval: { id: 'wa_2', workflow_id: 'wf_1' } } }).entries[0];
        expect(untitled).toMatchObject({ workflowApproval: { id: 'wa_2', workflowId: 'wf_1', workflowName: 'Your workflow', title: null } });
        expect(history({ role: 'note', text: 'x', data: { workflow_approval: { id: 'wa_3' } } }).entries[0]).not.toHaveProperty('workflowApproval');
    });
});

describe('a model switch’s line', () => {
    const switched = {
        state: 'switched', lead: 'Claude-work used up. Now on your Claude plan (claude-personal) until 3:20 PM', detail: null,
        from: 'claude-work', to: 'claude-personal', to_name: 'claude-personal', harness_from: 'claude_code', harness_to: 'claude_code', model_from: 'claude-opus-5-5', model_to: 'claude-opus-5-5',
        pays: 'plan', reason: 'limit', by: { type: 'noclick', name: 'NoClick' }, grant: null, window: 'five_hour', resets_at: '2026-11-17T15:20:00+00:00',
    };

    it('reads back and arrives live as a note carrying its move, the owner’s words where a grant cites them', () => {
        const thread = history({ role: 'note', text: switched.lead, data: { switch_model: switched }, created_at: iso(0) });
        expect(thread.entries[0]).toMatchObject({ kind: 'note', modelSwitch: { state: 'switched', from: 'claude-work', to: 'claude-personal', toName: 'claude-personal', reason: 'limit', by: 'noclick', grant: null, resetsAt: new Date('2026-11-17T15:20:00Z') } });
        const cited = { ...switched, to: 'openai', reason: 'out of plans', by: { type: 'agent', id: 'a1', name: 'Atlas' }, resets_at: null,
            grant: { id: 'g1', scope: 'standing', source: 'cited', evidence: { where: 'channel', channel_id: 'ch-usage', channel_name: 'usage', message_id: 'msg-9', at: '2026-11-17T15:10:00+00:00', quote: 'use the openai key from now on', link: 'https://noclick.com/dashboard?tab=work&channel=ch-usage' } } };
        const live = play(EMPTY_THREAD, [{ type: 'message', role: 'note', text: 'Now on your openai key.', data: { switch_model: cited } }]);
        expect(live.entries[0]).toMatchObject({ kind: 'note', modelSwitch: { by: 'agent', resetsAt: null, grant: { source: 'cited', scope: 'standing', evidence: { where: 'channel', channelId: 'ch-usage', channelName: 'usage', messageId: 'msg-9', at: new Date('2026-11-17T15:10:00Z') } } } });
    });

    it('reads a wait’s reset from its until, and data that isn’t a move carries none', () => {
        const waiting = history({ role: 'note', text: 'Claude-work is out until 3:20 PM · Atlas picks this up then', data: { switch_model: { state: 'waiting', lead: 'Claude-work is out until 3:20 PM', detail: 'Atlas picks this up then', until: '2026-11-17T15:20:00+00:00', connection: 'claude-work', picks_up: true } }, created_at: iso(0) });
        expect(waiting.entries[0]).toMatchObject({ kind: 'note', modelSwitch: { state: 'waiting', connection: 'claude-work', picksUp: true, resetsAt: new Date('2026-11-17T15:20:00Z') } });
        expect(history({ role: 'note', text: 'x', data: { switch_model: { state: 'sideways', lead: 'x' } } }).entries[0]).not.toHaveProperty('modelSwitch');
    });

    it('takes a turn its plan’s limit stopped as a failure of its own, which the line says', () => {
        const why = failureOf({ type: 'plan_limit_reached', reason: 'plan_limit', connection: 'claude-work', connection_name: 'claude-work', integration: 'anthropic', message: 'Your Claude plan (claude-work) is used up until 3:20 PM.', window: 'five_hour', resets_at: '2026-11-17T15:20:00+00:00', then: { waiting_until: '2026-11-17T15:20:00+00:00', picks_up: true } });
        expect(why).toMatchObject({ reason: 'plan_limit', connection: 'claude-work' });
        const thread = history({ role: 'user', text: 'Fix the flaky test', created_at: iso(0), operation_id: ASK }, { role: 'assistant', text: TURN_FAILED_LINE, failed: true, failure: { type: 'plan_limit_reached', reason: 'plan_limit', connection: 'claude-work' }, created_at: iso(5), operation_id: ASK });
        expect(turns(thread)[0]).toMatchObject({ status: 'failed', failure: { reason: 'plan_limit' } });
    });
});

describe('a failure a line already says', () => {
    const limited = (op: string, at: number) => ({ role: 'assistant', text: TURN_FAILED_LINE, failed: true, failure: { type: 'plan_limit_reached', reason: 'plan_limit', connection: 'claude-work', message: 'Your Claude plan (claude-work) is used up until 3:20 PM.' }, created_at: iso(at), operation_id: op });
    const moved = (at: number, state = 'switched') => ({ role: 'note', text: 'Moved', data: { switch_model: { state, lead: 'Moved', to: 'claude-personal' } }, created_at: iso(at) });

    it('is told by a move or a wait beside it, on either side of its reply, never by one after the next message or a return', () => {
        const thread = history(
            { role: 'user', text: 'One', created_at: iso(0), operation_id: ASK },
            moved(1),
            limited(ASK, 2),
            { role: 'user', text: 'Two', created_at: iso(10), operation_id: WAKE },
            limited(WAKE, 11),
            { role: 'user', text: 'Three', created_at: iso(20), operation_id: TEXTED },
            moved(21, 'back_on'),
            limited(TEXTED, 22),
            moved(23, 'waiting'),
        );
        const keys = turns(thread).map((t) => t.key);
        expect([...failuresTold(thread.entries)]).toEqual([keys[0], keys[2]]);
    });
});

describe('a space’s news', () => {
    const LAUNCH = { workspace_id: 'ws-launch', name: 'Launch', label: 'NoClick · Launch' };

    it('reads back as a note from the space; a notification from no space stays a reply', () => {
        const thread = history({ role: 'assistant', text: 'Priya asked for your sign-off.', notification: true, space: LAUNCH, created_at: iso(0) }, { role: 'assistant', text: 'Done.', notification: true, created_at: iso(1) });
        expect(thread.entries[0]).toMatchObject({ kind: 'note', text: 'Priya asked for your sign-off.', space: { id: 'ws-launch', label: 'NoClick · Launch' }, setup: null });
        expect(thread.entries[1]).toMatchObject({ kind: 'turn', reply: 'Done.' });
    });

    it('arrives live as a note of its own, never as a reply of the turn at work here, and once', () => {
        const news: Frame = { type: 'message', role: 'assistant', text: 'Priya asked for your sign-off.', operation_id: 'op-background', notification: true, space: LAUNCH };
        let thread = sent(EMPTY_THREAD, 'k1', 'what’s new?', [], AT);
        thread = play(thread, [{ type: 'text', text: 'Let me look', operation_id: ASK }, news, { ...news, operation_id: null }]);
        expect(drawn(thread)).toEqual(['sending: what’s new?', 'note: Priya asked for your sign-off.', { running: null, parts: ['Let me look'] }]);
    });
});

describe('what a message points at', () => {
    const refs = [
        { kind: 'automation' as const, id: 'wf-1', label: 'Morning brief' },
        { kind: 'account' as const, id: 'cred-9', label: 'ops@acme.test' },
        { kind: 'account' as const, id: 'connection:conn-4', label: 'Notion · maya@notion.test' },
    ];

    it('names each by the id the platform API looks it up by: a named connection by its connection id', () => {
        expect(composeMessage('Use these', refs, false)).toBe(
            'Use these\n\n(About the automation “Morning brief” (workflow wf-1), the account “ops@acme.test” (credential:cred-9) and the account “Notion · maya@notion.test” (connection conn-4).)'
        );
    });

    it('reads back as the words and their chips, the line naming them taken off; files alone show no words', () => {
        const thread = history({ role: 'user', text: composeMessage('Why did this fail?', refs, false), created_at: iso(0) }, { role: 'user', text: composeMessage('', [], true), created_at: iso(1) });
        expect(thread.entries[0]).toMatchObject({ kind: 'user', text: 'Why did this fail?', references: refs });
        expect(thread.entries[1]).toMatchObject({ kind: 'user', text: '', references: [] });
    });

    it('matches a message this page sent with its chips to the one the conversation shows back', () => {
        let thread = sent(EMPTY_THREAD, 'k1', 'Why did this fail?', [], AT, { references: refs });
        thread = play(thread, [{ type: 'message', id: 'm1', role: 'user', text: composeMessage('Why did this fail?', refs, false), operation_id: ASK }]);
        expect(drawn(thread)).toEqual(['user: Why did this fail?', { running: null, parts: [] }]);
        expect(thread.entries[0]).toMatchObject({ id: 'm1', pending: false, references: refs });
    });
});

describe('a turn turned down because the account ran out', () => {
    const outOfFunds = { said: 'You’re out of funds, so I can’t start that.', invite_url: 'https://noclick.com/i/abc' };

    it('reads back with what its card draws, from the reply the conversation kept in its place', () => {
        const thread = history({ role: 'user', text: 'Build me a site', created_at: iso(0) }, { role: 'assistant', text: outOfFunds.said, out_of_funds: outOfFunds, created_at: iso(1) });
        expect(turns(thread)[0]).toMatchObject({ reply: outOfFunds.said, outOfFunds, status: 'done' });
    });

    it('ends with the refusal as its reply when the send was turned down', () => {
        const thread = ended(started(sent(EMPTY_THREAD, 'k1', 'Build me a site', [], AT), 'k1', ASK), ASK, { status: 'done', reply: outOfFunds.said, outOfFunds, at: AT });
        expect(turns(thread)[0]).toMatchObject({ reply: outOfFunds.said, outOfFunds, status: 'done' });
    });
});

describe('a turn stopped before its reply', () => {
    it('keeps what it said on the way as its reply, so stopping never takes its words away', () => {
        let thread = started(sent(EMPTY_THREAD, 'k1', 'Speed up my site', [], AT), 'k1', ASK);
        thread = play(thread, [{ type: 'text', text: 'Looking at your sites.', operation_id: ASK }]);
        thread = ended(thread, ASK, { status: 'stopped', at: AT + 5000 });
        expect(turns(thread)[0]).toMatchObject({ status: 'stopped', reply: 'Looking at your sites.' });
        // One that said nothing has nothing to keep.
        const quiet = ended(started(sent(EMPTY_THREAD, 'k2', 'Hi', [], AT), 'k2', WAKE), WAKE, { status: 'stopped', at: AT });
        expect(turns(quiet)[0].reply).toBeNull();
    });
});
