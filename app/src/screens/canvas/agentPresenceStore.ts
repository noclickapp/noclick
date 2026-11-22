// Real-time, busy-aware agent-sandbox presence for the current workflow: which agent
// steps have a sandbox running and which are mid-turn, as whoever renders the canvas
// pushes it (the sandboxes' heartbeats, relayed to the workflow's viewers). Kept in a
// valtio proxy (NOT node.data): it's a transient per-viewer signal. Nothing pushes it
// where nothing relays heartbeats, and the canvas then reads an agent's turn by its
// stored output alone (agentRunState.ts).

import { proxy } from 'valtio';

export interface AgentPresenceWire {
    nodeId: string;
    conversationKey: string;
    userId: string;
    busy: boolean;
}

export interface NodeAgentPresence {
    /** Live sandboxes presence currently sees for this node (collaborator-inclusive). */
    count: number;
    /** True if any of them is mid-turn. */
    busy: boolean;
}

export const agentPresenceStore = proxy<{
    /** nodeId → live presence. A node stays here at count 0 once presence has reported
     *  it, so the badge honors its real-time "reaped" (count 0) instead of falling
     *  back to a slower poll. */
    byNode: Record<string, NodeAgentPresence>;
    /** `${nodeId}::${conversationKey}` → mid-turn. Conversation-scoped busy for
     *  chat surfaces (a node can run several conversations; the interface chat
     *  must only react to its own). Absence means "not busy" — rebuilt fresh
     *  from each snapshot, no reaped-tombstone semantics needed. */
    byConversation: Record<string, boolean>;
    /** Epoch ms of the last set. Presence is authoritative only while FRESH: a
     *  sandbox that dies uncleanly sends no last heartbeat, and the last snapshot —
     *  count 1, maybe busy — would otherwise stay authoritative forever. Consumers
     *  past the staleness window fall back to a slower poll that heals itself. */
    lastSetAt: number;
}>({
    byNode: {},
    byConversation: {},
    lastSetAt: 0,
});

/** How long a set stays authoritative. Generous (heartbeats are frequent but only
 *  changes are pushed, so a quiet warm sandbox produces no
 *  traffic) — this bounds a stale badge at minutes instead of forever. */
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

/** Replace the map from presence's full agent set (each snapshot/delta is complete).
 *  Nodes presence has ALREADY reported are kept at count 0 when they drop out of the
 *  set: presence is authoritative for them, so their absence means "sandbox reaped",
 *  not "no info". Without this, an agent's badge would fall back to a slower poll
 *  and linger after its sandbox reaps. */
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
    for (const nodeId of Object.keys(agentPresenceStore.byNode)) {
        byNode[nodeId] ??= { count: 0, busy: false };
    }
    agentPresenceStore.byNode = byNode;
    agentPresenceStore.byConversation = byConversation;
    agentPresenceStore.lastSetAt = Date.now();
}
