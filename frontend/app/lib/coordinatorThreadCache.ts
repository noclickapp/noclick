// The coordinator's thread as this browser last saw it, so opening the chat paints the conversation at once (or the
// empty start, for an account with none) instead of a blank page or a start screen that the history then replaces.
// The persisted history still loads every time and replaces the copy. Per account the page acts as: the key carries
// that user's id (a staff member's view-as keeps the viewed account's copy), and a chat of another kind keeps its own
// (`scope`: the coordinator agent's chat on /v1 beside the socket chat it replaced).
//
// It keeps the settled turns' words and the calls they made (their cards), never what's sealed or only yours: no files
// or pictures (their links are signed; they come back with the history), no reasoning or status (live only). A copy of
// another shape is dropped, and storage that's missing, slow or throwing reads as no copy.
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import { valtioCache } from '~/lib/indexeddb';

/** The newest messages kept: enough to fill the screen; the rest arrives with the history. */
const KEEP = 60;
/** Bumped when what's kept changes shape. */
export const CACHED_THREAD_VERSION = 2;
/** How long a page waits on storage before it opens without a copy. */
const WAIT_MS = 250;

export interface CachedThread {
    conversationId: string;
    messages: AgentChatMessage[];
}

interface Stored extends CachedThread {
    version: number;
}

export const cachedThreadKey = (userId: string, scope?: string) => `coordinator-thread:${userId}${scope ? `:${scope}` : ''}`;

export async function readCachedThread(userId: string, scope?: string): Promise<CachedThread | null> {
    const key = cachedThreadKey(userId, scope);
    let stored: Stored | null;
    try {
        stored = await Promise.race([valtioCache.get<Stored>(key), new Promise<null>((resolve) => setTimeout(() => resolve(null), WAIT_MS))]);
    } catch {
        return null;
    }
    if (!stored) return null;
    if (stored.version !== CACHED_THREAD_VERSION) {
        void valtioCache.delete(key).catch(() => undefined);
        return null;
    }
    return { conversationId: stored.conversationId, messages: stored.messages };
}

/** What a kept turn leaves out: its files and pictures (signed links), and what only streamed live. */
const LEFT_OUT = ['attachments', 'content', 'thoughts', 'status'] as const;

/** A settled turn as it's kept. */
function kept(m: AgentChatMessage): AgentChatMessage {
    const copy = { ...m };
    for (const field of LEFT_OUT) delete copy[field];
    return copy;
}

/** Keeps the settled turns; a reply still streaming belongs to the live session. */
export function writeCachedThread(userId: string, conversationId: string, messages: readonly AgentChatMessage[], scope?: string): void {
    try {
        // Plain data: a render snapshot is a proxy, which IndexedDB can't clone.
        const settled = JSON.parse(JSON.stringify(messages.filter((m) => m.isComplete).slice(-KEEP).map(kept))) as AgentChatMessage[];
        void valtioCache.set<Stored>(cachedThreadKey(userId, scope), { version: CACHED_THREAD_VERSION, conversationId, messages: settled }).catch(() => undefined);
    } catch {
        // Nothing kept: the chat opens as it does without a copy.
    }
}
