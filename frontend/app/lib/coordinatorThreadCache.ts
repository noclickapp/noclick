// The coordinator's thread as this browser last saw it, so opening the chat paints the conversation at once (or the
// empty start, for an account with none) instead of a blank page or a start screen that the history then replaces.
// The persisted history still loads every time and replaces the copy. Per account: the key carries the user's id.
import type { AgentChatMessage } from '~/hooks/useAgentChat';
import { valtioCache } from '~/lib/indexeddb';

/** The newest messages kept: enough to fill the screen; the rest arrives with the history. */
const KEEP = 60;

export interface CachedThread {
    conversationId: string;
    messages: AgentChatMessage[];
}

const key = (userId: string) => `coordinator-thread:${userId}`;

export function readCachedThread(userId: string): Promise<CachedThread | null> {
    return valtioCache.get<CachedThread>(key(userId));
}

/** Keeps the settled turns; a reply still streaming belongs to the live session. */
export function writeCachedThread(userId: string, conversationId: string, messages: readonly AgentChatMessage[]): void {
    // Plain data: a render snapshot is a proxy, which IndexedDB can't clone.
    const settled = JSON.parse(JSON.stringify(messages.filter((m) => m.isComplete).slice(-KEEP))) as AgentChatMessage[];
    void valtioCache.set<CachedThread>(key(userId), { conversationId, messages: settled });
}
