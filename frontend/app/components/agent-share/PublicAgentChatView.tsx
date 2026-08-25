// Client view for the public shared-agent page (/a/{linkId}): a minimal,
// chat-only surface over an anonymous ShareSocket. No settings panel — just
// the agent header (+ tool logos), the shared AgentChatTranscript/Composer,
// and a Powered-by-NoClick badge. Costs bill to the workflow owner backend-side.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { SquarePen } from 'lucide-react';
import { useAgentChat, type AgentChatTransport, type ResumeResponse } from '~/hooks/useAgentChat';
import { useShareSocket } from '~/hooks/useShareSocket';
import { useStickToBottom } from '~/hooks/useStickToBottom';
import { AgentChatTranscript } from '~/components/chat/AgentChatTranscript';
import { AgentChatComposer } from '~/components/chat/AgentChatComposer';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { ToolLogosRow, type ToolLogo } from './ToolLogosRow';
import { PoweredByBadge } from './PoweredByBadge';
import { getOrCreateVisitorId, getChatKey, mintChatKey } from '~/lib/agentShareVisitor';
import {
  SharedAgentSendRequest,
  SharedAgentResumeRequest,
  type SharedAgentAckResponse,
  type SharedAgentResumeResponse,
} from '~/types/socket-events.generated';

const SEND_ERROR_MESSAGES: Record<string, string> = {
  link_inactive: 'This share link is no longer active.',
  busy: 'The agent is still working on the previous message — give it a moment.',
  agent_unavailable: 'This agent is currently unavailable.',
};

// Transport used while the socket / visitor identity is still initializing.
// useAgentChat never calls the transport with a null conversationId, so this
// only exists to keep the hook unconditional.
const NOOP_TRANSPORT: AgentChatTransport = {
  onEvent: () => () => {},
  resume: async () => ({ messages: [] }),
};

export interface PublicAgentMeta {
  workflow_name: string | null;
  owner_name: string | null;
  agent: { label: string; model: string | null };
  tools: { node_type: string; label: string }[];
  conversation_prefix: string;
}

export function PublicAgentChatView({
  linkId,
  meta,
  agentIcon,
  toolLogos,
}: {
  linkId: string;
  meta: PublicAgentMeta;
  agentIcon: { iconHtml: string; iconColor: string } | null;
  toolLogos: ToolLogo[];
}) {
  // Visitor identity is browser-only state — resolve it after mount so the
  // SSR HTML (identity-less) matches the first client render.
  const [visitorId, setVisitorId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState<string | null>(null);
  useEffect(() => {
    setVisitorId(getOrCreateVisitorId());
    setChatKey(getChatKey(linkId));
  }, [linkId]);

  const { socket, status } = useShareSocket(linkId, visitorId ?? '');
  const ready = !!socket && !!visitorId && !!chatKey;

  const conversationId = ready
    ? `${meta.conversation_prefix}:${visitorId}:${chatKey}`
    : null;

  const transport = useMemo<AgentChatTransport>(() => {
    if (!socket || !chatKey) return NOOP_TRANSPORT;
    return {
      onEvent: (event: 'chat:message' | 'agent:state', handler: (data: never) => void) =>
        socket.on(event, handler),
      resume: async (): Promise<ResumeResponse> => {
        const resp = await socket.request<SharedAgentResumeResponse>(
          SharedAgentResumeRequest.create({ chat_key: chatKey }),
        );
        return { messages: (resp?.messages ?? []) as ResumeResponse['messages'] };
      },
    };
  }, [socket, chatKey]);

  const { messages, isStreaming, errorReason, addUserMessage } = useAgentChat(conversationId, transport);
  const { ref: scrollRef, onScroll, pin: pinScroll } = useStickToBottom([messages, isStreaming]);

  const [draft, setDraft] = useState('');
  const [sendError, setSendError] = useState<string | null>(null);

  // The owner running out of credits surfaces as credits:exhausted on this
  // sid — visitors just see "unavailable", never the owner's billing state.
  useEffect(() => {
    if (!socket) return;
    return socket.on('credits:exhausted', () => {
      setSendError(SEND_ERROR_MESSAGES.agent_unavailable);
    });
  }, [socket]);

  const submit = useCallback(() => {
    const text = draft.trim();
    if (!text || !socket || !chatKey || isStreaming) return;
    setSendError(null);
    setDraft('');
    pinScroll();
    void (async () => {
      try {
        const ack = await socket.request<SharedAgentAckResponse>(
          SharedAgentSendRequest.create({ text, chat_key: chatKey }),
        );
        if (ack?.accepted) {
          // Echo only once dispatched — an early echo on a rejected send would
          // leave the hook stuck in streaming with no turn to resolve it.
          addUserMessage(text);
        } else {
          setDraft(text);
          setSendError(SEND_ERROR_MESSAGES[ack?.error ?? ''] ?? 'Something went wrong — try again.');
        }
      } catch {
        setDraft(text);
        setSendError('Connection problem — try again.');
      }
    })();
  }, [draft, socket, chatKey, isStreaming, addUserMessage, pinScroll]);

  const handleNewChat = useCallback(() => {
    setSendError(null);
    setChatKey(mintChatKey(linkId));
  }, [linkId]);

  // h-dvh (not min-h): the page must stay viewport-bounded so the transcript is
  // the ONLY scroll container and the composer stays pinned — min-h let long
  // chats grow the page and scroll the composer away (2026-07-18).
  return (
    <div className="h-dvh overflow-hidden bg-background text-foreground flex flex-col">
      {/* Reconnecting strip. */}
      {ready && status !== 'connected' ? (
        <div className="shrink-0 text-center text-[11px] text-amber-700 dark:text-amber-300/90 bg-amber-100/70 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-900/40 py-1">
          Reconnecting…
        </div>
      ) : null}

      <div className="flex-1 min-h-0 w-full max-w-3xl mx-auto flex flex-col">
        {/* Header: agent identity + tools + new chat. */}
        <div className="px-6 pt-6 pb-4 shrink-0 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              {agentIcon?.iconHtml ? (
                <SerializedIcon html={agentIcon.iconHtml} iconColor={agentIcon.iconColor} className="w-7 h-7 shrink-0" />
              ) : null}
              <h1 className="text-lg font-semibold tracking-tight truncate" data-testid="agent-share-title">
                {meta.agent.label}
              </h1>
            </div>
            <div className="mt-1 text-xs text-muted-foreground/70 dark:text-zinc-500 truncate">
              {[meta.workflow_name, meta.agent.model].filter(Boolean).join(' · ')}
            </div>
            {toolLogos.length > 0 ? (
              <div className="mt-3">
                <ToolLogosRow tools={toolLogos} />
              </div>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleNewChat}
            data-testid="agent-share-new-chat"
            className="shrink-0 inline-flex items-center gap-1.5 text-xs text-muted-foreground dark:text-zinc-300 hover:text-foreground bg-foreground/[0.04] hover:bg-foreground/[0.08] border border-border hover:border-foreground/20 rounded-lg px-2.5 py-1.5 transition-colors"
          >
            <SquarePen className="w-3.5 h-3.5" />
            New chat
          </button>
        </div>

        {/* Transcript. */}
        <div ref={scrollRef} onScroll={onScroll} className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle">
          <div className="px-6 py-4">
            {messages.length === 0 && !isStreaming ? (
              <div className="text-sm text-muted-foreground/70 dark:text-zinc-500 py-8 text-center">
                Say hello — {meta.agent.label} is ready to chat.
              </div>
            ) : null}
            <AgentChatTranscript
              messages={messages}
              isStreaming={isStreaming}
              errorReason={sendError ?? errorReason}
            />
          </div>
        </div>

        {/* Composer — the Powered-by badge shares the hint row, no extra row. */}
        <AgentChatComposer
          value={draft}
          onChange={setDraft}
          onSubmit={submit}
          placeholder={`Message ${meta.agent.label}`}
          inputDisabled={!ready}
          sendDisabled={!draft.trim() || isStreaming || !ready}
          footerEnd={<PoweredByBadge />}
        />
      </div>
    </div>
  );
}
