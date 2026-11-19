// What a thread's cards are, and what they read for the whole thread: the work its turns started, what changes as it
// moves on, what the person asked. The cards themselves are the chat's own table (table.tsx) and whatever its host adds
// in the `chat.cards.more` slot (more cards, cards for a chat's own tools by name, more asks to connect, more of what a
// card draws on its canvas). Light on purpose: a card's matcher module reads its types.
import { createContext, useContext, type ReactNode } from 'react';
import { standing } from '@/slots';
import type { CoordinatorJob, CoordinatorJobs } from '@/lib/threadJobs';
import type { CoordinatorToolCall } from '@/lib/toolCalls';
import { MORE_CARDS } from '../slots';
import { connectAskOfLink } from './cardMatchers';

// `turn` is every call of the turn the card is drawn under, for a card that draws several of them as one.
export type ToolCard = (props: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) => ReactNode;

/** What a card is drawn for, recognised by the call itself rather than a tool name. `turn` is the call's turn, for a
 *  card another of its cards carries. */
export type CardMatch = (call: CoordinatorToolCall, turn?: readonly CoordinatorToolCall[]) => boolean;

/** A card and what it's drawn for. `whileRunning`: it draws while its call still runs too (work it follows live), not
 *  only once it answered. */
export interface CardEntry {
    match: CardMatch;
    Card: ToolCard;
    whileRunning?: boolean;
}

// What the owner asked in the message a turn answers, for the cards under that turn's reply (an MCP server's card opens
// on the agent the owner named); null where no message of theirs started the turn.
const TurnAskedContext = createContext<string | null>(null);
export const TurnAskedProvider = TurnAskedContext.Provider;

export function useTurnAsked(): string | null {
    return useContext(TurnAskedContext);
}

// The work a thread's turns started, as the thread follows it (CardsProvider): a card reads its job here by id.
export const CoordinatorJobsContext = createContext<CoordinatorJobs>({ live: false, get: () => undefined });

export function useCoordinatorJob(jobId: string | undefined): { live: boolean; job: CoordinatorJob | undefined } {
    const jobs = useContext(CoordinatorJobsContext);
    return { live: jobs.live, job: jobs.get(jobId) };
}

// What changes as the thread moves on (a new message), for a card that reads something back again then.
export const ThreadMovedContext = createContext<unknown>(undefined);

export function useThreadMoved(): unknown {
    return useContext(ThreadMovedContext);
}

/** An account a call asks the owner to connect: the request behind its link (`url`), which `requestId` hears fulfilled
 *  elsewhere. */
export interface ConnectAsk {
    /** The call that asked. */
    id: string;
    credentialType: string;
    url: string;
    requestId?: string;
    /** What it's for, in the asker's words. */
    message?: string;
    startedAt: number;
    /** The operation the link waits on, which settles once the account is connected. */
    operationId?: string;
}

export type ConnectAskOf = (call: CoordinatorToolCall) => ConnectAsk | undefined;

/** The account a call asks to connect: an app's connect link the call made, or one a host's tools ask for. */
export function connectAskOf(call: CoordinatorToolCall): ConnectAsk | undefined {
    for (const read of [...standing(MORE_CARDS).asks, connectAskOfLink]) {
        const ask = read(call);
        if (ask) return ask;
    }
    return undefined;
}

/** Every account a turn's calls ask to connect, in the order they asked: one card holds them all. */
export function connectAsksOf(calls: readonly CoordinatorToolCall[]): ConnectAsk[] {
    return calls.flatMap((call) => connectAskOf(call) ?? []);
}
