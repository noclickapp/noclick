// An automation is drawn in full once in a thread, on the newest card about it: an older card about the same
// automation folds to a line (a build card a later build supersedes, a setup card a later one for another client
// replaces), so the thread ends where the automation now stands rather than wherever it was first drawn. Each kind
// of tool card says which automation a call draws; a platform adds its own (hosted: the coordinator agent's builds
// through the platform API). A note's setup card is about the automation its setup names.
import { createContext, useContext } from 'react';
import type { CoordinatorJobs } from '~/hooks/useCoordinatorJobs';
import { str, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import type { CoordinatorSetupRef } from '~/types/socket-events.generated';

/** The automation a call's card draws on its canvas, if it draws one; `jobs` are the thread's reads of its work. */
export type CanvasOf = (call: CoordinatorToolCall, jobs: CoordinatorJobs) => string | undefined;

const CANVASES: CanvasOf[] = [(call) => (call.tool === 'request_build' ? str(call.result, 'workflow_id') : undefined)];

export function registerCanvasCard(canvasOf: CanvasOf): void {
    CANVASES.push(canvasOf);
}

/** A note's setup card, by the id the transcript gives it (`setupCardId`). */
export interface SetupCardRef {
    id: string;
    setup: CoordinatorSetupRef;
}

/** The newest card about an automation: a tool call's, or a note's setup card (with its setup). */
export interface NewestCard {
    id: string;
    setup?: CoordinatorSetupRef;
}

export function setupCardId(messageIndex: number): string {
    return `setup:${messageIndex}`;
}

function automationOf(card: CoordinatorToolCall | SetupCardRef, jobs: CoordinatorJobs): string | undefined {
    if ('setup' in card) return card.setup.workflow_id;
    for (const canvasOf of CANVASES) {
        const workflowId = canvasOf(card, jobs);
        if (workflowId) return workflowId;
    }
    return undefined;
}

/** Each automation the thread's cards (in thread order) draw, to its newest card. */
export function newestCanvases(cards: readonly (CoordinatorToolCall | SetupCardRef)[], jobs: CoordinatorJobs): ReadonlyMap<string, NewestCard> {
    const newest = new Map<string, NewestCard>();
    for (const card of cards) {
        const workflowId = automationOf(card, jobs);
        if (workflowId) newest.set(workflowId, 'setup' in card ? { id: card.id, setup: card.setup } : { id: card.id });
    }
    return newest;
}

const CanvasesContext = createContext<ReadonlyMap<string, NewestCard>>(new Map());
export const CanvasesProvider = CanvasesContext.Provider;

/** The newer card in the thread about `workflowId` than the card `cardId`, if there is one. */
export function useNewerCard(cardId: string, workflowId: string | undefined): NewestCard | undefined {
    const newest = useContext(CanvasesContext).get(workflowId ?? '');
    return newest && newest.id !== cardId ? newest : undefined;
}

/** Whether the card of `callId` draws `workflowId`'s canvas: unless a newer card in the thread is about it. */
export function useDrawsCanvas(callId: string, workflowId: string | undefined): boolean {
    return !useNewerCard(callId, workflowId);
}
