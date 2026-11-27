// What Work showed when it was last open in this browser, kept per account the page acts as (@/lib/kept): the first
// open paints it at once (your spaces, your channels, the newest messages of the ones you were in) and reads it all
// again behind it, as a return to Work within a session does. Your own perspective only: a joined space reads through a
// session minted each visit, and a copy of one would be keyed by that space and whose eyes it reads through.
//
// It keeps what any member of those channels reads, never what's sealed or only yours: no attachment links (signed
// capabilities), no post still going and no note only you see; and a history only while it holds just its newest page,
// so the first read on opening replaces every message kept.
import { peekV1, primeV1 } from '@/sdk/useV1';
import type { NoClick } from 'noclick';
import type { ChannelsTransport } from '@/screens/channels/transport';
import type { ChannelMessage } from '@/screens/channels/types';
import { heldBy, hold, type ChannelsHeld } from '@/screens/channels/useChannels';
import { keepFor, readKept } from '@/lib/kept';
import { MINE_KEY, type WorkSpace } from './spaces';

/** Bumped when what's kept changes shape: a copy of another version is dropped. */
export const KEPT_VERSION = 1;
/** The histories kept: the channels most recently active, each only while it holds just its newest page. */
const HISTORIES = 8;
const NEWEST_PAGE = 50;

interface KeptWork {
    spaces: WorkSpace[];
    channels: ChannelsHeld;
}

const activity = (c: ChannelsHeld['lists']['channels'][number]) => c.lastMessage?.at ?? c.createdAt;

/** A message as it's kept: its attachments without their links (signed, and read again on opening). */
const keptMessage = (m: ChannelMessage): ChannelMessage => ({ ...m, attachments: m.attachments.map((a) => ({ ...a, url: undefined })) });

/** Puts what Work kept for `account` under its client and own transport, unless this page already holds something. */
export async function restoreWork(account: string, client: NoClick, transport: ChannelsTransport): Promise<void> {
    if (heldBy(transport)) return;
    const kept = await readKept<KeptWork>(account, 'work', KEPT_VERSION);
    if (!kept) return;
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
        keepFor<KeptWork>(account, 'work', KEPT_VERSION, JSON.parse(JSON.stringify({ spaces, channels: { ...channels, histories } })));
    } catch {
        // Nothing kept: Work opens as it does without a copy.
    }
}
