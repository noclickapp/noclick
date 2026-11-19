// A call placed through the platform API (POST /v1/phone_numbers/{id}/calls), as its card follows it: the SDK reads
// the call (PhoneNumber.getCall, first by the operation that placed it, then by the call's own id), and reads it again
// whenever the backend says it moved (a platform:resource frame of kind phone_call: picked up, a turn said, ended),
// with a slow re-read while it goes as the backstop. Hang up is PhoneNumber.hangUp; the end arrives as any end does.
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { CallOutcome } from '@/ui/chat/live';
import { BACKSTOP_POLL_MS } from '@/sdk/staleReads';
import { useClient } from '@/sdk/client';
import { NotFound, Operation, PhoneNumber, type PhoneCall } from 'noclick';
import { useWorkFrames } from '@/sdk/live';

export type CallState = 'calling' | 'answered' | 'ended';

export interface PlacedCall {
    /** A read has said how the call stands. */
    known: boolean;
    state: CallState;
    outcome?: CallOutcome;
    /** Hung up through NoClick (the card, or the coordinator asked to). */
    endedByYou?: boolean;
    to?: string;
    from?: string;
    placedAt?: number;
    answeredAt?: number;
    endedAt?: number;
    /** What was said so far, as the card names who said it. */
    lines: { who: 'them' | 'noclick'; text: string }[];
}

export const UNKNOWN_CALL: PlacedCall = { known: false, state: 'calling', lines: [] };

const OPEN = new Set(['placing', 'calling']);
// How a call that ended reads on its card: refused and failed alike didn't go through; lost, that track was lost.
const OUTCOMES: Record<string, CallOutcome> = { completed: 'completed', not_connected: 'not_connected', lost: 'expired' };

/** The call as its card draws it. */
export function placedCall(call: PhoneCall): PlacedCall {
    const open = OPEN.has(call.status ?? '');
    return {
        known: true,
        state: open ? (call.answeredAt ? 'answered' : 'calling') : 'ended',
        ...(open ? {} : { outcome: OUTCOMES[call.status ?? ''] ?? 'failed' }),
        endedByYou: call.endedBy === 'hang_up',
        to: call.to ?? undefined,
        from: call.fromNumber ?? undefined,
        placedAt: call.createdAt?.getTime(),
        answeredAt: call.answeredAt?.getTime(),
        endedAt: call.endedAt?.getTime(),
        lines: call.lines.map((line) => ({ who: line.who === 'them' ? 'them' : 'noclick', text: line.text })),
    };
}

export interface PlacedCallControls {
    call: PlacedCall;
    /** The call couldn't be read: the card can only say what the tool reported. */
    unreadable: boolean;
    hangUp: () => void;
    hangingUp: boolean;
}

export function usePlacedCall(operationId: string): PlacedCallControls {
    const client = useClient();
    const [call, setCall] = useState<PlacedCall>(UNKNOWN_CALL);
    const [unreadable, setUnreadable] = useState(false);
    const [gone, setGone] = useState(false);
    const [hangingUp, setHangingUp] = useState(false);
    // The call's own id once a read named it; until then the operation that placed it names it.
    const callId = useRef<string | null>(null);
    const reading = useRef(false);
    const again = useRef(false);

    const target = useCallback(
        () => callId.current ?? Operation.fromId(operationId, { client, user: null }),
        [client, operationId]
    );

    // One read at a time; a move heard meanwhile reads once more after it, so the newest state always lands.
    const read = useCallback(async () => {
        if (reading.current) {
            again.current = true;
            return;
        }
        reading.current = true;
        try {
            do {
                again.current = false;
                try {
                    const found = await PhoneNumber.getCall(target(), { client, user: null });
                    callId.current = found.id ?? callId.current;
                    setCall(placedCall(found));
                    setUnreadable(false);
                } catch (error) {
                    if (error instanceof NotFound) setGone(true);
                    setUnreadable(true);
                    console.warn('[coordinator] reading the call failed:', error);
                }
            } while (again.current);
        } finally {
            reading.current = false;
        }
    }, [client, target]);

    useWorkFrames(
        'platform:resource',
        (frame) => {
            // Before the first read names the call, any call's move may be this one's.
            if (frame.kind === 'phone_call' && (!callId.current || frame.id === callId.current)) void read();
        }
    );

    const live = call.state !== 'ended';
    useEffect(() => {
        if (gone) return;
        void read();
    }, [gone, read]);
    useEffect(() => {
        if (gone || !live) return;
        const look = () => void read();
        window.addEventListener('focus', look);
        const timer = window.setInterval(look, BACKSTOP_POLL_MS);
        return () => {
            window.removeEventListener('focus', look);
            window.clearInterval(timer);
        };
    }, [gone, live, read]);

    const hangUp = useCallback(async () => {
        setHangingUp(true);
        try {
            await PhoneNumber.hangUp(target(), { client, user: null });
            // The end arrives as a frame, as any end does.
        } catch (error) {
            setHangingUp(false);
            toast.error(error instanceof Error ? error.message : 'The call couldn’t be hung up');
            // It may have ended without this card hearing it.
            void read();
        }
    }, [client, target, read]);

    return { call, unreadable: unreadable && !call.known, hangUp: () => void hangUp(), hangingUp };
}
