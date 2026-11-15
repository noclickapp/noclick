// The seams a platform fills in the coordinator's transcript: cards for its own tools, how a turn at work is drawn,
// and the card under a setup note. Kept apart from toolCards.tsx (which renders the built-in cards and with them
// the credential forms and every node schema) because a platform registers here while every page boots.
import { createContext, useContext, type ComponentType, type ReactNode } from 'react';
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import { failed, str, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import type { NewestCard } from './canvases';
import type { CoordinatorSetupRef } from '~/types/socket-events.generated';

// `turn` is every call of the turn the card is drawn under, for a card that draws several of them as one.
export type ToolCard = (props: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) => ReactNode;

// What the owner asked in the message a turn answers, for the cards under that turn's reply (an MCP server's card opens
// on the agent the owner named); null where no message of theirs started the turn.
const TurnAskedContext = createContext<string | null>(null);
export const TurnAskedProvider = TurnAskedContext.Provider;

export function useTurnAsked(): string | null {
    return useContext(TurnAskedContext);
}

// Cards a platform adds for what only its tools do, recognised by the call itself rather than a tool name (hosted: a
// call NoClick placed, from cloud/bootstrap). `turn` is the call's turn, for a card another of its cards carries.
export type CardMatch = (call: CoordinatorToolCall, turn?: readonly CoordinatorToolCall[]) => boolean;
export const MATCHED_CARDS: { match: CardMatch; Card: ToolCard; whileRunning: boolean }[] = [];

/** `whileRunning`: the card draws while its call still runs too (work it follows live), not only once it answered. */
export function registerToolCard(match: CardMatch, Card: ToolCard, { whileRunning = false }: { whileRunning?: boolean } = {}): void {
    MATCHED_CARDS.push({ match, Card, whileRunning });
}

/** An account a call asks the owner to connect: the credential request behind its provide link (`url`), which
 *  `requestId` hears fulfilled elsewhere. */
export interface ConnectAsk {
    /** The call that asked. */
    id: string;
    credentialType: string;
    url: string;
    requestId?: string;
    /** What it's for, in the asker's words. */
    message?: string;
    startedAt: number;
}

export type ConnectAskOf = (call: CoordinatorToolCall) => ConnectAsk | undefined;

// The coordinator's own ask (connect_credential), and any a platform registers (hosted: a connect link one of its calls
// made), so every ask a turn makes is one card.
const CONNECT_ASKS: ConnectAskOf[] = [
    (call) => {
        const credentialType = str(call.args, 'credential_type');
        const url = str(call.result, 'url');
        if (call.tool !== 'connect_credential' || !credentialType || !url || failed(call.result)) return undefined;
        return { id: call.id, credentialType, url, requestId: str(call.result, 'request_id'), message: str(call.args, 'message'), startedAt: call.startedAt };
    },
];

export function registerConnectAsk(read: ConnectAskOf): void {
    CONNECT_ASKS.push(read);
}

export function connectAskOf(call: CoordinatorToolCall): ConnectAsk | undefined {
    for (const read of CONNECT_ASKS) {
        const ask = read(call);
        if (ask) return ask;
    }
    return undefined;
}

/** Every account a turn's calls ask to connect, in the order they asked. */
export function connectAsksOf(calls: readonly CoordinatorToolCall[]): ConnectAsk[] {
    return calls.flatMap((call) => connectAskOf(call) ?? []);
}

// How a turn shows the agent at work (its calls as it makes them, the wait for its reply), where the platform draws
// that its own way; unset, the transcript's standard steps and orb stand. Undefined for a message it leaves alone.
export type TurnWorkDrawing = (msg: AgentChatMessage | null) => ReactNode | undefined;
let TURN_WORK: TurnWorkDrawing | undefined;

export function registerTurnWork(draw: TurnWorkDrawing): void {
    TURN_WORK = draw;
}

export function turnWorkDrawing(): TurnWorkDrawing | undefined {
    return TURN_WORK;
}

// The card under a setup note (a workflow picked on a public page, finished here): the platform that makes those
// pages draws it, loaded when a thread first shows one. `newer` is the newer card in the thread about the same
// automation, when there is one: the card folds to a line.
export type SetupCard = ComponentType<{ setup: CoordinatorSetupRef; newer?: NewestCard }>;
let SETUP_CARD: SetupCard | null = null;

export function registerSetupCard(Card: SetupCard): void {
    SETUP_CARD = Card;
}

export function setupCard(): SetupCard | null {
    return SETUP_CARD;
}

// The card under a reply that turned a request down because the account ran out of money (`outOfFunds` on the
// message): the platform that sells funds draws how to get going again.
export type OutOfFundsCard = ComponentType<{ refusal: Record<string, unknown> }>;
let OUT_OF_FUNDS_CARD: OutOfFundsCard | null = null;

export function registerOutOfFundsCard(Card: OutOfFundsCard): void {
    OUT_OF_FUNDS_CARD = Card;
}

export function outOfFundsCard(): OutOfFundsCard | null {
    return OUT_OF_FUNDS_CARD;
}
