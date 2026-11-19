// The cards under an agent's turns: the chat's cards for a call (a purchase held for a yes, an account to connect, a
// build on its canvas, a long action followed until it settles), read from the turn's calls of NoClick's own tools and
// what its stream announced of them, so a card looks and acts the same in Work and on the Chat page.
import { useMemo, type ReactNode } from 'react';
import { announcedResult } from '@/lib/agentThread/messages';
import type { ThreadJobs } from '@/lib/threadJobs';
import { CardsProvider, TurnCards } from '@/screens/chat/cards/toolCards';
import { TurnAskedProvider } from '@/screens/chat/cards/toolCardRegistry';
import { parsePartialJson } from '@/lib/partialJson';
import type { CoordinatorToolCall, JsonObject } from '@/lib/toolCalls';
import { stepsOf, type Step, type Thread, type TurnEntry } from '@/lib/agentThread/thread';

// NoClick's own tools as an agent names them: directly, or through a coding harness's MCP server.
const PREFIX = /^(mcp__(?:noclick|nc)__)?(noclick__)?/;

const asObject = (value: unknown): JsonObject | undefined => (value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : undefined);

/** A call's answer as its card reads it: the object it answered (or the JSON text it was passed on as), its error as a
 *  failed answer reads. */
function answerOf(step: Step): JsonObject | undefined {
    if (step.running || step.result === null || step.result === undefined) return undefined;
    if (step.isError) return { error: typeof step.result === 'string' ? step.result : JSON.stringify(step.result) };
    return typeof step.result === 'string' ? asObject(parsePartialJson(step.result)) : asObject(step.result);
}

/** A step as the card registry reads a call: its tool by NoClick's own name, what it was given, what it answered. */
export function cardCallOf(step: Step): CoordinatorToolCall | null {
    if (step.kind !== 'tool') return null;
    return { id: step.id, tool: step.tool.replace(PREFIX, ''), args: step.arguments, result: answerOf(step), running: step.running, startedAt: step.at };
}

/** A turn's calls for its cards, and what its stream announced that no call's answer names (an approval held behind
 *  a call that answered something else). */
export function turnCalls(turn: TurnEntry): CoordinatorToolCall[] {
    const calls = stepsOf(turn).flatMap((s) => cardCallOf(s) ?? []);
    const named = calls.map((c) => JSON.stringify(c.result ?? {})).join('\n');
    const announced = turn.announced
        .filter((a) => typeof a.id === 'string' && !named.includes(a.id))
        .map((a): CoordinatorToolCall => ({ id: `${turn.key}:announced:${String(a.id)}`, tool: String(a.kind), args: {}, result: announcedResult(a), running: false, startedAt: turn.startedAt }));
    return [...calls, ...announced];
}

/** What the cards under the thread's turns read: the work they started, followed as `follow` follows it. */
export function ThreadCards({ thread, follow, children }: { thread: Thread; follow: ThreadJobs; children: ReactNode }) {
    const cards = useMemo(() => thread.entries.flatMap((e) => (e.kind === 'turn' ? turnCalls(e) : [])), [thread]);
    const jobs = follow(cards, thread.entries.length);
    return (
        <CardsProvider cards={cards} jobs={jobs} moved={thread.entries.length}>
            {children}
        </CardsProvider>
    );
}

/** A turn's cards, under what it said; `asked`, what the person asked in the message it answers. */
export function TurnCardsOf({ turn, asked }: { turn: TurnEntry; asked: string | null }) {
    const calls = useMemo(() => turnCalls(turn), [turn]);
    if (!calls.length) return null;
    return (
        <TurnAskedProvider value={asked}>
            <TurnCards calls={calls} text={turn.reply ?? undefined} />
        </TurnAskedProvider>
    );
}
