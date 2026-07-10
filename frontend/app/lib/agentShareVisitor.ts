// Per-browser identity for public shared-agent pages (/a/{linkId}): a stable
// visitor uuid (one per browser, shared across links) plus a per-link chat key
// so "New chat" can start a fresh thread while the visitor id stays stable.
// Both live in localStorage — the backend keys the visitor's conversation as
// share:{link_id}:{visitor_id}:{chat_key}.

const VISITOR_KEY = 'noclick_agent_share_visitor';
const CHAT_KEY_PREFIX = 'noclick_agent_share_chat:';
export const DEFAULT_CHAT_KEY = 'main';

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode — identity becomes per-pageview, which still works */
  }
}

export function getOrCreateVisitorId(): string {
  const existing = safeGet(VISITOR_KEY);
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  safeSet(VISITOR_KEY, fresh);
  return fresh;
}

export function getChatKey(linkId: string): string {
  return safeGet(CHAT_KEY_PREFIX + linkId) || DEFAULT_CHAT_KEY;
}

/** Mint a fresh thread key for this link ("New chat"). 8-char uuid slice —
 *  mirrors useAgentChatConversations.freshKey and fits the backend's
 *  ^[a-zA-Z0-9_-]{1,32}$ chat_key validation. */
export function mintChatKey(linkId: string): string {
  const fresh = crypto.randomUUID().slice(0, 8);
  safeSet(CHAT_KEY_PREFIX + linkId, fresh);
  return fresh;
}
