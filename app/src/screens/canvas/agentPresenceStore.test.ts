// Unit tests for setAgentPresence — aggregating presence's full agent set (each
// snapshot/delta is complete) into per-node {count, busy} the canvas badge reads.

import { describe, it, expect, beforeEach } from 'vitest';
import { agentPresenceStore, agentPresenceConversationKey, setAgentPresence } from './agentPresenceStore';

describe('setAgentPresence', () => {
    beforeEach(() => {
        agentPresenceStore.byNode = {};
        agentPresenceStore.byConversation = {};
    });

    it('aggregates count + busy per node', () => {
        setAgentPresence([
            { nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: false },
            { nodeId: 'a', conversationKey: 'c2', userId: 'u', busy: true },
            { nodeId: 'b', conversationKey: 'c3', userId: 'u', busy: false },
        ]);
        expect(agentPresenceStore.byNode.a).toEqual({ count: 2, busy: true }); // any busy → busy
        expect(agentPresenceStore.byNode.b).toEqual({ count: 1, busy: false });
    });

    it('keeps a reported node at count 0 when its sandbox reaps', () => {
        // Dropping the node's entry entirely made an agent's badge fall back to a
        // slower poll, so it lingered after a clean reap. The node stays at count 0
        // so the badge honors the instant removal.
        setAgentPresence([{ nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: true }]);
        expect(agentPresenceStore.byNode.a.busy).toBe(true);
        setAgentPresence([]); // all sandboxes gone (a reduced set pushed)
        expect(agentPresenceStore.byNode.a).toEqual({ count: 0, busy: false });
    });

    it('never invents entries for nodes presence has not reported', () => {
        setAgentPresence([]);
        expect(agentPresenceStore.byNode.neverSeen).toBeUndefined();
    });

    it('tracks busy per (node, conversation) for chat surfaces', () => {
        setAgentPresence([
            { nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: true },
            { nodeId: 'a', conversationKey: 'c2', userId: 'u', busy: false },
        ]);
        expect(agentPresenceStore.byConversation[agentPresenceConversationKey('a', 'c1')]).toBe(true);
        // Idle and unreported conversations are simply absent — falsy either way.
        expect(agentPresenceStore.byConversation[agentPresenceConversationKey('a', 'c2')]).toBeUndefined();
        expect(agentPresenceStore.byConversation[agentPresenceConversationKey('b', 'c9')]).toBeUndefined();
    });

    it('clears conversation busy when the next snapshot drops it (turn finished / reaped)', () => {
        setAgentPresence([{ nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: true }]);
        expect(agentPresenceStore.byConversation[agentPresenceConversationKey('a', 'c1')]).toBe(true);
        setAgentPresence([{ nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: false }]);
        expect(agentPresenceStore.byConversation[agentPresenceConversationKey('a', 'c1')]).toBeUndefined();
    });
});
