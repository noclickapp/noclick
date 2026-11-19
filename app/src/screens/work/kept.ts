// What Work showed when it was last open in this browser, kept per account the page acts as (whoever shows Work names
// it: one person looking at another's account keeps that account's copy, never their own): the first open paints it
// at once (your spaces, your channels, the newest messages of the ones you were in) and reads it all again behind it,
// as a return to Work within a session does. Your own perspective only: a joined space reads through a session minted
// each visit, and a copy of one would be keyed by that space and whose eyes it reads through.
//
// It keeps what any member of those channels reads, never what's sealed or only yours: no attachment links (signed
// capabilities), no post still going and no note only you see; and a history only while it holds just its newest page,
// so the first read on opening replaces every message kept. Storage that's missing, slow or throwing leaves Work as it
// is without a copy.
import { peekV1, primeV1 } from '@/sdk/useV1';
import type { NoClick } from 'noclick';
import type { ChannelsTransport } from '@/screens/channels/transport';
import type { ChannelMessage } from '@/screens/channels/types';
import { heldBy, hold, type ChannelsHeld } from '@/screens/channels/useChannels';
import { valtioCache } from '@/lib/indexeddb';
import { MINE_KEY, type WorkSpace } from './spaces';
import { keptKey } from './keptKey';

/** Bumped when what's kept changes shape: a copy of another version is dropped. */
export const KEPT_VERSION = 1;
/** The histories kept: the channels most recently active, each only while it holds just its newest page. */
const HISTORIES = 8;
const NEWEST_PAGE = 50;
/** How long Work waits on storage before it opens without a copy. */
const WAIT_MS = 250;

interface KeptWork {
    version: number;
    spaces: WorkSpace[];
    channels: ChannelsHeld;
}


const activity = (c: ChannelsHeld['lists']['channels'][number]) => c.lastMessage?.at ?? c.createdAt;

/** A message as it's kept: its attachments without their links (signed, and read again on opening). */
const keptMessage = (m: ChannelMessage): ChannelMessage => ({ ...m, attachments: m.attachments.map((a) => ({ ...a, url: undefined })) });

/** Puts what Work kept for `account` under its client and own transport, unless this page already holds something. */
export async function restoreWork(account: string, client: NoClick, transport: ChannelsTransport): Promise<void> {
    if (heldBy(transport)) return;
    let kept: KeptWork | null = null;
    try {
        kept = await Promise.race([valtioCache.get<KeptWork>(keptKey(account)), new Promise<null>((resolve) => setTimeout(() => resolve(null), WAIT_MS))]);
    } catch {
        return;
    }
    if (!kept) return;
    if (kept.version !== KEPT_VERSION) {
        void valtioCache.delete(keptKey(account)).catch(() => undefined);
        return;
    }
    hold(transport, kept.channels);
    primeV1(client, MINE_KEY, kept.spaces);
}

/** Keeps what Work holds now for `account`, once its lists and spaces are read. */
export function keepWork(account: string, client: NoClick, transport: ChannelsTransport): void {
    const channels = heldBy(transport);
    const spaces = peekV1<WorkSpace[]>(client, MINE_KEY);
    if (!channels || !spaces || channels.lists.loading || channels.lists.error) return;
    const recent = [...channels.lists.channels]
        .filter((c) => (channels.histories[c.id]?.messages.length ?? NEWEST_PAGE + 1) <= NEWEST_PAGE)
        .sort((a, b) => activity(b).localeCompare(activity(a)))
        .slice(0, HISTORIES);
    const histories = Object.fromEntries(
        recent.map((c) => {
            const h = channels.histories[c.id];
            return [c.id, { ...h, restored: true, messages: h.messages.filter((m) => !m.pending && !m.ephemeral).map(keptMessage) }];
        })
    );
    try {
        // Plain data: IndexedDB clones it.
        const kept: KeptWork = JSON.parse(JSON.stringify({ version: KEPT_VERSION, spaces, channels: { ...channels, histories } }));
        void valtioCache.set<KeptWork>(keptKey(account), kept).catch(() => undefined);
    } catch {
        // Nothing kept: Work opens as it does without a copy.
    }
}
