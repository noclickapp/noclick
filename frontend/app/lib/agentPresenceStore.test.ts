// Unit tests for aggregating the relay's complete local-agent presence set.

import { describe, it, expect, beforeEach } from 'vitest';
import { agentPresenceStore, agentPresenceConversationKey, setAgentPresence, agentPresenceFresh, PRESENCE_STALE_MS } from './agentPresenceStore';

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

    it('clears node presence when the relay reports an empty set', () => {
        setAgentPresence([{ nodeId: 'a', conversationKey: 'c1', userId: 'u', busy: true }]);
        expect(agentPresenceStore.byNode.a.busy).toBe(true);
        setAgentPresence([]);
        expect(agentPresenceStore.byNode.a).toBeUndefined();
    });

    it('never invents entries for nodes the relay has not reported', () => {
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


describe('agentPresenceFresh', () => {
    it('goes stale when the relay falls silent', () => {
        setAgentPresence([
            { nodeId: 'n1', conversationKey: 'ck', userId: 'u', busy: true },
        ]);
        expect(agentPresenceFresh()).toBe(true);
        // A set older than the window is no longer authoritative — a lost
        // clear delta must age out instead of pinning the indicator forever.
        expect(
            agentPresenceFresh(Date.now() + PRESENCE_STALE_MS + 1)
        ).toBe(false);
    });
});
