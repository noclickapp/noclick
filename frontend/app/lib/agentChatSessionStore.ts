// Per-conversation agent-chat session state (messages, streaming flag, error,
// terminal watermark) in a module-level valtio proxy, so the live transcript —
// including mid-turn status/step timelines — survives the chat surface
// unmounting (Interface ↔ Workflow tab switches used to erase in-progress
// lines). Volatile by design: a surface that keeps a copy on disk seeds it
// back with seedAgentChatSession, and the persisted history replaces it.

import { proxy } from 'valtio';

import type { AgentChatMessage } from '~/hooks/useAgentChat';

export interface AgentChatSession {
    messages: AgentChatMessage[];
    isStreaming: boolean;
    errorReason: string | null;
    /** Epoch ms of the most recent terminal signal (finished frame / terminal
     *  agent:state / reconciler adoption); 0 if none. */
    lastFinishedAt: number;
    /** Whether the persisted-history cold fetch has completed once for this
     *  conversation — a remount with a live session must NOT reset and refetch
     *  (that was the erasure), it restores instantly and lets the reconcile
     *  poll heal any frames missed while unmounted. */
    resumedOnce: boolean;
    /** A turn that came in on another app (a text, a call, an email) is
     *  running: this chat follows it and reads the saved turn back at its end. */
    turnElsewhere: boolean;
    /** The persisted-history fetch failed; null once one succeeds. */
    resumeError: string | null;
    /** How many of `messages`, from the start, are a cached copy shown until the persisted history lands. */
    cached: number;
}

const emptySession = (): AgentChatSession => ({
    messages: [],
    isStreaming: false,
    errorReason: null,
    lastFinishedAt: 0,
    resumedOnce: false,
    turnElsewhere: false,
    resumeError: null,
    cached: 0,
});

export const agentChatSessionStore = proxy<{
    sessions: Record<string, AgentChatSession>;
}>({ sessions: {} });

/** The LIVE (mutable) session for a conversation, created on first touch. */
export function getAgentChatSession(conversationId: string): AgentChatSession {
    // Read back AFTER assigning, deliberately. `x ??= y` evaluates to y — the
    // RAW object — so the FIRST touch of a conversation used to hand out an
    // unproxied session, and every mutation through it was invisible to valtio.
    // Existing sessions returned the proxy, which is why this only ever bit the
    // first write to a brand-new conversation: it landed in the store but
    // rendered nothing until some unrelated re-render happened to pick it up.
    if (!agentChatSessionStore.sessions[conversationId]) {
        agentChatSessionStore.sessions[conversationId] = emptySession();
    }
    return agentChatSessionStore.sessions[conversationId];
}

/** Show a cached copy of a conversation until its persisted history lands; a no-op once the session holds anything. */
export function seedAgentChatSession(conversationId: string, messages: AgentChatMessage[]): void {
    const session = getAgentChatSession(conversationId);
    if (session.resumedOnce || session.isStreaming || session.messages.length > 0 || messages.length === 0) return;
    session.messages = messages;
    session.cached = messages.length;
}

/** Test isolation — the store is module-level state. */
export function resetAgentChatSessions(): void {
    agentChatSessionStore.sessions = {};
}
