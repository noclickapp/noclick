// A running turn's pace, as Claude Code's CLI shows one ("14s · ↓ 988 tokens · thought for 10s"), read off the turn's
// `progress` moments alone (the one shape every harness's turn tells it in), through the SDK's own parser, as the
// working line draws it.
import { describe, expect, it } from 'vitest';
import type { AgentEvent, JsonObject } from 'noclick';
import { toAgentEvent } from '@/sdk/source';
import { applyEvent, EMPTY_THREAD, ended, paceOf, thoughtMs, type Thread, type TurnEntry } from './thread';
import { paceLine, tokenCount } from '@/screens/work/conversation/Activity';

const AT = Date.parse('2026-11-24T10:10:22Z');
const OP = '9d9fc43f-3849-4eb3-af88-47f22ebb10de';
type Frame = JsonObject & { type: string };

const heard = (frame: Frame): AgentEvent => {
    const { type, ...data } = frame;
    return toAgentEvent(type, data);
};
const at = (s: number) => AT + s * 1000;

/** The thread after each frame, heard at its own second after `AT`. */
const play = (frames: [number, Frame][]): Thread => frames.reduce((t, [s, f]) => applyEvent(t, heard(f), at(s)), EMPTY_THREAD);
const turnOf = (thread: Thread) => thread.entries.find((e): e is TurnEntry => e.kind === 'turn')!;

const START: [number, Frame][] = [
    [0, { type: 'reasoning', text: 'Checking the two sign-ins.', operation_id: OP }],
    [0, { type: 'progress', thinking: true, operation_id: OP }],
];

describe("a running turn's pace, from its progress moments", () => {
    it('times its thinking from when it started until it ended', () => {
        const thinking = play(START);
        expect(paceLine(paceOf(turnOf(thinking)), at(6))).toBe('thinking 6s');
        const done = play([...START, [10, { type: 'progress', thinking: false, operation_id: OP }]]);
        expect(paceOf(turnOf(done))).toMatchObject({ thinkingSince: null, thinkingMs: 10_000 });
        expect(paceLine(paceOf(turnOf(done)), at(20))).toBe('thought for 10s');
    });

    it('takes the moment its daemon heard over when it reached the page', () => {
        const thread = play([[9, { type: 'progress', thinking: true, at: at(3), operation_id: OP }]]);
        expect(thoughtMs(paceOf(turnOf(thread)), at(9))).toBe(6000);
    });

    it('shows the tokens its progress says, estimated or reported', () => {
        const counted = play([...START, [2, { type: 'progress', output_tokens: 140, estimated: true, operation_id: OP }]]);
        expect(paceLine(paceOf(turnOf(counted)), at(4))).toBe('↓ 140 tokens · thinking 4s');
        const reported = applyEvent(counted, heard({ type: 'progress', output_tokens: 988, estimated: false, usage: { input_tokens: 312_000, cached_tokens: 300_000, output_tokens: 988 }, operation_id: OP }), at(5));
        expect(paceOf(turnOf(reported))).toMatchObject({ tokens: 988, estimated: false, inputTokens: 312_000 });
        expect(paceLine(paceOf(turnOf(reported)), at(6))).toBe('↑ 312k ↓ 988 tokens · thinking 6s');
    });

    it('is at work from the moment its runner starts it, before its message or a word comes, its message drawn first', () => {
        const working: Frame = { type: 'progress', working: true, stage: 'delivering', started_at: at(0), elapsed_ms: 0, operation_id: OP };
        const thread = play([
            [0, working],
            [2, { type: 'message', role: 'user', id: '4', text: 'Reply with only the word pong.', operation_id: OP }],
        ]);
        expect(thread.entries.map((e) => [e.kind, e.kind === 'turn' && e.status])).toEqual([
            ['user', false],
            ['turn', 'running'],
        ]);
    });

    it('reads nothing of its words or calls themselves', () => {
        const thread = play([[0, { type: 'text', text: 'x'.repeat(4000), operation_id: OP }], [1, { type: 'tool_call', id: 't1', tool: 'shell', source: 'harness', command: 'ls', operation_id: OP }]]);
        expect(paceLine(paceOf(turnOf(thread)), at(5))).toBe('');
    });

    it('stops its thinking clock when it ends', () => {
        const done = ended(play(START), OP, { status: 'done', reply: 'Hi', at: at(7) });
        expect(paceOf(turnOf(done))).toMatchObject({ thinkingSince: null, thinkingMs: 7000 });
    });

    it('counts tokens as the CLI does', () => {
        expect([tokenCount(988), tokenCount(1200), tokenCount(1000), tokenCount(34_567)]).toEqual(['988', '1.2k', '1k', '35k']);
    });
});
