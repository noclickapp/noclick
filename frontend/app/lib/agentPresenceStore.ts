// Real-time, busy-aware agent presence for the current workflow. The local CLI
// runner publishes before a turn starts and clears in a finally block. This is
// transient per-viewer state, never workflow graph data.

import { proxy } from 'valtio';

export interface AgentPresenceWire {
    nodeId: string;
    conversationKey: string;
    userId: string;
    busy: boolean;
}

export interface NodeAgentPresence {
    /** Live agent processes the relay currently sees for this node (collaborator-inclusive). */
    count: number;
    /** True if any of them is mid-turn. */
    busy: boolean;
}

export const agentPresenceStore = proxy<{
    /** nodeId → live local agent processes for the current relay set. */
    byNode: Record<string, NodeAgentPresence>;
    /** `${nodeId}::${conversationKey}` → whether that turn is busy. */
    byConversation: Record<string, boolean>;
    /** Epoch ms of the last relay set. Presence is authoritative only while
     *  FRESH: deltas are fire-and-forget, and a lost CLEAR would otherwise
     *  leave the last busy snapshot standing forever (2026-09-01 stuck orb).
     *  The relay re-broadcasts while a turn runs, so a genuinely busy agent
     *  keeps this ticking; consumers past the window treat busy as unknown. */
    lastSetAt: number;
}>({
    byNode: {},
    byConversation: {},
    lastSetAt: 0,
});

/** How long a relay set stays authoritative. Comfortably above the relay's
 *  re-broadcast cadence, so only a silence that means "no longer busy" —
 *  or a dead relay connection — ages presence out. */
export const PRESENCE_STALE_MS = 180_000;

export function agentPresenceFresh(now: number = Date.now()): boolean {
    const at = agentPresenceStore.lastSetAt;
    return at > 0 && now - at < PRESENCE_STALE_MS;
}

/** Key into byConversation for one agent node's conversation. */
export function agentPresenceConversationKey(
    nodeId: string,
    conversationKey: string
): string {
    return `${nodeId}::${conversationKey}`;
}

/** Replace the maps from the relay's complete current agent set. Empty input
 *  is authoritative and clears both node counts and conversation busy state. */
export function setAgentPresence(agents: AgentPresenceWire[]): void {
    const byNode: Record<string, NodeAgentPresence> = {};
    const byConversation: Record<string, boolean> = {};
    for (const a of agents) {
        const entry = (byNode[a.nodeId] ??= { count: 0, busy: false });
        entry.count += 1;
        if (a.busy) entry.busy = true;
        if (a.busy && a.conversationKey) {
            byConversation[
                agentPresenceConversationKey(a.nodeId, a.conversationKey)
            ] = true;
        }
    }
    agentPresenceStore.byNode = byNode;
    agentPresenceStore.byConversation = byConversation;
    agentPresenceStore.lastSetAt = Date.now();
}
