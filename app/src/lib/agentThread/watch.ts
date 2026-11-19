// One agent conversation followed live over /v1 (agent.watch), for each page that shows one: Work's conversations and
// the Chat page. A dropped stream is taken up again after a pause that grows while it keeps dropping, with the history
// read afresh before each reconnection. Only the first connection replays what the stream keeps, so a turn at work as
// the page opened is drawn from its start, leaving out the moments of turns the history already holds. A reconnection
// never replays: the page has drawn those moments, and a turn's words and output would be appended twice.
import type { Agent, AgentEvent, Message } from 'noclick';

const RECONNECT_MS = [1000, 2000, 5000, 10_000, 30_000];

const pause = (ms: number, signal: AbortSignal) =>
    new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, ms);
        signal.addEventListener('abort', () => (clearTimeout(timer), resolve()), { once: true });
    });

/** Whether the stream's replay of `event` is a moment of a turn that's over. Messages are never replayed: the
 *  conversation keeps them. */
export function ofTurnOver(event: AgentEvent, over: ReadonlySet<string>): boolean {
    return event.type !== 'message' && !!event.operationId && over.has(event.operationId);
}

export interface Watch {
    signal: AbortSignal;
    /** For the first connection, the turns the history holds (over), whose moments a replay leaves out; null replays
     *  nothing. */
    replay: ReadonlySet<string> | null;
    onEvent: (event: AgentEvent) => void;
    /** The history read again after the stream dropped, before it's taken up again. */
    onReread: (history: Message[]) => void;
    /** Who watches, in what the console says. */
    label: string;
}

/** Follows `conversation` until `signal` aborts. */
export async function watchConversation(agent: Agent, conversation: string, { signal, replay, onEvent, onReread, label }: Watch): Promise<void> {
    let over = replay;
    for (let drops = 0; !signal.aborted; ) {
        try {
            for await (const event of agent.watch(conversation, { signal, replay: over !== null })) {
                drops = 0;
                if (!over || !ofTurnOver(event, over)) onEvent(event);
            }
        } catch (error) {
            if (signal.aborted) return;
            console.warn(`[${label}] the conversation’s stream dropped:`, error);
        }
        over = null;
        await pause(RECONNECT_MS[Math.min(drops++, RECONNECT_MS.length - 1)], signal);
        if (signal.aborted) return;
        try {
            const history = await agent.history(conversation);
            if (!signal.aborted) onReread(history);
        } catch (error) {
            console.warn(`[${label}] the conversation didn’t read back:`, error);
        }
    }
}
