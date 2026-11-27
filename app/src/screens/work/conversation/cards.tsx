// The cards under an agent's turns: the chat's cards for a call (a purchase held for a yes, an account to connect, a
// build on its canvas, a long action followed until it settles), read from the turn's calls of NoClick's own tools and
// what its stream announced of them, so a card looks and acts the same in Work and on the Chat page. A connect link a
// reply hands over is an account to connect too, whatever made it: an agent on a coding harness may make the
// connection from its own shell, calling the API, which no tool call records.
import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from 'react';
import { Connection, type NoClick } from 'noclick';
import { announcedResult } from '@/lib/agentThread/messages';
import type { ThreadJobs } from '@/lib/threadJobs';
import { useProvidedClient } from '@/sdk/client';
import { connectLinkOf, handedLinkTokens, provideToken } from '@/screens/chat/cards/cardMatchers';
import { CardsProvider, TurnCards } from '@/screens/chat/cards/toolCards';
import { connectAskOf, TurnAskedProvider } from '@/screens/chat/cards/toolCardRegistry';
import { parsePartialJson } from '@/lib/partialJson';
import { obj, str, type CoordinatorToolCall, type JsonObject } from '@/lib/toolCalls';
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

/** The account's own pending connections whose connect link a reply hands over, as /v1 lists them, by the link's
 *  token, each with the turn whose reply first handed it over: the one that draws its card. */
export type HandedLinks = ReadonlyMap<string, { connection: JsonObject; turn: string }>;

const NO_LINKS: HandedLinks = new Map();
const HandedLinksContext = createContext<HandedLinks>(NO_LINKS);

/** The connect link a call made or read, by its token. */
const carriedToken = (call: CoordinatorToolCall): string | undefined => provideToken(connectLinkOf(call)?.url ?? connectAskOf(call)?.url);

/** Each connect link the thread hands over, by its token, with the turn that first did: by a call (whose card draws
 *  it), or by a settled reply; the links a reply hands over first are the ones read and drawn for it. */
function firstHanded(thread: Thread): Map<string, { turn: string; byReply: boolean }> {
    const first = new Map<string, { turn: string; byReply: boolean }>();
    for (const e of thread.entries) {
        if (e.kind !== 'turn') continue;
        for (const step of stepsOf(e)) {
            const call = cardCallOf(step);
            const token = call ? carriedToken(call) : undefined;
            if (token && !first.has(token)) first.set(token, { turn: e.key, byReply: false });
        }
        if (e.status === 'running') continue;
        for (const token of handedLinkTokens(e.reply)) if (!first.has(token)) first.set(token, { turn: e.key, byReply: true });
    }
    return first;
}

/** The connect links the turn's reply first handed over, each as the call that made its connection would have
 *  answered it: so its card connects it right there, and the link's operation is followed. */
function handedCalls(turn: TurnEntry, handed: HandedLinks): CoordinatorToolCall[] {
    return [...handed].flatMap(([token, { connection, turn: key }]): CoordinatorToolCall[] => {
        if (key !== turn.key) return [];
        const result = { status: 'awaiting_human', operation_id: str(obj(connection, 'connect_link'), 'operation_id'), response: connection };
        return [{ id: `${turn.key}:handed:${token}`, tool: 'connect_link', args: {}, result, running: false, startedAt: turn.startedAt }];
    });
}

/** A turn's calls for its cards, the connect links its reply hands over (`handed`), and what its stream announced that
 *  no call's answer names (an approval held behind a call that answered something else). */
export function turnCalls(turn: TurnEntry, handed: HandedLinks = NO_LINKS): CoordinatorToolCall[] {
    const calls = [...stepsOf(turn).flatMap((s) => cardCallOf(s) ?? []), ...handedCalls(turn, handed)];
    const named = calls.map((c) => JSON.stringify(c.result ?? {})).join('\n');
    const announced = turn.announced
        .filter((a) => typeof a.id === 'string' && !named.includes(a.id))
        .map((a): CoordinatorToolCall => ({ id: `${turn.key}:announced:${String(a.id)}`, tool: String(a.kind), args: {}, result: announcedResult(a), running: false, startedAt: turn.startedAt }));
    return [...calls, ...announced];
}

// What each client found for the links replies hand over, by token: the account's own pending connection a link
// fills, or null where it fills none (another person's request, one connected or replaced already). Kept for the
// page's life, so a card connected right there stays drawn once the connection no longer lists its link. `found` is
// replaced, never changed, so a view reading it hears each read land.
interface HandedStore {
    found: ReadonlyMap<string, JsonObject | null>;
    asking: Set<string>;
    heard: Set<() => void>;
}

const storesByClient = new WeakMap<NoClick, HandedStore>();
const NO_STORE: HandedStore = { found: new Map(), asking: new Set(), heard: new Set() };

function storeOf(client: NoClick | null): HandedStore {
    if (!client) return NO_STORE;
    let store = storesByClient.get(client);
    if (!store) storesByClient.set(client, (store = { found: new Map(), asking: new Set(), heard: new Set() }));
    return store;
}

/** Reads which of `tokens` open the links of the account's own pending connections: one page of its connections,
 *  newest first, where a connection a turn just made or read waits. One that couldn't be read is asked again when the
 *  thread next moves. */
async function readHanded(client: NoClick, store: HandedStore, tokens: readonly string[]): Promise<void> {
    tokens.forEach((t) => store.asking.add(t));
    try {
        const page = await Connection.listPage({ client, origin: 'api', limit: 100 });
        const found = new Map(store.found);
        tokens.forEach((t) => found.set(t, null));
        for (const connection of page.data) {
            const token = provideToken(str(obj(connection.raw, 'connect_link'), 'url'));
            if (token && tokens.includes(token)) found.set(token, connection.raw);
        }
        store.found = found;
        store.heard.forEach((hear) => hear());
    } catch (error) {
        console.warn('[chat] the connections a reply links to didn’t read:', error);
    } finally {
        tokens.forEach((t) => store.asking.delete(t));
    }
}

/** The connections whose connect link the thread's settled replies hand over, read once per link. */
export function useHandedLinks(thread: Thread): HandedLinks {
    const client = useProvidedClient();
    const store = storeOf(client);
    const first = useMemo(() => [...firstHanded(thread)].filter(([, f]) => f.byReply), [thread]);
    const tokens = useMemo(() => first.map(([token]) => token), [first]);
    const subscribe = useCallback(
        (hear: () => void) => {
            store.heard.add(hear);
            return () => void store.heard.delete(hear);
        },
        [store]
    );
    const found = useSyncExternalStore(subscribe, () => store.found);
    useEffect(() => {
        const asked = tokens.filter((t) => !store.found.has(t) && !store.asking.has(t));
        if (client && asked.length) void readHanded(client, store, asked);
    }, [client, store, tokens]);
    return useMemo(() => {
        const handed = new Map(
            first.flatMap(([token, { turn }]) => {
                const connection = found.get(token);
                return connection ? [[token, { connection, turn }] as const] : [];
            })
        );
        return handed.size ? handed : NO_LINKS;
    }, [found, first]);
}

/** What the cards under the thread's turns read: the work they started, followed as `follow` follows it, and the
 *  connect links their replies hand over. */
export function ThreadCards({ thread, follow, children }: { thread: Thread; follow: ThreadJobs; children: ReactNode }) {
    const handed = useHandedLinks(thread);
    const cards = useMemo(() => thread.entries.flatMap((e) => (e.kind === 'turn' ? turnCalls(e, handed) : [])), [thread, handed]);
    const jobs = follow(cards, thread.entries.length);
    return (
        <HandedLinksProvider value={handed}>
            <CardsProvider cards={cards} jobs={jobs} moved={thread.entries.length}>
                {children}
            </CardsProvider>
        </HandedLinksProvider>
    );
}

/** Gives the turns' cards below the connect links the thread's replies hand over (`useHandedLinks`). */
export const HandedLinksProvider = HandedLinksContext.Provider;

/** A turn's cards, under what it said; `asked`, what the person asked in the message it answers. */
export function TurnCardsOf({ turn, asked }: { turn: TurnEntry; asked: string | null }) {
    const handed = useContext(HandedLinksContext);
    const calls = useMemo(() => turnCalls(turn, handed), [turn, handed]);
    if (!calls.length) return null;
    return (
        <TurnAskedProvider value={asked}>
            <TurnCards calls={calls} text={turn.reply ?? undefined} />
        </TurnAskedProvider>
    );
}
