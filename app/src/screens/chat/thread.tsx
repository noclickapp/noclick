// The Chat page's live conversation: NoClick's one session through the one hook every page uses (useAgentThread),
// handed to what draws it beside the page's shared parts: the transcript (Work's rows, naming the accounts a message
// points at as the host names them), the Beside and the box (clear and resume). The work its turns started is followed
// once here, so the cards and the Beside read one copy of it.
import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { ChatReference } from '@/lib/agentThread/messages';
import type { Thread } from '@/lib/agentThread/thread';
import type { CoordinatorJobs } from '@/lib/threadJobs';
import { turnCalls } from '@/screens/work/conversation/cards';
import type { SessionControls } from '@/screens/work/conversation/sessionControls';
import type { ConversationState } from '@/screens/work/hooks/useAgentThread';
import type { ThreadTurn } from './useAgentsAtWork';

/** How a reference chip names what a message points at, and its mark (an account in its app's logo); undefined where
 *  the chip's own words stand. */
export type ReferenceDisplay = (reference: ChatReference) => { label: string; mark: ReactNode } | undefined;

export interface ChatThread {
    state: ConversationState;
    /** The session it's in, once read. */
    session: string | null;
    /** Clearing it and resuming an earlier one. */
    sessions: SessionControls;
    /** Each turn's calls of NoClick's tools, with what the person asked in the message it answers. */
    turns: ThreadTurn[];
    /** The work those calls started, followed once. */
    jobs: CoordinatorJobs;
    referenceDisplay: ReferenceDisplay;
}

export const ChatThreadContext = createContext<ChatThread | null>(null);

export function useChatThread(): ChatThread {
    const thread = useContext(ChatThreadContext);
    if (!thread) throw new Error('The chat’s parts render inside its provider.');
    return thread;
}

/** The thread's turns as the work they started is read from them: each turn's calls (and what it left waiting on a
 *  person), and what the person asked in the message it answers (a trigger's isn't theirs). */
export function threadTurns(thread: Thread): ThreadTurn[] {
    const turns: ThreadTurn[] = [];
    let asked: string | null = null;
    for (const e of thread.entries) {
        if (e.kind === 'user') asked = e.trigger && !e.author ? null : e.text;
        else if (e.kind === 'turn') turns.push({ asked, calls: turnCalls(e) });
    }
    return turns;
}

/** Provides the thread, its turns and their followed work to what draws it. */
export function ChatThreadProvider({
    state,
    session,
    sessions,
    referenceDisplay,
    children,
}: {
    state: ConversationState;
    session: string | null;
    sessions: SessionControls;
    referenceDisplay: ReferenceDisplay;
    children: ReactNode;
}) {
    const turns = useMemo(() => threadTurns(state.thread), [state.thread]);
    const calls = useMemo(() => turns.flatMap((t) => t.calls), [turns]);
    const jobs = state.followJobs(calls, state.thread.entries.length);
    const value = useMemo(() => ({ state, session, sessions, turns, jobs, referenceDisplay }), [state, session, sessions, turns, jobs, referenceDisplay]);
    return <ChatThreadContext.Provider value={value}>{children}</ChatThreadContext.Provider>;
}
