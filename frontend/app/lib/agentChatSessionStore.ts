// Per-conversation agent-chat session state (messages, streaming flag, error,
// terminal watermark) in a module-level valtio proxy, so the live transcript —
// including mid-turn status/step timelines — survives the chat surface
// unmounting (Interface ↔ Workflow tab switches used to erase in-progress
// lines). Volatile by design: session-only, never persisted to disk.

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
}

const emptySession = (): AgentChatSession => ({
  messages: [],
  isStreaming: false,
  errorReason: null,
  lastFinishedAt: 0,
  resumedOnce: false,
});

export const agentChatSessionStore = proxy<{
  sessions: Record<string, AgentChatSession>;
}>({ sessions: {} });

/** The LIVE (mutable) session for a conversation, created on first touch. */
export function getAgentChatSession(conversationId: string): AgentChatSession {
  return (agentChatSessionStore.sessions[conversationId] ??= emptySession());
}

/** Test isolation — the store is module-level state. */
export function resetAgentChatSessions(): void {
  agentChatSessionStore.sessions = {};
}
