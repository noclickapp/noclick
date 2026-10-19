// The seams a platform fills in the coordinator's transcript: cards for its own tools, how a turn at work is drawn,
// and the card under a setup note. Kept apart from toolCards.tsx (which renders the built-in cards and with them
// the credential forms and every node schema) because a platform registers here while every page boots.
import { createContext, useContext, type ComponentType, type ReactNode } from 'react';
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import type { NewestCard } from './canvases';
import type { CoordinatorSetupRef } from '~/types/socket-events.generated';

export type ToolCard = (props: { call: CoordinatorToolCall }) => ReactNode;

// What the owner asked in the message a turn answers, for the cards under that turn's reply (an MCP server's card opens
// on the agent the owner named); null where no message of theirs started the turn.
const TurnAskedContext = createContext<string | null>(null);
export const TurnAskedProvider = TurnAskedContext.Provider;

export function useTurnAsked(): string | null {
    return useContext(TurnAskedContext);
}

// Cards a platform adds for what only its tools do, recognised by the call itself rather than a tool name (hosted: a
// call NoClick placed, from cloud/bootstrap).
export const MATCHED_CARDS: { match: (call: CoordinatorToolCall) => boolean; Card: ToolCard }[] = [];

export function registerToolCard(match: (call: CoordinatorToolCall) => boolean, Card: ToolCard): void {
    MATCHED_CARDS.push({ match, Card });
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
