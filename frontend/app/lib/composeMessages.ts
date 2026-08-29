// Pure projection: persisted committed history + active in-flight gens →
// the Message[] that MessagesView renders.
//
// This is the entire "how does the chat look right now" computation.
// It's a pure function over two inputs, so it's trivial to test and
// impossible to enter a stuck/inconsistent state on. The complexity
// budget for chat-rendering is spent here, once.
//
// Invariants:
//   • Persisted prefix always comes first (in the order of conversations.events)
//   • Each active gen contributes exactly two bubbles: [user_prompt, asst_in_flight]
//   • The asst bubble's isComplete=false signals streaming to ChatBox
//   • An active gen's text + events + edit_steps live on the asst bubble
//     ─ no separate streaming-state surface to keep in sync
//
// On terminal: the gen evicts from activeGenStore and the BE's committed
// patch replaces persistedMessages atomically (see useConversation),
// producing a single render where the in-flight bubble disappears and
// the persisted history grows by one turn — no flicker.

import type { Message, EditSegment } from '~/components/chat/types';
import type { ActiveGeneration } from '~/lib/activeGenStore';
import { mapPersistedMessages, type PersistedMessage } from '~/hooks/conversationRestoreMapping';

type EditEvents = Extract<EditSegment, { type: 'events' }>['events'];

/** Convert one active gen into bubbles.
 *
 * A fresh gen produces [user_prompt, asst_in_flight]. A resume gen
 * (prompt === '') is a continuation — the prior turn's user prompt is
 * already in persisted history, so we render only the assistant bubble.
 * This is what makes Skip All and credential-submit feel like the same
 * bubble continuing rather than a new turn appearing.
 */
function activeGenToBubbles(gen: ActiveGeneration): Message[] {
    // Assemble edit_segments from the gen's accumulated text + graph events.
    // Same shape conversations.events uses, so MessagesView's renderer
    // doesn't need a special case for in-flight content.
    const segments: EditSegment[] = [];
    if (gen.text) {
        segments.push({ type: 'text', text: gen.text });
    }
    if (gen.events.length > 0) {
        segments.push({
            type: 'events',
            events: gen.events.map(e => ({ ...(e as Record<string, unknown>), status: 'completed' as const })) as EditEvents,
        });
    }
    // A gen the user stopped (`wasInterrupted` → "interrupted by user" notice)
    // OR one the watchdog flagged as interrupted (container drained/killed — no
    // terminal frame is coming) renders as a completed turn: no streaming
    // animation. The disconnect case shows no inline notice — the actionable
    // "connection lost / Retry" affordance lives in the InterruptedRunBanner
    // above the ChatBox; here we just stop the spinner so it doesn't look live.
    const ended = !!(gen.stopped || gen.interrupted || gen.failed);
    const assistant: Message = {
        text: '',
        isUser: false,
        isComplete: ended,
        editSegments: segments,
        editSteps: gen.edit_steps.length > 0 ? [...gen.edit_steps] : undefined,
        editStatus: ended ? undefined : (gen.status || undefined),
        generationId: gen.gen_id,
        ...(gen.stopped ? { wasInterrupted: true } : {}),
        ...(gen.failed ? { failed: true, error: gen.error, errorCode: gen.errorCode, errorMeta: gen.errorMeta } : {}),
    };
    if (!gen.prompt) {
        // Resume / continuation: no new user bubble.
        return [assistant];
    }
    return [
        { text: gen.prompt, isUser: true, isComplete: true },
        assistant,
    ];
}

/** Build the extra segments + steps an active gen contributes. */
function genExtras(gen: ActiveGeneration): {
    segments: EditSegment[];
    steps: string[];
} {
    const segments: EditSegment[] = [];
    if (gen.text) segments.push({ type: 'text', text: gen.text });
    if (gen.events.length > 0) {
        segments.push({
            type: 'events',
            events: gen.events.map(e => ({ ...(e as Record<string, unknown>), status: 'completed' as const })) as EditEvents,
        });
    }
    return { segments, steps: [...gen.edit_steps] };
}

export function composeMessages(
    persisted: PersistedMessage[],
    activeGens: ActiveGeneration[],
): Message[] {
    const result = mapPersistedMessages(persisted);
    if (activeGens.length === 0) return result;

    for (let i = 0; i < activeGens.length; i++) {
        const gen = activeGens[i];
        const prev = i > 0 ? activeGens[i - 1] : null;
        // A resume re-submits the interrupted run's ORIGINAL prompt. Render it as
        // a continuation of that dead turn (extend the trailing assistant) rather
        // than a fresh [user, asst] turn — otherwise the prompt shows twice and
        // two simultaneously-streaming turns can drive a render loop (React #185).
        // Keyed on the immediately-prior gen being interrupted with the same
        // prompt, so genuinely re-typing a prompt after a COMPLETED turn is never
        // merged.
        const continuesInterrupted = !!(gen.prompt && prev && prev.interrupted && prev.prompt === gen.prompt);
        if (!gen.prompt || continuesInterrupted) {
            // Resume / continuation: extend the trailing assistant in
            // place. This is what makes Skip All / credential-submit
            // look like the same bubble continuing — accumulated
            // segments + steps from the prior turn stay visible while
            // the new ones stream in below them.
            const lastIdx = result.length - 1;
            const last = lastIdx >= 0 ? result[lastIdx] : null;
            if (last && !last.isUser) {
                const extras = genExtras(gen);
                const ended = !!(gen.stopped || gen.interrupted || gen.failed);
                result[lastIdx] = {
                    ...last,
                    isComplete: ended,
                    pendingAsk: undefined,
                    editSegments: [...(last.editSegments || []), ...extras.segments],
                    editSteps: [...(last.editSteps || []), ...extras.steps],
                    editStatus: ended ? undefined : (gen.status || last.editStatus),
                    generationId: gen.gen_id,
                    ...(gen.stopped ? { wasInterrupted: true } : {}),
                    ...(gen.failed ? { failed: true, error: gen.error, errorCode: gen.errorCode, errorMeta: gen.errorMeta } : {}),
                };
                continue;
            }
            // Fall through: no trailing assistant to extend. Render as
            // a standalone in-flight bubble (the activeGenToBubbles
            // path with empty prompt already handles this — single bubble).
        }
        // Fresh gen with a prompt OR resume gen with no anchor: append
        // [user_bubble, asst_in_flight] (or just [asst_in_flight] for
        // empty-prompt with no anchor).
        const bubbles = activeGenToBubbles(gen);
        // Defensive dedupe: persisted tail user prompt already matches
        // the gen's user bubble.
        const lastHead = result[result.length - 1];
        const skipUser = !!(lastHead && lastHead.isUser && lastHead.text === gen.prompt && gen.prompt);
        result.push(...(skipUser ? bubbles.slice(1) : bubbles));
    }
    return result;
}
