// A call NoClick holds for the account's owner (the gate answers it 402 `approval_required`, with the held call as an
// operation and where the owner was sent the link, never the link): what the screen that made it says while it waits,
// and once it's answered. It's followed over the account's frames: the approval's own frame says when the owner
// answered; approved, the call runs, and one wait the server holds until it ends brings its answer. A frame missed (a
// reset, the tab coming back into focus) reads the call once again. Nothing asks on a timer.
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
    ApprovalRequired,
    Expired,
    NotFound,
    Operation,
    OperationCanceled,
    OperationTimeout,
    PolicyDenied,
    type JsonObject,
    type NoClick,
} from 'noclick';
import { useProvidedClient } from '@/sdk/client';
import { WorkLiveContext, type WorkLive } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';

/** A held call, as the screen that made it reads it from the 402. */
export interface HeldCall {
    approvalId: string;
    /** The held call itself: NoClick makes it once the owner approves. */
    operationId: string;
    /** Where the owner was sent the link: `whatsapp`, `imessage`, `email`; `web` alone when the card in the chat they
     *  were watching was it; none when it reached nobody. */
    sentTo: string[];
    /** Who else answers it, when the account's settings route it to someone other than the owner. */
    approver: string | null;
    /** What the call does, in the gate's words. */
    summary: string | null;
    /** `awaiting_approval`, or `approved` when it was approved already and runs now. */
    status: string;
}

/** The held call `error` is, or null for any other error (an approval of something else, which has no call to run). */
export function heldCallOf(error: unknown): HeldCall | null {
    if (!(error instanceof ApprovalRequired)) return null;
    const details = error.details as JsonObject;
    const operationId = typeof details.operation_id === 'string' ? details.operation_id : null;
    const approvalId = error.approvalId;
    if (!operationId || !approvalId) return null;
    const approver = details.approver && typeof details.approver === 'object' ? (details.approver as JsonObject) : null;
    return {
        approvalId,
        operationId,
        sentTo: Array.isArray(details.sent_to) ? details.sent_to.filter((app): app is string => typeof app === 'string') : [],
        approver: approver ? String(approver.name ?? approver.kind ?? 'someone the account named') : null,
        summary: typeof details.summary === 'string' ? details.summary : null,
        status: typeof details.status === 'string' ? details.status : 'awaiting_approval',
    };
}

const SENT_ON: Record<string, string> = { whatsapp: 'on WhatsApp', imessage: 'by iMessage', email: 'by email' };

/** Where the approval went, as a person reads it: "Sent to the account's owner to approve, by email." */
export function sentWords(held: HeldCall): string {
    if (held.approver) return `Sent to ${held.approver} to approve.`;
    if (held.sentTo.length === 1 && held.sentTo[0] === 'web') return 'Sent to the account’s owner to approve, on its card in their NoClick chat.';
    const ways = held.sentTo.map((app) => SENT_ON[app] ?? `on ${app}`);
    if (!ways.length) return 'NoClick couldn’t reach the account’s owner, so it waits for them to approve it signed in to NoClick.';
    return `Sent to the account’s owner to approve, ${ways.join(' and ')}.`;
}

export type HeldPhase = 'waiting' | 'running' | 'done' | 'declined' | 'expired' | 'canceled' | 'failed';

export interface HeldState {
    phase: HeldPhase;
    /** Once done: the call's own answer (its HTTP status and body). */
    status?: number;
    response?: unknown;
    /** Once it ended any other way: why, in NoClick's words. */
    message?: string;
}

const ENDED = new Set<HeldPhase>(['done', 'declined', 'expired', 'canceled', 'failed']);

/** Whether `state` is where the call ended. */
export const settled = (state: HeldState | null): boolean => !!state && ENDED.has(state.phase);

/** What an approval's frame status says of the call. */
const BY_FRAME: Record<string, HeldPhase> = { approved: 'running', declined: 'declined', expired: 'expired', canceled: 'canceled' };
const SAID: Partial<Record<HeldPhase, string>> = {
    declined: 'The account’s owner declined it.',
    expired: 'Nobody approved it in time.',
    canceled: 'The approval was withdrawn.',
};

/** The call's state from its operation as last read. */
function stateOf(op: Operation<JsonObject>): HeldState {
    const status = String(op.status);
    if (status === 'succeeded') {
        const result = (op.result ?? {}) as JsonObject;
        return { phase: 'done', status: typeof result.status === 'number' ? result.status : undefined, response: result.response };
    }
    if (status === 'awaiting_human') return { phase: 'waiting' };
    if (status === 'queued' || status === 'running') return { phase: 'running' };
    const message = op.error?.message;
    if (status === 'expired') return { phase: 'expired', message: message ?? SAID.expired };
    if (status === 'canceled') return { phase: 'canceled', message: message ?? SAID.canceled };
    if (op.error instanceof PolicyDenied) return { phase: 'declined', message: message ?? SAID.declined };
    return { phase: 'failed', message: message ?? 'It didn’t go through.' };
}

/** The call's state from what its wait threw. */
function thrownState(error: unknown): HeldState | null {
    if (error instanceof PolicyDenied) return { phase: 'declined', message: error.message };
    if (error instanceof Expired) return { phase: 'expired', message: error.message };
    if (error instanceof OperationCanceled) return { phase: 'canceled', message: error.message };
    if (error instanceof NotFound) return { phase: 'canceled', message: 'It’s no longer here.' };
    return null;
}

const WAIT_S = 50;

/**
 * Follows `held` until it ends, telling `onState` each state it reaches (the first one at once): on `live`'s frames of
 * its approval, a reset, and `look()` (a tab back in focus). Returns `{ look, stop }`.
 */
export function followHeldCall(client: NoClick, live: WorkLive, held: HeldCall, onState: (state: HeldState) => void) {
    const op = Operation.fromId<JsonObject>(held.operationId, { client });
    let stopped = false;
    let last: HeldState | null = null;
    let waiting = false;
    const say = (state: HeldState) => {
        if (stopped || settled(last)) return;
        // Read again and found where it was: nothing new to say.
        if (last && last.phase === state.phase && !settled(state)) return;
        last = state;
        onState(state);
        if (settled(state)) stop();
    };

    // Approved: the call runs now, and the server holds this read until it ends.
    const waitForIt = async () => {
        if (waiting) return;
        waiting = true;
        try {
            while (!stopped) {
                try {
                    await op.wait({ timeoutS: WAIT_S });
                    say(stateOf(op));
                    return;
                } catch (error) {
                    const ended = thrownState(error);
                    if (ended) return say(ended);
                    if (error instanceof OperationTimeout) continue;
                    console.warn('[held] waiting on the held call failed:', error);
                    return;
                }
            }
        } finally {
            waiting = false;
        }
    };

    const look = async () => {
        if (stopped || settled(last)) return;
        try {
            await op.refresh();
        } catch (error) {
            const ended = thrownState(error);
            if (ended) say(ended);
            else console.warn('[held] reading the held call failed:', error);
            return;
        }
        const state = stateOf(op);
        // An approval answered just now: its frame can come before the call is failed or queued.
        if (state.phase === 'waiting' && last && last.phase !== 'waiting') return;
        say(state);
        if (state.phase === 'running') void waitForIt();
    };

    const offFrames = live.on('platform:resource', (frame) => {
        if (frame.kind !== 'approval' || frame.id !== held.approvalId) return;
        const phase = BY_FRAME[frame.status ?? ''];
        if (phase === 'running') {
            say({ phase });
            void waitForIt();
        } else if (phase) {
            // The call is failed with the reason in the same step that sent the frame, which may land first.
            void op.refresh().then(
                () => say(op.done ? stateOf(op) : { phase, message: SAID[phase] }),
                () => say({ phase, message: SAID[phase] })
            );
        } else void look();
    });
    const offReset = live.on('reset', () => void look());

    function stop() {
        if (stopped) return;
        stopped = true;
        offFrames();
        offReset();
    }

    if (held.status === 'approved') {
        say({ phase: 'running' });
        void waitForIt();
    } else {
        say({ phase: 'waiting' });
        void look();
    }
    return { look: () => void look(), stop };
}

/** Where a screen made a held call: the client it made it with, and the frames it follows (a console's own). */
export interface HeldSource {
    client?: NoClick | null;
    live?: WorkLive | null;
}

/** The client the call was made with (the page's own by default), and the frames a screen follows: its own (the
 *  console's, Work's, a test's) where it has them, else the account's change stream. */
function useHeldLive(from: HeldSource | null = null): () => { client: NoClick; live: WorkLive } {
    const provided = useProvidedClient();
    const client = from?.client ?? provided;
    const context = useContext(WorkLiveContext);
    const given = from?.live ?? context;
    const own = useMemo(() => (given || !client ? null : liveFromWatch(sdkLive(client))), [given, client]);
    // Asked for only once something is held, so a screen that never holds anything needs neither.
    return useCallback(() => {
        if (!client) throw new Error('A held call is followed with the client that made it: pass it, or render under a <ClientProvider>.');
        return { client, live: given ?? own! };
    }, [client, given, own]);
}

/** `held` followed while the screen shows it: its state, or null when nothing is held. Read again when the tab comes
 *  back into focus while it waits. */
export function useHeldCall(held: HeldCall | null, onSettled?: (state: HeldState) => void, from?: HeldSource | null): HeldState | null {
    const following = useHeldLive(from);
    const [state, setState] = useState<HeldState | null>(null);
    const settledRef = useRef(onSettled);
    settledRef.current = onSettled;
    const heldRef = useRef(held);
    heldRef.current = held;
    // A held call read from an error again each render is the same call: followed once, by its approval.
    const approvalId = held?.approvalId ?? null;
    useEffect(() => {
        setState(null);
        const call = heldRef.current;
        if (!call) return;
        const { client, live } = following();
        const follow = followHeldCall(client, live, call, (next) => {
            setState(next);
            if (settled(next)) settledRef.current?.(next);
        });
        const look = () => follow.look();
        window.addEventListener('focus', look);
        return () => {
            window.removeEventListener('focus', look);
            follow.stop();
        };
    }, [following, approvalId]);
    return state;
}

export interface HeldWords {
    /** What the call does, as the screen names it ("Buy +1 567 483 3618"). */
    what: string;
    /** Said once it's done ("+1 567 483 3618 is yours"); "<what>: done" by default. */
    done?: string;
}

/** What a screen says of `held` at `state` (null: just held). */
export function heldLines(held: HeldCall, state: HeldState | null, words: HeldWords): { title: string; text?: string } {
    switch (state?.phase ?? 'waiting') {
        case 'waiting':
            return { title: `${words.what}: waiting for approval`, text: `${sentWords(held)} It goes ahead once they approve it.` };
        case 'running':
            return { title: `${words.what}: approved`, text: 'NoClick is doing it now.' };
        case 'done':
            return { title: words.done ?? `${words.what}: done` };
        default:
            return { title: `${words.what}: not done`, text: state?.message };
    }
}

/**
 * For a screen whose call ends in a toast (a delete, mostly): `report(error, what, onDone)` shows a held call as a
 * toast that says where it went and follows it to its end, calling `onDone` once it's done (to read the list again),
 * and returns true; any other error returns false for the screen to show as it does.
 */
export function useReportHeld(from?: HeldSource | null): (error: unknown, what: string, onDone?: (state: HeldState) => void) => boolean {
    const following = useHeldLive(from);
    return useCallback(
        (error, what, onDone) => {
            const held = heldCallOf(error);
            if (!held) return false;
            const { client, live } = following();
            const id = `held:${held.approvalId}`;
            const focus = () => follow.look();
            const follow = followHeldCall(client, live, held, (state) => {
                const { title, text } = heldLines(held, state, { what });
                const show = state.phase === 'done' ? toast.success : settled(state) ? toast.error : toast;
                show(title, { id, description: text, duration: settled(state) ? 8000 : Infinity });
                if (settled(state)) {
                    window.removeEventListener('focus', focus);
                    if (state.phase === 'done') onDone?.(state);
                }
            });
            window.addEventListener('focus', focus);
            return true;
        },
        [following]
    );
}
