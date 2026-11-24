// One agent conversation, live, for every page that shows one (Work's conversations, the Chat page's): its history
// read through the SDK, then its moments followed with agent.watch (a dropped stream is taken up again and the history
// read afresh), what its harness asks a person, its commands and its settings. Sends go as messages or harness
// commands, steering the turn under way or queued behind it; Stop cancels the turn's operation, which stops the
// harness. A turn NoClick turns down because the account ran out ends on its refusal (what its card draws); one that
// fails for no reason a person can act on, on the failure line its history keeps.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Agent, APIConnectionError, NoClickError, NotFound, Operation, OperationFailed, OperationTimeout, PaymentRequired, RequestTimeout, ServerError, UpstreamError, type AgentCommands, type AgentEvent, type AgentStep, type Attachment, type ConversationChanges, type ConversationSettings, type HarnessRequest, type Message, type MessageSubagent, type NoClick, type RequestDecision } from 'noclick';
import { peekV1, readV1 } from '@/sdk/useV1';
import { useReportHeld } from '@/sdk/held';
import { operationFollower, PushedOperations } from '@/sdk/useFollowedOperations';
import type { ThreadJobs } from '@/lib/threadJobs';
import type { ChatReference } from '@/lib/agentThread/messages';
import { composeMessage, outOfFundsOf, TURN_FAILED_LINE } from '@/lib/agentThread/messages';
import { watchConversation } from '@/lib/agentThread/watch';
import { useWorkClient } from '../client';
import { rereadAccounts } from '../newAgent/catalog';
import { costlyModelOf, refusedForFunds, useFundsThenSwitch } from '../newAgent/funds';
import { applyEvent, closed, EMPTY_THREAD, ended, failureOf, fromHistory, liveTurn, refused, reread, runningTurn, sent, started, turnsOver, unanswered, unsent, withFailure, type Failure, type Thread } from '@/lib/agentThread/thread';

/** What a conversation says when its agent isn't there (or isn't the reader's to see). */
export const AGENT_GONE = 'This agent is gone, or you can’t see it.';

/** An agent turn's reply words, from its operation's result. */
const replyText = (result: unknown): string | null => {
    const text = result && typeof result === 'object' ? (result as { text?: unknown }).text : null;
    return typeof text === 'string' ? text : null;
};

// A turn that failed on NoClick's side or a service's says nothing a person can act on.
const UNSAID = [OperationFailed, OperationTimeout, RequestTimeout, ServerError, UpstreamError, APIConnectionError];

const reasonOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'NoClick couldn’t answer that.');

/** A failed operation's error, where its model connection was refused. */
const failureOfError = (error: unknown): Failure | null => (error instanceof NoClickError ? failureOf({ ...error.details, type: error.type, message: error.message, next_step: error.nextStep }) : null);

/** Why a turn the stream settled as failed failed, from its operation (the stream's message doesn't carry it). */
async function failureOfOperation(client: NoClick, operationId: string): Promise<Failure | null> {
    const op = await Operation.fromId(operationId, { client }).hydrate();
    return failureOfError(op.error);
}

/** A message sent behind the turn under way, until its own turn starts. */
export interface Queued {
    key: string;
    text: string;
    command: { name: string; arguments?: string } | null;
    operationId: string | null;
}

export interface SendInput {
    text: string;
    files?: Attachment[];
    /** What the words point at (an automation, an account): named in a line the message ends with, drawn as chips. */
    references?: ChatReference[];
    command?: { name: string; arguments?: string };
    /** While a turn runs: into it, or after it. */
    delivery?: 'steer' | 'queue';
}

/** NoClick's refusal of a turn for lack of money, as the turn ends on it: its words, and what its card draws when the
 *  account ran out. */
export function refusalOf(error: PaymentRequired): { reply: string; outOfFunds: Record<string, unknown> | null } {
    const outOfFunds = outOfFundsOf(error.details.out_of_funds) ?? null;
    return { reply: outOfFunds ? String(outOfFunds.said) : error.message, outOfFunds };
}

export interface ConversationState {
    agent: Agent;
    /** The agent's own fields, once read (its name, harness, model). */
    ready: boolean;
    loadError: string | null;
    thread: Thread;
    working: boolean;
    queued: Queued[];
    commands: AgentCommands | null;
    settings: ConversationSettings | null;
    send: (input: SendInput) => Promise<boolean>;
    /** Tells one of its harness's subagents something: it joins the turn under way (or, with that turn over, starts
     *  one), the main session passing it on. Drawn at once, as the person's, for that subagent. */
    tellSubagent: (subagent: MessageSubagent, text: string) => Promise<boolean>;
    stop: () => Promise<void>;
    unqueue: (key: string) => Promise<Queued | null>;
    answer: (request: HarnessRequest, decision: RequestDecision, options?: { note?: string; answers?: Record<string, string | string[]> }) => Promise<void>;
    updateSettings: (patch: ConversationChanges) => Promise<void>;
    /** Add funds, opened by a change refused for want of them (a costly model on NoClick's key): shown by the view. */
    fundsDialog: ReactNode;
    /** Reads its settings again: the accounts it runs on, after their connection changed. */
    rereadSettings: () => void;
    retry: () => void;
    error: string | null;
    clearError: () => void;
    /** How the cards under its turns follow the work they started: what the stream says of each, then its own wait. */
    followJobs: ThreadJobs;
    /** Reads its history again (a note just added to it), keeping a turn at work. */
    rereadHistory: () => Promise<void>;
}

export interface AgentThreadOptions {
    /** What names its thread in this session's reads (an agent's id, or a name before it's found). */
    key: string;
    /** Its history read beside the agent's lookup, by a name the agent goes by, for a page that can draw it before the
     *  lookup answers (null where it can't be read that way). */
    readFirst?: () => Promise<Message[] | null>;
    /** What its logs call it. */
    label?: string;
    /** Hears each of its live events, as it arrives (what a page reads beside the thread follows them). */
    onEvent?: (event: AgentEvent) => void;
}

/** What a conversation showed when it was last open this session (per client, so no view sees another's): a revisit
 *  paints it at once, then reads it again and follows it from there. */
interface Kept {
    thread: Thread;
    commands: AgentCommands | null;
    settings: ConversationSettings | null;
}
const KEPT_MAX = 40;
const keptByClient = new WeakMap<NoClick, Map<string, Kept>>();

function keptFor(client: NoClick): Map<string, Kept> {
    let kept = keptByClient.get(client);
    if (!kept) keptByClient.set(client, (kept = new Map()));
    return kept;
}

function keep(client: NoClick, key: string, value: Kept): void {
    const kept = keptFor(client);
    kept.delete(key);
    kept.set(key, value);
    if (kept.size > KEPT_MAX) kept.delete(kept.keys().next().value!);
}

/** Where a conversation's thread is read, once for whoever shows it or reads it ahead (Work's `prefetchConversation`). */
export const threadKey = (key: string, conversation: string) => `work:agent:${key}:thread:${conversation}`;

/** A conversation's thread as the server holds it: its history, what its harness asks, and the turn it may still run. */
export async function readThread(client: NoClick, agent: Agent, conversation: string): Promise<Thread> {
    const [history, pending] = await Promise.all([agent.history(conversation), agent.requests(conversation, { status: 'pending' })]);
    let entries = fromHistory(history);
    // The last message nothing has answered: its turn may still be running.
    const open = unanswered(entries);
    if (open?.operationId) {
        const op = await Operation.fromId(open.operationId, { client }).hydrate();
        if (!op.done) entries = [...entries, runningTurn(open.operationId, op.startedAt?.getTime() ?? open.at)];
    }
    return { entries, requests: Object.fromEntries(pending.map((r) => [r.id, r])) };
}

/** How one of `caller`'s conversations is set (its model, effort, account, and what its harness offers of each): read
 *  once `loaded` answers (null while the agent isn't found yet), never blocking anything, again on `rereadSettings`;
 *  changed with its PATCH, whose answer is what shows. A refused change keeps what was shown and says why (`onError`),
 *  but one refused for want of funds opens Add funds (`fundsDialog`), and is made by itself once they land. */
export function useConversationSettings(caller: Agent, loaded: Promise<unknown> | null, conversation: string, seed: ConversationSettings | null, onError: (reason: string) => void, key: string = caller.id) {
    const [settings, setSettings] = useState<ConversationSettings | null>(seed);
    const [read, setRead] = useState(0);
    const apply = useCallback(async (patch: ConversationChanges) => setSettings(await caller.conversation(conversation).update(patch)), [caller, conversation]);
    const adding = useFundsThenSwitch<ConversationChanges>(`settings:${key}:${conversation}`, apply);
    useEffect(() => {
        if (!loaded) return;
        let gone = false;
        loaded
            .then(() => caller.conversation(conversation).settings())
            .then((s) => !gone && setSettings(s), (e: unknown) => console.warn('[work] settings didn’t read:', e));
        return () => {
            gone = true;
        };
    }, [caller, loaded, conversation, read]);
    const updateSettings = useCallback(
        async (patch: ConversationChanges) => {
            try {
                await apply(patch);
            } catch (e) {
                if (refusedForFunds(e)) adding.open(costlyModelOf(e), patch);
                else onError(reasonOf(e));
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps -- adding.open only sets the dialog's state and the hold
        [apply, onError]
    );
    const rereadSettings = useCallback(() => setRead((n) => n + 1), []);
    return { settings, updateSettings, rereadSettings, fundsDialog: adding.dialog };
}

/** `caller`'s conversation, live: a lazy agent is looked up first, once, before anything else (beside the history read
 *  by name, `readFirst`, where the page has one). Null while the page doesn't know which yet (an agent's session):
 *  nothing is read, and it isn't ready. */
export function useAgentThread(caller: Agent, conversation: string | null, { key, readFirst, label = 'work', onEvent }: AgentThreadOptions): ConversationState {
    const client = useWorkClient();
    // Looked up once it has a conversation to read: a page still finding which reads nothing yet.
    const known = conversation !== null;
    const loaded = useMemo(() => (known ? caller.hydrate() : null), [caller, known]);
    const keptKey = `${key}\n${conversation}`;
    const seed = () => keptFor(client).get(keptKey);
    const [thread, setThread] = useState<Thread>(() => seed()?.thread ?? EMPTY_THREAD);
    const [ready, setReady] = useState(() => !!seed());
    const [loadError, setLoadError] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    // Stopping a turn can wait for the account's owner (a key NoClick gave this app): a toast follows it.
    const reportHeld = useReportHeld({ client });
    const [attempt, setAttempt] = useState(0);
    const [queued, setQueued] = useState<Queued[]>([]);
    const [commands, setCommands] = useState<AgentCommands | null>(() => seed()?.commands ?? null);
    const { settings, updateSettings, rereadSettings, fundsDialog } = useConversationSettings(caller, loaded, conversation ?? '', seed()?.settings ?? null, setError, key);
    const threadRef = useRef(thread);
    threadRef.current = thread;
    // The turns this page started, which it follows to their end (`follow`).
    const following = useRef(new Set<string>());
    // What the stream says of the long actions its turns start, for their cards.
    const pushed = useMemo(() => new PushedOperations(), []);
    const followJobs = useMemo(() => operationFollower(client, pushed), [client, pushed]);

    useEffect(() => {
        if (ready) keep(client, keptKey, { thread, commands, settings });
    }, [client, keptKey, ready, thread, commands, settings]);

    useEffect(() => {
        const stop = new AbortController();
        const { signal } = stop;
        const seeded = conversation ? (keptFor(client).get(keptKey)?.thread ?? peekV1<Thread>(client, threadKey(key, conversation))) : undefined;
        setThread(seeded ?? EMPTY_THREAD);
        setReady(!!seeded);
        setQueued([]);
        if (!conversation || !loaded) return;
        void (async () => {
            // Read by name beside the lookup, it's drawn the moment it answers; the whole read stands over it.
            if (!seeded && readFirst && !caller.isHydrated) {
                void readFirst().then((early) => {
                    if (early && !signal.aborted) setThread((t) => (t === EMPTY_THREAD ? { ...EMPTY_THREAD, entries: fromHistory(early) } : t));
                });
            }
            const read = await readV1(client, threadKey(key, conversation), () => loaded.then(() => readThread(client, caller, conversation)));
            if (signal.aborted) return;
            setThread(read);
            setReady(true);
            await watchConversation(caller, conversation, {
                signal,
                replay: turnsOver(read),
                label,
                onEvent: (event) => {
                    onEvent?.(event);
                    if (event.type === 'operation' && event.operation) pushed.put(event.operation);
                    if (event.type === 'message' && event.role !== 'assistant' && event.operationId) {
                        const op = event.operationId;
                        setQueued((q) => q.filter((x) => x.operationId !== op));
                    }
                    setThread((t) => applyEvent(t, event, Date.now(), following.current));
                    // A reply the stream settles as failed says why only on its operation.
                    const failedOp = event.type === 'message' && event.role === 'assistant' && event.raw.failed === true && !event.raw.failure ? event.operationId : null;
                    if (failedOp) {
                        failureOfOperation(client, failedOp).then(
                            (failure) => {
                                if (!failure || signal.aborted) return;
                                setThread((t) => withFailure(t, failedOp, failure));
                                rereadAccounts();
                            },
                            (e: unknown) => console.warn('[work] the failed turn’s operation didn’t read:', e)
                        );
                    }
                },
                onReread: (history) => {
                    const entries = fromHistory(history);
                    setThread((t) => reread(t, entries));
                    // A turn at work that ended while the stream was down said so on the stream, which isn't replayed:
                    // its operation says how (one this page follows, its wait says).
                    for (const e of reread(threadRef.current, entries).entries) {
                        const id = e.kind === 'turn' && e.status === 'running' ? e.operationId : null;
                        if (!id || following.current.has(id)) continue;
                        Operation.fromId(id, { client })
                            .hydrate()
                            .then(
                                (op) => {
                                    if (op.done && !signal.aborted) setThread((t) => closed(t, id, op.status, replyText(op.result), Date.now(), following.current));
                                },
                                (err: unknown) => console.warn('[work] a turn’s operation didn’t read:', err)
                            );
                    }
                },
            });
        })().catch((e: unknown) => {
            if (signal.aborted) return;
            setLoadError(e instanceof NotFound ? AGENT_GONE : reasonOf(e));
        });
        return () => stop.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `keptKey` names the agent and conversation
    }, [caller, loaded, client, key, conversation, attempt, pushed]);

    // What its harness offers: read once, never blocking the thread.
    useEffect(() => {
        if (!conversation || !loaded) return;
        let gone = false;
        loaded.then(() => caller.commands(conversation)).then((c) => !gone && setCommands(c), (e: unknown) => console.warn('[work] commands didn’t read:', e));
        return () => {
            gone = true;
        };
    }, [caller, loaded, conversation]);

    const working = !!liveTurn(thread);

    /** Follows a turn this page started to its end, for when its stream says nothing of it (a failure, a stop). */
    const follow = useCallback(
        (op: Operation<unknown>) => {
            following.current.add(op.id);
            op.wait().then(
                (reply) => {
                    following.current.delete(op.id);
                    const answer = reply as { text?: string; steps?: AgentStep[] } | null;
                    setThread((t) => ended(t, op.id, { status: 'done', reply: answer?.text, steps: answer?.steps, at: Date.now() }));
                },
                (error: unknown) => {
                    following.current.delete(op.id);
                    const own = op.isHydrated ? op.error : undefined;
                    // Turned down for lack of money: NoClick's answer, said as its reply.
                    if (own instanceof PaymentRequired) return setThread((t) => ended(t, op.id, { status: 'done', ...refusalOf(own), at: Date.now() }));
                    const status = op.isHydrated && op.status === 'canceled' ? 'stopped' : 'failed';
                    const failure = status === 'failed' ? failureOfError(error) : null;
                    // A failure no one can act on reads as its history will: the failure line. One they can (NoClick
                    // is busy, try again) says so, in its own words without the developer's console link.
                    const said = own && !UNSAID.some((c) => own instanceof c) ? own.message : TURN_FAILED_LINE;
                    setThread((t) =>
                        failure ? withFailure(ended(t, op.id, { status, failure, at: Date.now() }), op.id, failure) : ended(t, op.id, { status, ...(status === 'failed' ? { reply: said } : {}), at: Date.now() })
                    );
                    if (failure) rereadAccounts();
                }
            );
        },
        []
    );

    const send = useCallback(
        async ({ text, files = [], command, delivery, references = [] }: SendInput): Promise<boolean> => {
            const busy = !!liveTurn(threadRef.current);
            const behind = busy ? (command ? 'queue' : (delivery ?? 'steer')) : undefined;
            const shown = command ? `/${command.name}${command.arguments ? ` ${command.arguments}` : ''}` : text;
            const at = Date.now();
            const key = `sent:${at}:${threadRef.current.entries.length}`;
            if (behind === 'queue') setQueued((q) => [...q, { key, text: shown, command: command ?? null, operationId: null }]);
            else setThread((t) => sent(t, key, text, files, at, { steer: behind === 'steer', command, references }));
            try {
                const op = await caller.send(command ? null : composeMessage(text, references, files.length > 0), { conversation: conversation ?? undefined, files, command, delivery: behind });
                if (behind === 'queue') setQueued((q) => q.map((x) => (x.key === key ? { ...x, operationId: op.id } : x)));
                else if (behind !== 'steer') setThread((t) => started(t, key, op.id));
                if (behind !== 'steer') follow(op);
                return true;
            } catch (e) {
                // Turned down for lack of money: the message stands, and NoClick's refusal is its answer.
                if (e instanceof PaymentRequired && behind !== 'queue') {
                    setThread((t) => refused(t, key, refusalOf(e), Date.now()));
                    return true;
                }
                if (behind === 'queue') setQueued((q) => q.filter((x) => x.key !== key));
                else setThread((t) => unsent(t, key));
                setError(reasonOf(e));
                return false;
            }
        },
        [caller, conversation, follow]
    );

    const tellSubagent = useCallback(
        async (subagent: MessageSubagent, text: string): Promise<boolean> => {
            const busy = !!liveTurn(threadRef.current);
            const at = Date.now();
            const key = `sent:${at}:${threadRef.current.entries.length}`;
            setThread((t) => sent(t, key, text, [], at, { steer: busy, subagent }));
            try {
                const op = await caller.conversation(conversation!).messageSubagent(subagent.id, text);
                // With no turn to join it starts one, followed as a send's is.
                if (op.kind === 'agent.message') {
                    setThread((t) => started(t, key, op.id));
                    follow(op);
                }
                return true;
            } catch (e) {
                setThread((t) => unsent(t, key));
                setError(reasonOf(e));
                return false;
            }
        },
        [caller, conversation, follow]
    );

    const stop = useCallback(async () => {
        const live = liveTurn(threadRef.current);
        if (!live?.operationId) return;
        const id = live.operationId;
        try {
            await Operation.fromId(id, { client }).cancel();
            setThread((t) => ended(t, id, { status: 'stopped', at: Date.now() }));
        } catch (e) {
            if (!reportHeld(e, 'Stop the turn')) setError(reasonOf(e));
        }
    }, [client, reportHeld]);

    /** Takes a queued message back (cancelling its operation): it never runs. */
    const unqueue = useCallback(
        async (key: string): Promise<Queued | null> => {
            const item = queued.find((q) => q.key === key);
            if (!item) return null;
            setQueued((q) => q.filter((x) => x.key !== key));
            if (item.operationId) {
                try {
                    await Operation.fromId(item.operationId, { client }).cancel();
                } catch (e) {
                    if (!reportHeld(e, 'Take the message back')) setError(reasonOf(e));
                }
            }
            return item;
        },
        [client, queued, reportHeld]
    );

    const answer = useCallback(
        async (request: HarnessRequest, decision: RequestDecision, options: { note?: string; answers?: Record<string, string | string[]> } = {}) => {
            try {
                const answered = await caller.answer(conversation!, request.id, decision, options);
                setThread((t) => ({ ...t, requests: { ...t.requests, [answered.id]: answered } }));
            } catch (e) {
                setError(reasonOf(e));
            }
        },
        [caller, conversation]
    );

    const rereadHistory = useCallback(async () => {
        if (!conversation) return;
        const history = await caller.history(conversation);
        setThread((t) => reread(t, fromHistory(history)));
    }, [caller, conversation]);

    return {
        agent: caller,
        // The agent's fields are read from it once shown: a lazy one is loaded by then.
        ready: ready && caller.isHydrated,
        loadError,
        thread,
        working,
        queued,
        commands,
        settings,
        send,
        tellSubagent,
        stop,
        unqueue,
        answer,
        updateSettings,
        fundsDialog,
        rereadSettings,
        retry: () => {
            setLoadError(null);
            setAttempt((n) => n + 1);
        },
        error,
        clearError: () => setError(null),
        followJobs,
        rereadHistory,
    };
}

