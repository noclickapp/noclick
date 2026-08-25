// Per-agent conversation history for the AgentChatBlock.
//
// Wraps the `conversation:list_for_agent` socket call plus the existing
// `conversation:delete` handler, and exposes refresh / switchTo / deleteOne /
// createNew. Switching writes the chosen conversation_key back to the node
// config (via the caller-provided onConfigChange), which flips the derived
// conversation_id in useAgentChat → that hook reloads the chosen thread.
//
// Refresh is debounced one event-loop tick to coalesce a switch+refresh burst
// after delete/create. The list is cached per (workflow_id, node_id) in
// component state so a remount doesn't refetch from scratch when the user
// just switches tabs and comes back.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  sendEventAsync,
  ListConversationsForAgentRequest,
  DeleteConversationRequest,
} from '~/lib/socket-sender';
import { DEFAULT_INTERFACE_CONV_KEY } from '~/lib/agentChat';

export interface AgentConversationSummary {
  conversation_id: string;
  /** Suffix after the `ck:{wf}:{node}:` prefix — what the user sees. */
  conversation_key: string;
  title: string;
  preview: string;
  /** Model id captured at conversation creation time (e.g. 'codex',
   *  'claude-code', 'openrouter/openai/gpt-4o-mini'). Null for rows
   *  created before the conversations.agent_model column was added. */
  agent_model: string | null;
  last_activity: string;
  created_at: string;
  turn_count: number;
  /** True for visitor threads created via the agent's public share link
   *  (conversation_key starts with `share:`). */
  shared?: boolean;
}

interface ListResponse {
  conversations?: AgentConversationSummary[];
}

export interface UseAgentChatConversationsResult {
  conversations: AgentConversationSummary[];
  isLoading: boolean;
  /** Force a fresh fetch from the server. */
  refresh: () => Promise<void>;
  /** Switch the active thread by writing `key` back to the node config. */
  switchTo: (key: string) => void;
  /** Soft-delete a thread; refreshes the list. If the deleted thread is the
   *  active one, mints a new key so the chat surface immediately moves to a
   *  fresh empty thread. */
  deleteOne: (conv: AgentConversationSummary) => Promise<void>;
  /** Start a new chat. Mints a fresh conversation_key and persists it. */
  createNew: () => string;
}

function freshKey(): string {
  const suffix = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 8)
    : String(Date.now());
  return `${DEFAULT_INTERFACE_CONV_KEY}_${suffix}`;
}

export function useAgentChatConversations(
  workflowId: string | null | undefined,
  nodeId: string,
  /** Current conversation_key on the agent node config (the active thread). */
  activeKey: string | undefined,
  /** Patch the agent node config — used by switchTo/createNew to write the
   *  new conversation_key back. */
  onSetConversationKey: (key: string) => void,
): UseAgentChatConversationsResult {
  const [conversations, setConversations] = useState<AgentConversationSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const loadedForRef = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    if (!workflowId || !nodeId) return;
    setIsLoading(true);
    try {
      const resp = (await sendEventAsync(
        ListConversationsForAgentRequest.create({
          workflow_id: workflowId,
          node_id: nodeId,
        }),
      )) as ListResponse;
      setConversations(Array.isArray(resp.conversations) ? resp.conversations : []);
    } catch (err) {
      console.warn('[useAgentChatConversations] list failed', err);
    } finally {
      setIsLoading(false);
    }
  }, [workflowId, nodeId]);

  // Initial fetch when the (workflow, node) pair changes.
  useEffect(() => {
    if (!workflowId || !nodeId) return;
    const key = `${workflowId}:${nodeId}`;
    if (loadedForRef.current === key) return;
    loadedForRef.current = key;
    void refresh();
  }, [workflowId, nodeId, refresh]);

  const switchTo = useCallback((key: string) => {
    onSetConversationKey(key);
  }, [onSetConversationKey]);

  const createNew = useCallback((): string => {
    const key = freshKey();
    onSetConversationKey(key);
    // The DB row is only written on the first send (no events = no row), so
    // we don't refetch here. The popover's open-handler refreshes the list,
    // which is when the new thread will become visible.
    return key;
  }, [onSetConversationKey]);

  const deleteOne = useCallback(async (conv: AgentConversationSummary) => {
    try {
      await sendEventAsync(
        DeleteConversationRequest.create({ conversation_id: conv.conversation_id }),
      );
    } catch (err) {
      console.warn('[useAgentChatConversations] delete failed', err);
      return;
    }
    // Remove locally for instant feedback then refresh from server.
    setConversations(prev => prev.filter(c => c.conversation_id !== conv.conversation_id));
    if (conv.conversation_key === activeKey) {
      // Deleted the active thread — move to a fresh one.
      onSetConversationKey(freshKey());
    }
    void refresh();
  }, [activeKey, onSetConversationKey, refresh]);

  // Memoize the return so consumers don't see new object identities on every
  // render (helps stable useEffect deps).
  return useMemo(
    () => ({ conversations, isLoading, refresh, switchTo, deleteOne, createNew }),
    [conversations, isLoading, refresh, switchTo, deleteOne, createNew],
  );
}
