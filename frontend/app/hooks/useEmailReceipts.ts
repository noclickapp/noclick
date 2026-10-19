// What became of the emails that carried the coordinator's replies, kept live: a reply's event is read with its
// receipt as it stood (usually still sending, as the turn is saved before the email goes), and each move after that
// (sent, delivered, bounced, couldn't send) arrives as a coordinator:email_reply frame on the owner's user room.
// A receipt only moves forward, so a frame and a read that land in either order settle on the furthest one.
import { useState } from 'react';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import type { CoordinatorEmailReply } from '~/types/socket-events.generated';

const RANK: Record<CoordinatorEmailReply['state'], number> = { sending: 0, sent: 1, delayed: 2, delivered: 3, bounced: 3, failed: 3, unknown: 3 };

/** A send that never reported back (its process stopped mid-send) stays "sending" on the record: past this, the
 *  chat stops saying it's sending and says it can't confirm it. */
export const SENDING_STALE_MS = 5 * 60 * 1000;

/** The further along of two copies of one receipt. */
export function furthest(a: CoordinatorEmailReply | undefined, b: CoordinatorEmailReply | undefined): CoordinatorEmailReply | undefined {
    if (!a || !b) return a ?? b;
    return RANK[b.state] > RANK[a.state] ? b : a;
}

/** How a receipt reads now: one still sending well after its reply was saved never finished saying how it went. */
export function receiptState(receipt: CoordinatorEmailReply, savedAt: number | undefined, now = Date.now()): CoordinatorEmailReply['state'] {
    return receipt.state === 'sending' && savedAt !== undefined && now - savedAt > SENDING_STALE_MS ? 'unknown' : receipt.state;
}

/** The receipts the frames moved since this chat opened, by id (each reply's own), to lay over what its messages
 *  were read with. */
export function useEmailReceipts(): Record<string, CoordinatorEmailReply> {
    const [moved, setMoved] = useState<Record<string, CoordinatorEmailReply>>({});
    useSocketEvent('coordinator:email_reply', ({ reply }) => {
        setMoved((known) => {
            const next = furthest(known[reply.id], reply)!;
            return next === known[reply.id] ? known : { ...known, [reply.id]: next };
        });
    });
    return moved;
}
