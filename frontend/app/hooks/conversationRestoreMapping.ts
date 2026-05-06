// Shared mapper from a backend `conversation:resume` response shape to the
// frontend Message[] used by MessagesView. Lives in its own module so two
// callers (useSidebarConversation.resumeConversation for workflow-open
// auto-restore, ChatHistory.handleResumeConversation for the dropdown click)
// can share one source of truth — and so unit tests can drive the mapping
// directly without standing up a hook context.
//
// Pin every persisted-shape → Message-shape decision here. Anything that
// changes how a restored bubble renders should change exactly one function.

import type { Message, EditSegment, AgenticStep, ContentItem } from '~/components/chat/types';

export interface PendingAskPayload {
    ask_id: string;
    title?: string | null;
    inputs: Array<Record<string, unknown>>;
}

export interface PersistedMessage {
    role?: string;
    message?: string;
    /** Inline content blocks (text + image_url) for messages that carry rich content. */
    content?: ContentItem[];
    edit_segments?: EditSegment[];
    edit_steps?: string[];
    /** Both snake_case and camelCase variants exist in older rows. */
    agentic_steps?: AgenticStep[];
    agenticSteps?: AgenticStep[];
    /** Set on the cancelled assistant of a user-cancelled run. */
    cancelled?: boolean;
    /** Set on the paused assistant of a turn that ended on <ask/>. The trailing
     *  assistant of a paused conversation carries this so the FE can surface
     *  the ask drawer on restore — no separate generation snapshot needed. */
    pending_ask?: PendingAskPayload | null;
    /** The brain's view of this turn — needed only for backend resume context;
     *  the FE doesn't need to read it. */
    llm_messages?: unknown;
}

/**
 * Map a single persisted message into a frontend Message.
 *
 * Key invariants:
 *   - `cancelled: true` sets wasInterrupted (renders the "Response interrupted" notice)
 *   - `pending_ask` is forwarded as-is so BuilderInputBridge can surface the
 *     ask drawer when the conversation is restored
 *   - all restored messages are isComplete=true. With <ask/> as a turn boundary
 *     there's no longer an "in-flight" placeholder bubble for paused runs —
 *     the trailing assistant IS the bubble; the ask drawer is a separate UI surface.
 */
export function mapPersistedMessage(msg: PersistedMessage): Message {
    const mapped: Message = {
        text: msg.message || '',
        isUser: msg.role === 'user',
        isComplete: true,
        content: msg.content,
        editSegments: msg.edit_segments,
        editSteps: msg.edit_steps,
        agenticSteps: msg.agentic_steps ?? msg.agenticSteps,
    };
    if (msg.cancelled === true) {
        mapped.wasInterrupted = true;
    }
    if (msg.pending_ask) {
        mapped.pendingAsk = msg.pending_ask;
    }
    return mapped;
}

/** Convenience: map an array of persisted messages. */
export function mapPersistedMessages(msgs: PersistedMessage[] | undefined): Message[] {
    return (msgs || []).map(mapPersistedMessage);
}
