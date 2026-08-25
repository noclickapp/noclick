// Live message state for the AgentChatBlock (Interface tab chat).
//
// Why this exists: the workflow-builder chat surfaces in NoClick.tsx use
// `useConversation`, which reads live state from `activeGenStore`. That store
// is wired to the agentic-builder event stream (`active_gen:*`) — it does NOT
// listen to the per-event `chat:message` channel the regular agent node emits
// when run via WorkflowExecuteRequest. So an interface-tab chat send produces
// `chat:message` events that nothing renders. This hook fills that gap.
//
// Responsibilities:
//   • Listen to incoming `chat:message` events filtered by conversation_id.
//   • Accumulate streamed text into the in-flight agent bubble; close it when
//     `finished: true` lands.
//   • Provide `addUserMessage` so the caller can show the user's send
//     optimistically (the backend doesn't echo user messages over the wire).
//   • Cold-fetch persisted history via `conversation:resume` on conversation_id
//     change so reload restores the thread.

import { useCallback, useEffect, useRef } from 'react';
import { useSnapshot } from 'valtio';
import { onSocketEvent } from '~/lib/socket-receiver';
import { splitCarryOverContext } from '~/lib/agentChat';
import { sendEventAsync, ResumeConversationRequest } from '~/lib/socket-sender';
import {
    agentChatSessionStore,
    getAgentChatSession,
} from '~/lib/agentChatSessionStore';
import type {
    ChatMessageEvent,
    AgentStateEvent,
} from '~/types/socket-events.generated';
import type { AgenticStep, ContentItem } from '~/types/socket-schema.generated';

/** Agent states that mean "the run is over — stop showing the streaming
 *  indicator". An agent that hits a rate limit / hard error / user stop will
 *  not emit a finished:true chat:message; the only signal is the agent:state
 *  transition. Without listening to this, the UI gets stuck in streaming. */
const TERMINAL_AGENT_STATES = new Set([
    'stopped',
    'finished',
    'error',
    'rejected',
    'paused', // user-initiated; resume would lift the indicator anyway
]);

/** Collapse consecutive identical terminal-error bubbles into one. The live
 *  agent:state error (appended) and the persisted action:error (prepended by
 *  resume) are the SAME failure; if a relay redelivery lands one during the
 *  resume window they can both end up in the list (2026-07-09 duplicate error
 *  on tab-switch). Order-independent, so it fixes either arrival sequence. */
export function dedupeConsecutiveErrors(
    msgs: AgentChatMessage[]
): AgentChatMessage[] {
    const out: AgentChatMessage[] = [];
    for (const m of msgs) {
        const prev = out[out.length - 1];
        if (
            m.error &&
            prev &&
            prev.error === m.error &&
            !prev.isUser &&
            !m.isUser
        )
            continue;
        out.push(m);
    }
    return out;
}

// Relay-independent reconciler cadence (see the streaming effect below). Grace
// lets the fast relay path resolve the common case before the first poll; the
// interval bounds how long a lost relay frame can leave the chat stuck.
const RECONCILE_GRACE_MS = 6000;
const RECONCILE_INTERVAL_MS = 5000;

/** One row of a turn's live activity timeline. Tool rows come from
 *  ChatMessageEvent.agentic_steps (the SDK agent's tool frames and the local
 *  CLI harness's turn-scoped MCP endpoint);
 *  status rows are folded in from ChatMessageEvent.status milestones
 *  ("Starting sandbox…"). id-keyed so a completion frame updates its
 *  in_progress row in place. */
export interface AgentChatStep {
    id: string;
    /** First-seen label — "Calling linear__create_issue({…})" / "Starting sandbox…". */
    title: string;
    /** Result preview delivered by the completion frame (tool rows only). */
    detail?: string;
    status: 'in_progress' | 'completed';
    kind: 'status' | 'tool';
    startedAt: number;
    endedAt?: number;
}

/** A non-image file attached to a user turn — rendered as a chip linking to
 *  the permanent R2 URL. Images ride `content` as image_url items instead. */
export interface AgentChatFileAttachment {
    name: string;
    url: string;
    mimeType?: string;
}

export interface AgentChatMessage {
    isUser: boolean;
    text: string;
    isComplete: boolean;
    /** Replayed from the thread this conversation carried over when the agent's
     *  model changed. A real turn, just not one that happened here. */
    carriedOver?: boolean;
    content?: ContentItem[];
    /** Files the user attached to this turn (non-image — see above). */
    attachments?: AgentChatFileAttachment[];
    /** In-flight status emitted by the agent (e.g. "Starting sandbox…"). Only
     *  meaningful while the bubble is still streaming; cleared once text or
     *  content lands. Used by the UI to give the user feedback during long
     *  runtime startup windows. */
    status?: string;
    /** Live activity timeline for this turn (status milestones + tool calls).
     *  Not persisted — present only on bubbles built from live frames. */
    steps?: AgentChatStep[];
    /** Set when this bubble represents a terminal-state error (rate limit,
     *  provider 4xx, CLI exec failure, …). The chat renders it as a red inline
     *  banner instead of a normal agent reply. When set, `text` is empty. */
    error?: string;
    /** Approval card for the agent's prompt_builder tool call (interactive chats
     *  only). When set, the message renders as an approve/dismiss card instead
     *  of a text bubble; `text` is empty. Not persisted — live-session only. */
    builderPrompt?: BuilderPromptProposal;
}

/** Payload of ChatMessageEvent.builder_prompt — the agent's proposed builder
 *  edit awaiting user approval. */
export interface BuilderPromptProposal {
    prompt: string;
    node_id?: string | null;
    /** Server-minted per-proposal id; dedupes event relay redeliveries. */
    proposal_id?: string | null;
    /** What approval actually submits to the builder: `prompt` anchored to the
     *  requesting agent node, so a multi-agent workflow can't misroute the
     *  edit. The card displays `prompt`; falls back to it when absent. */
    anchored_prompt?: string | null;
    /** The user's persisted verdict, restored from the transcript's
     *  `builder_decision` events — the cross-device source of truth the card
     *  prefers over its localStorage fallback. */
    decision?: 'approved' | 'dismissed' | null;
}

export interface UseAgentChatResult {
    messages: AgentChatMessage[];
    isStreaming: boolean;
    /** Last terminal-state reason from the agent (rate-limit, exception, …). Null
     *  while streaming or on clean completion. Cleared on the next user send. */
    errorReason: string | null;
    /** Append a user message to the transcript (optimistic — the backend does
     *  not echo user messages over chat:message). `content` carries attached
     *  images as image_url items; `attachments` the non-image file chips. */
    addUserMessage: (
        text: string,
        content?: ContentItem[],
        attachments?: AgentChatFileAttachment[]
    ) => void;
    /** Epoch ms of the most recent terminal signal seen for this conversation
     *  (finished frame / terminal agent:state / reconciler adoption); 0 if none.
     *  Lets the caller suppress the presence-driven working indicator right
     *  after a turn ends — the busy beat can lag a finished turn by up to a
     *  heartbeat interval (~15s). */
    lastFinishedAt: number;
}

/** Persisted-event row stored on conversations.events. The fields we care
 *  about for the chat-surface restore — agent-side and user-side message
 *  actions. Everything else (system prompt, recall, think, env observations)
 *  is internal machinery and not rendered in the transcript. */
interface PersistedEvent {
    id?: number;
    /** Legacy action/source shape — pre-Phase-9 events written by the previous
     *  OpenHands-era PostgresStore. Still present in older conversations.events rows. */
    action?: string;
    /** Set on observation events (vs. action events). State transitions and
     *  terminal errors arrive as `observation: 'agent_state_changed'`. */
    observation?: string;
    source?: string;
    message?: string;
    args?: {
        content?: string;
        image_urls?: string[] | null;
        file_urls?: string[] | null;
        /** For agent_state_changed observations. */
        agent_state?: string;
        reason?: string;
        [key: string]: unknown;
    } | null;
    timestamp?: string;
    /** Post-Phase-9 shape (what agent_node._persist_interface_chat_event +
     *  agent_handler._persist_chat_event write). Same shape WorkflowBuilder's
     *  _save_conversation has always used. New chats land in this shape; old
     *  chats from the pre-Phase-9 era land in the {action, source, args} shape
     *  above. The mapper accepts both. */
    role?: string;
    /** Set on assistant events to flag a terminal error / cancelled run.
     *  Renders the "Response interrupted" bubble. */
    cancelled?: boolean;
    /** Media on a turn, persisted via agent_node._persist_interface_chat_event:
     *  generated media on assistant turns (image / video / kling fast-path
     *  handlers + image-generating LLM tools) and user-attached images on user
     *  turns. Restored as image_url / video_url content items so reload shows
     *  the media. */
    image_urls?: string[] | null;
    video_urls?: string[] | null;
    /** Non-image files the user attached to a user turn — restored as chips
     *  on the bubble. */
    attachments?: { name?: string; url?: string; mime_type?: string }[] | null;
    /** Compacted tool timeline persisted with a CLI turn's assistant event
     *  (tool_call_log.compact_tool_calls_for_transcript) — restored as the
     *  bubble's step rows so the activity timeline survives reloads. */
    tool_calls?: unknown;
    /** prompt_builder approval card persisted mid-turn (platform_tools) —
     *  restored as a card message so reconcile adoption / reload keep it. */
    builder_prompt?: BuilderPromptProposal | null;
}

/** Rebuild a restored bubble's step rows from its persisted tool timeline.
 *  Titles are synthesized in the live wire's "Calling {tool}({args})" format
 *  so the renderer's humanizer/expander treat restored and live rows alike. */
function stepsFromPersistedToolCalls(
    raw: unknown
): AgentChatStep[] | undefined {
    if (!Array.isArray(raw) || raw.length === 0) return undefined;
    const steps: AgentChatStep[] = [];
    raw.forEach((t, i) => {
        if (!t || typeof t !== 'object') return;
        const tc = t as {
            tool_name?: string;
            arguments_preview?: string;
            result_preview?: string | null;
            duration_ms?: number | null;
            created_at?: string | null;
        };
        if (!tc.tool_name) return;
        const endedAt = tc.created_at ? Date.parse(tc.created_at) : NaN;
        const durationMs =
            typeof tc.duration_ms === 'number' ? tc.duration_ms : 0;
        const hasTime = Number.isFinite(endedAt);
        steps.push({
            id: `restored-${i}`,
            title: `Calling ${tc.tool_name}(${tc.arguments_preview ?? ''})`,
            detail: tc.result_preview || undefined,
            status: 'completed',
            kind: 'tool',
            startedAt: hasTime ? endedAt - durationMs : 0,
            ...(hasTime ? { endedAt } : {}),
        });
    });
    return steps.length ? steps : undefined;
}

export interface ResumeResponse {
    session_id?: string;
    messages?: PersistedEvent[];
    workflow_id?: string | null;
}

/** Pluggable event/resume transport so the hook can run over a socket other
 *  than the authenticated app singleton. The default delegates to the
 *  singleton (byte-identical to the pre-transport behavior); the public
 *  shared-agent page supplies one backed by its anonymous ShareSocket, whose
 *  resume maps to shared_agent:resume. */
export interface AgentChatTransport {
    onEvent(
        event: 'chat:message',
        handler: (data: ChatMessageEvent) => void
    ): () => void;
    onEvent(
        event: 'agent:state',
        handler: (data: AgentStateEvent) => void
    ): () => void;
    resume(conversationId: string): Promise<ResumeResponse>;
}

const defaultTransport: AgentChatTransport = {
    onEvent: (
        event: 'chat:message' | 'agent:state',
        handler: (data: never) => void
    ) => onSocketEvent(event, handler as never),
    resume: async (conversationId: string) =>
        (await sendEventAsync(
            ResumeConversationRequest.create({ session_id: conversationId })
        )) as ResumeResponse,
};

/** User-side `message:user` events are stored with a JSON-encoded multimodal
 *  payload wrapped in `__NOCLICK_SEQUENCE__:[...]`. Unwrap it to plain text +
 *  content[] so the bubble renders correctly on restore. */
const NOCLICK_SEQUENCE_PREFIX = '__NOCLICK_SEQUENCE__:';

interface NoClickSequenceItem {
    type: 'text' | 'image_url';
    text?: string | null;
    image_url?: string | { url?: string } | null;
}

function decodeNoClickSequence(raw: string): {
    text: string;
    content?: ContentItem[];
} {
    if (!raw.startsWith(NOCLICK_SEQUENCE_PREFIX)) {
        return { text: raw };
    }
    const json = raw.slice(NOCLICK_SEQUENCE_PREFIX.length);
    try {
        const items = JSON.parse(json) as NoClickSequenceItem[];
        const textParts: string[] = [];
        const content: ContentItem[] = [];
        for (const it of items) {
            if (it.type === 'text' && it.text) {
                textParts.push(it.text);
                content.push({ type: 'text', text: it.text });
            } else if (it.type === 'image_url' && it.image_url) {
                const url =
                    typeof it.image_url === 'string'
                        ? it.image_url
                        : it.image_url.url;
                if (url)
                    content.push({ type: 'image_url', image_url: { url } });
            }
        }
        return {
            text: textParts.join(''),
            content: content.length > 0 ? content : undefined,
        };
    } catch {
        return { text: raw };
    }
}

/** Build image_url/video_url content items from an assistant event's
 *  persisted media URL lists (image / video / kling generation). Returns
 *  undefined when the turn carried no generated media. */
function mediaContentFromEvent(ev: PersistedEvent): ContentItem[] | undefined {
    const content: ContentItem[] = [];
    if (Array.isArray(ev.image_urls)) {
        for (const url of ev.image_urls) {
            if (url) content.push({ type: 'image_url', image_url: { url } });
        }
    }
    if (Array.isArray(ev.video_urls)) {
        for (const url of ev.video_urls) {
            if (url) content.push({ type: 'video_url', video_url: url });
        }
    }
    return content.length > 0 ? content : undefined;
}

/** File chips from a user event's persisted `attachments` (non-image files
 *  the user attached; images ride image_urls → content instead). */
function fileAttachmentsFromEvent(
    ev: PersistedEvent
): AgentChatFileAttachment[] | undefined {
    if (!Array.isArray(ev.attachments)) return undefined;
    const out: AgentChatFileAttachment[] = [];
    for (const f of ev.attachments) {
        if (!f?.url) continue;
        out.push({
            name: f.name || f.url.split('/').pop() || 'file',
            url: f.url,
            mimeType: f.mime_type ?? undefined,
        });
    }
    return out.length > 0 ? out : undefined;
}

/** Convert persisted conversation events into chat-surface transcript bubbles.
 *  Two event shapes flow into this — both are accepted so old chats written
 *  under the pre-Phase-9 PostgresStore continue to restore alongside chats
 *  started under the in-process LLM agent wrapper at coder/openai_agent/.
 *
 *  Post-Phase-9 shape (what agent_node + agent_handler write today):
 *    - `{role: 'user', message}` → user bubble
 *    - `{role: 'assistant', message}` → agent bubble
 *    - `{role: 'assistant', message, cancelled: true}` → error/interrupted bubble
 *
 *  Pre-Phase-9 legacy shape (still present in old conversations.events rows):
 *    - `action: 'message'` + source user/agent → regular bubble
 *    - `observation: 'agent_state_changed'` with state error/rejected → error bubble
 *    - `action: 'error'` → error bubble (CLI handlers' persist_agent_error)
 *
 *  Everything else is internal machinery and is dropped. Exported for unit
 *  testing. */
/** Normalize any error payload into a human-readable string. Backends emit
 *  plain strings, but harness errors can arrive as structured objects (codex:
 *  `{message: '<json blob>', codexErrorInfo, ...}` whose message is ANOTHER
 *  JSON envelope) — interpolating those rendered "Agent stopped: [object
 *  Object]". Digs through message/error/reason envelopes and JSON-encoded
 *  strings until it finds prose. */
/** Recursive text dig WITHOUT a stringify fallback — returns null when a
 *  branch holds no prose, so junk objects (e.g. litellm `metadata` carrying
 *  only provider_name/is_byok) can't shadow a real message on a sibling key.
 *  Key order matters: `raw` (the provider's verbatim text, e.g. openrouter's
 *  metadata.raw) and `metadata` outrank the often-generic `message`
 *  ("Provider returned error"). */
function digErrorText(raw: unknown): string | null {
    if (raw == null) return null;
    if (typeof raw === 'string') {
        const s = raw.trim();
        if (!s) return null;
        if (s.startsWith('{') || s.startsWith('[')) {
            try {
                return digErrorText(JSON.parse(s));
            } catch {
                return s;
            }
        }
        return s;
    }
    if (typeof raw !== 'object') return null;
    const o = raw as Record<string, unknown>;
    for (const key of ['raw', 'metadata', 'message', 'error', 'reason']) {
        if (o[key] != null) {
            const inner = digErrorText(o[key]);
            if (inner) return inner;
        }
    }
    return null;
}

/** Whether the text before an embedded JSON blob is exception-chain noise
 *  ("litellm.APIError: OpenrouterException - ") rather than prose. Exception
 *  prefixes are short, single-line, and light on words; a sentence or a
 *  multi-line explanation must survive verbatim. */
function isExceptionChainPrefix(prefix: string): boolean {
    const p = prefix.trim();
    if (p.includes('\n')) return false;
    return p.split(/\s+/).length <= 8;
}

export function formatAgentError(raw: unknown): string {
    if (raw == null) return '';
    if (typeof raw === 'string') {
        const s = raw.trim();
        if (s.startsWith('{') || s.startsWith('[')) {
            try {
                return formatAgentError(JSON.parse(s));
            } catch {
                /* prose that happens to start with { */
            }
        } else {
            // Provider blobs often embed JSON mid-string ("litellm.RateLimitError:
            // RateLimitError: OpenrouterException - {json}") — the human message
            // lives deep inside (metadata.raw), not in the exception-class prefix.
            // Only dig when the prefix IS such machine noise: backend-authored
            // rewrites (provider_errors) are real prose ending in a "Provider
            // message: {json}" appendix, and digging that JSON replaced the whole
            // explanation with the five-word provider error it exists to explain.
            const brace = s.indexOf('{');
            if (brace > 0 && isExceptionChainPrefix(s.slice(0, brace))) {
                try {
                    const dug = digErrorText(JSON.parse(s.slice(brace)));
                    if (dug) return dug;
                } catch {
                    /* no embedded object — fall through to the raw string */
                }
            }
        }
        return raw;
    }
    if (typeof raw === 'object') {
        const dug = digErrorText(raw);
        if (dug) return dug;
        try {
            return JSON.stringify(raw);
        } catch {
            return String(raw);
        }
    }
    return String(raw);
}

export function persistedEventsToChatMessages(
    events: PersistedEvent[] | undefined
): AgentChatMessage[] {
    if (!Array.isArray(events)) return [];
    // Persisted verdicts (agent:builder_decision) — the card's cross-device
    // decided state. Collected up front: the decision event always lands AFTER
    // its proposal's card event.
    const decisions = new Map<string, 'approved' | 'dismissed'>();
    for (const ev of events) {
        const d = (
            ev as {
                builder_decision?: { proposal_id?: string; decision?: string };
            }
        ).builder_decision;
        if (
            d?.proposal_id &&
            (d.decision === 'approved' || d.decision === 'dismissed')
        ) {
            decisions.set(d.proposal_id, d.decision);
        }
    }
    const out: AgentChatMessage[] = [];
    // Builder approval cards render BELOW the turn they belong to (they're
    // persisted mid-turn, before the assistant's reply lands): hold them and
    // flush after the turn's assistant message — or before the next user turn /
    // at the end when the turn never completed.
    const pendingCards: AgentChatMessage[] = [];
    const flushCards = () => {
        out.push(...pendingCards.splice(0));
    };
    for (const ev of events) {
        if ((ev as { builder_decision?: unknown }).builder_decision) continue; // verdict marker, not a bubble
        if (ev.builder_prompt?.prompt) {
            const pid = ev.builder_prompt.proposal_id;
            const decided =
                (pid && decisions.get(pid)) || ev.builder_prompt.decision;
            pendingCards.push({
                isUser: false,
                text: '',
                isComplete: true,
                builderPrompt: decided
                    ? { ...ev.builder_prompt, decision: decided }
                    : ev.builder_prompt,
            });
            continue;
        }
        // Post-Phase-9 shape: {role, message}. Check this BEFORE the legacy
        // action/source branch — if an event has both, prefer the explicit role.
        if (ev.role === 'user' || ev.role === 'assistant') {
            const isUser = ev.role === 'user';
            const rawText = ev.message ?? '';
            if (ev.cancelled) {
                // Terminal error / interrupted bubble. message body becomes
                // the error reason; text stays empty so the UI renders the
                // red banner shape consistently with the legacy action='error'
                // branch below.
                if (rawText) {
                    out.push({
                        isUser: false,
                        text: '',
                        isComplete: true,
                        error: formatAgentError(rawText),
                    });
                }
                continue;
            }
            // User turns may carry interleaved text+images encoded as a
            // __NOCLICK_SEQUENCE__ blob (legacy) plus attached images/files in
            // the structured image_urls/attachments fields; assistant turns
            // (image/video/kling generation) carry generated media in
            // image_urls / video_urls.
            const seq = isUser ? decodeNoClickSequence(rawText) : null;
            const decoded = seq ? seq.text : rawText;
            const merged = [
                ...(seq?.content ?? []),
                ...(mediaContentFromEvent(ev) ?? []),
            ];
            const content = merged.length > 0 ? merged : undefined;
            const fileAttachments = isUser
                ? fileAttachmentsFromEvent(ev)
                : undefined;
            // A model change starts a fresh conversation and folds the old
            // thread into the first message so the new model has context. Put
            // it back where it belongs: real bubbles above, and the user's own
            // words in their bubble — otherwise the whole transcript renders
            // inside what they typed.
            const { carried, text } = isUser
                ? splitCarryOverContext(decoded)
                : { carried: [], text: decoded };
            for (const turn of carried) {
                out.push({
                    isUser: turn.isUser,
                    text: turn.text,
                    isComplete: true,
                    carriedOver: true,
                });
            }
            if (!text && !content && !fileAttachments) continue;
            if (isUser) flushCards(); // cards belong to the PREVIOUS turn
            out.push({
                isUser,
                text,
                isComplete: true,
                content,
                attachments: fileAttachments,
                steps: isUser
                    ? undefined
                    : stepsFromPersistedToolCalls(ev.tool_calls),
            });
            if (!isUser) flushCards(); // sink the turn's cards below its reply
            continue;
        }
        if (ev.action === 'message') {
            const isUser = ev.source === 'user';
            const rawText = ev.args?.content ?? ev.message ?? '';
            const { text, content } = isUser
                ? decodeNoClickSequence(rawText)
                : { text: rawText, content: undefined };
            if (!text && !content) continue;
            if (isUser) flushCards();
            out.push({
                isUser,
                text,
                isComplete: true,
                content,
                steps: isUser
                    ? undefined
                    : stepsFromPersistedToolCalls(ev.tool_calls),
            });
            if (!isUser) flushCards();
            continue;
        }
        if (ev.observation === 'agent_state_changed') {
            const state = String(
                (ev.args as Record<string, unknown> | undefined)?.agent_state ??
                    ''
            ).toLowerCase();
            const reason = formatAgentError(
                (ev.args as Record<string, unknown> | undefined)?.reason ?? ''
            );
            if ((state === 'error' || state === 'rejected') && reason) {
                out.push({
                    isUser: false,
                    text: '',
                    isComplete: true,
                    error: reason,
                });
            }
            continue;
        }
        if (ev.action === 'error') {
            const reason = formatAgentError(
                (ev.args as Record<string, unknown> | undefined)?.reason ??
                    ev.message ??
                    ''
            );
            if (reason)
                out.push({
                    isUser: false,
                    text: '',
                    isComplete: true,
                    error: reason,
                });
        }
    }
    flushCards(); // a turn that never completed still shows its card (at the end)
    return out;
}

type ChatEventData = {
    message?: string | null;
    finished?: boolean;
    content?: ContentItem[] | null;
    status?: string | null;
    agentic_steps?: AgenticStep[] | null;
    /** prompt_builder approval card (see AgentChatMessage.builderPrompt). */
    builder_prompt?: BuilderPromptProposal | null;
};

/** Advance a bubble's activity timeline with one event's agentic_steps +
 *  status. Tool completions update their in_progress row in place (id-keyed);
 *  a new status milestone completes the previous one; text streaming resolves
 *  status rows (the agent is past setup) but not tool rows (tools can run
 *  mid-text); `finished` resolves everything. Returns the input unchanged
 *  (incl. undefined) when the event carries nothing timeline-related. */
function advanceSteps(
    steps: AgentChatStep[] | undefined,
    data: ChatEventData,
    hasText: boolean
): AgentChatStep[] | undefined {
    const incoming = Array.isArray(data.agentic_steps)
        ? data.agentic_steps
        : [];
    // A terminal frame's status ("completed" on a finished CLI frame) is a
    // machine sentinel, not a milestone — folding it would append
    // a spurious checkmarked "completed" row to every CLI turn.
    const incomingStatus =
        !data.finished && typeof data.status === 'string' && data.status
            ? data.status
            : undefined;
    // Copy only when this event can actually change the timeline — without the
    // needsResolve term, every text-only token delta on a bubble with steps
    // re-allocated the whole array for an identical result.
    const needsResolve =
        (hasText || data.finished) &&
        !!steps?.some(
            (s) =>
                s.status === 'in_progress' &&
                (data.finished || s.kind === 'status')
        );
    if (!incoming.length && !incomingStatus && !needsResolve) return steps;
    const now = Date.now();
    let next: AgentChatStep[] = steps ? steps.slice() : [];

    for (const ws of incoming) {
        if (!ws?.id) continue;
        const idx = next.findIndex((s) => s.id === ws.id);
        if (idx === -1) {
            const completed = ws.status === 'completed';
            // A completed frame whose start frame was lost carries the RESULT
            // preview as its text — that's detail, not a label.
            next.push({
                id: ws.id,
                title: completed ? 'Tool call' : (ws.text ?? ''),
                ...(completed && ws.text ? { detail: ws.text } : {}),
                status: completed ? 'completed' : 'in_progress',
                kind: 'tool',
                startedAt: now,
                ...(completed ? { endedAt: now } : {}),
            });
        } else if (ws.status === 'completed') {
            if (next[idx].status !== 'completed') {
                // Completion frame: keep the "Calling X(…)" title, stash the result
                // preview as expandable detail.
                next[idx] = {
                    ...next[idx],
                    status: 'completed',
                    endedAt: now,
                    detail: ws.text || undefined,
                };
            } else if (!next[idx].detail && ws.text) {
                // Row was force-completed by a finished frame that overtook this
                // completion — backfill the result preview it carries.
                next[idx] = { ...next[idx], detail: ws.text };
            }
        }
        // A late in_progress re-emit for an already-completed id is dropped —
        // relay and direct-socket frames can interleave out of order.
    }

    if (incomingStatus) {
        // Milestones are keyed by title: a repeat of the CURRENT milestone is a
        // no-op (reasoning models re-emit "Thinking" per delta); a RECURRING one
        // (Thinking → Retrying → Thinking) re-activates its existing row instead
        // of appending a duplicate.
        const lastStatus = next.filter((s) => s.kind === 'status').pop();
        if (lastStatus?.title !== incomingStatus) {
            next = next.map((s) =>
                s.kind === 'status' && s.status === 'in_progress'
                    ? { ...s, status: 'completed', endedAt: now }
                    : s
            );
            const existingIdx = next.findIndex(
                (s) => s.kind === 'status' && s.title === incomingStatus
            );
            if (existingIdx !== -1) {
                next[existingIdx] = {
                    ...next[existingIdx],
                    status: 'in_progress',
                    startedAt: now,
                    endedAt: undefined,
                };
            } else {
                next.push({
                    id: `status-${now}-${next.length}`,
                    title: incomingStatus,
                    status: 'in_progress',
                    kind: 'status',
                    startedAt: now,
                });
            }
        }
    }

    // Status milestones resolve when the turn visibly progresses past setup —
    // text streaming, a tool call starting, or the turn finishing. Without the
    // tool-step term, "Agent is working…" kept spinning next to an active tool
    // row (two spinners for one activity).
    if (hasText || data.finished || incoming.length) {
        next = next.map((s) =>
            s.status === 'in_progress' && (data.finished || s.kind === 'status')
                ? { ...s, status: 'completed', endedAt: now }
                : s
        );
    }
    return next.length ? next : undefined;
}

/** Index of the LIVE tail — the last message that is not a builder approval
 *  card. Cards sink to the bottom of their turn (arriving mid-stream, they
 *  must render below the response, not above it), so every "is the tail an
 *  in-flight bubble?" check skips them. -1 when only cards (or nothing). */
export function liveTailIndex(messages: readonly AgentChatMessage[]): number {
    let i = messages.length - 1;
    while (i >= 0 && messages[i].builderPrompt) i--;
    return i;
}

/** Resolve any still-running steps — used when a turn ends via a terminal
 *  agent:state instead of a finished chat:message frame. */
function finalizeSteps(
    steps: AgentChatStep[] | undefined
): AgentChatStep[] | undefined {
    if (!steps?.some((s) => s.status === 'in_progress')) return steps;
    const now = Date.now();
    return steps.map((s) =>
        s.status === 'in_progress'
            ? { ...s, status: 'completed', endedAt: now }
            : s
    );
}

/** Apply a single `chat:message` event to the current message list. Exported
 *  so unit tests can drive the reducer directly without going through
 *  React + the socket layer. */
export function applyChatMessageEvent(
    prev: AgentChatMessage[],
    data: ChatEventData
): AgentChatMessage[] {
    // prompt_builder approval card: a standalone frame arriving MID-turn (the
    // tool returned but the agent turn keeps running). Appended at the END so
    // the approval sits at the BOTTOM of the turn where the eye lands after a
    // long response — the streaming reducer finds the in-flight bubble ABOVE
    // trailing cards via liveTailIndex, so text keeps flowing into the right
    // bubble. proposal_id dedupes event relay redeliveries.
    if (data.builder_prompt?.prompt) {
        const pid = data.builder_prompt.proposal_id;
        if (pid && prev.some((m) => m.builderPrompt?.proposal_id === pid))
            return prev;
        return prev.concat({
            isUser: false,
            text: '',
            isComplete: true,
            builderPrompt: data.builder_prompt,
        });
    }
    const incomingContent = Array.isArray(data.content)
        ? data.content
        : undefined;
    const incomingStatus =
        typeof data.status === 'string' ? data.status : undefined;
    // Status applies to in-flight bubbles only. Once a chunk lands as completed
    // or after the agent's actual text starts streaming, "completed" status
    // strings from the backend become noise on the bubble — clear them.
    // The live tail skips trailing approval cards (they sink below the turn).
    const tailIdx = liveTailIndex(prev);
    const last = tailIdx >= 0 ? prev[tailIdx] : undefined;
    if (last && !last.isUser && !last.isComplete) {
        const accumulatedText = last.text + (data.message ?? '');
        const next: AgentChatMessage = {
            isUser: false,
            text: accumulatedText,
            isComplete: !!data.finished,
            content: incomingContent ?? last.content,
            // Keep status visible only while text is still empty. Once any text
            // arrives the bubble has visible content of its own.
            status:
                data.finished || accumulatedText
                    ? undefined
                    : (incomingStatus ?? last.status),
            steps: advanceSteps(last.steps, data, accumulatedText.length > 0),
        };
        return [...prev.slice(0, tailIdx), next, ...prev.slice(tailIdx + 1)];
    }
    // A text-less, unfinished frame whose step ids ALL belong to the last
    // (already complete) agent bubble is a late completion frame that lost a
    // out-of-order delivery race with the terminal frame — fold it into
    // that bubble instead of spawning a ghost. Frames with unknown ids or a
    // status are a NEW turn starting (possibly from another surface) and fall
    // through to open a bubble as usual.
    const startingText = data.message ?? '';
    const stragglers = Array.isArray(data.agentic_steps)
        ? data.agentic_steps
        : [];
    if (
        !startingText &&
        !data.finished &&
        !incomingContent &&
        !incomingStatus &&
        stragglers.length > 0 &&
        last &&
        !last.isUser &&
        last.isComplete &&
        stragglers.every(
            (ws) => ws?.id && last.steps?.some((s) => s.id === ws.id)
        )
    ) {
        return [
            ...prev.slice(0, tailIdx),
            {
                ...last,
                steps: advanceSteps(last.steps, data, last.text.length > 0),
            },
            ...prev.slice(tailIdx + 1),
        ];
    }
    // Start a new agent bubble.
    return prev.concat({
        isUser: false,
        text: startingText,
        isComplete: !!data.finished,
        content: incomingContent,
        status: data.finished || startingText ? undefined : incomingStatus,
        steps: advanceSteps(undefined, data, startingText.length > 0),
    });
}

// Stable empty for sessionless renders — a fresh [] per render would churn
// consumers' memos.
const EMPTY_MESSAGES: AgentChatMessage[] = [];

export function useAgentChat(
    conversationId: string | null | undefined,
    transport: AgentChatTransport = defaultTransport,
    /** Out-of-band "a turn is running" signal from the workflow relay.
     *  Keeps the terminal-state reconciler polling for turns this tab never saw
     *  the send for — a reload mid-turn, or a run started from another surface —
     *  so the finished response is adopted even if the live frames were missed.
     *  Deliberately does NOT flip isStreaming: presence is node/conversation
     *  level and must not block the composer. */
    externallyBusy = false
): UseAgentChatResult {
    // Session state lives in a MODULE-LEVEL store keyed by conversation_id
    // (agentChatSessionStore), not component state: the chat surface unmounts on
    // Interface ↔ Workflow tab switches, and component-local state erased the
    // in-flight status/step timeline every time (2026-07-18). The hook reads a
    // snapshot and mutates the live session; a remount restores instantly.
    // sync:true — chat frames must render the moment they mutate the session
    // (valtio's default batches notifications into a microtask, which also
    // breaks sync `act()` in tests). Frame volume here is modest.
    const sessionsSnap = useSnapshot(agentChatSessionStore, {
        sync: true,
    }).sessions;
    const sessionSnap = conversationId
        ? sessionsSnap[conversationId]
        : undefined;
    const messages = (sessionSnap?.messages ??
        EMPTY_MESSAGES) as AgentChatMessage[];
    const isStreaming = sessionSnap?.isStreaming ?? false;
    const errorReason = sessionSnap?.errorReason ?? null;
    const lastFinishedAt = sessionSnap?.lastFinishedAt ?? 0;

    // Setters resolve the target session through a ref, not a closure: they stay
    // identity-stable AND always write to the CURRENT conversation. A closure
    // over conversationId dropped sends silently when a stale callback survived
    // an id change — the public page's first render (id still null) and post-
    // mount switches (new chat, thread switch) both ate the user's bubble
    // (2026-07-18). Async callers (cold fetch, reconcile poll) that must not
    // outlive their conversation already guard with `cancelled`.
    const conversationIdRef = useRef(conversationId);
    conversationIdRef.current = conversationId;
    const setMessages = useCallback(
        (
            updater:
                | AgentChatMessage[]
                | ((prev: AgentChatMessage[]) => AgentChatMessage[])
        ) => {
            const id = conversationIdRef.current;
            if (!id) return;
            const s = getAgentChatSession(id);
            s.messages =
                typeof updater === 'function' ? updater(s.messages) : updater;
        },
        []
    );
    const setIsStreaming = useCallback((v: boolean) => {
        const id = conversationIdRef.current;
        if (id) getAgentChatSession(id).isStreaming = v;
    }, []);
    const setErrorReason = useCallback((v: string | null) => {
        const id = conversationIdRef.current;
        if (id) getAgentChatSession(id).errorReason = v;
    }, []);
    // Terminal watermark: timestamp of the most recent finished frame /
    // terminal state / adoption. Read synchronously off the live session by the
    // cold-fetch guard (a terminal frame landing during the resume window means
    // the persisted snapshot already includes that turn — prepending it again
    // double-renders the bubble).
    const markFinished = useCallback((at: number) => {
        const id = conversationIdRef.current;
        if (id) getAgentChatSession(id).lastFinishedAt = at;
    }, []);

    // Cold-fetch persisted history. The session store makes remounts (tab away →
    // back) an INSTANT restore — a session that has already streamed or loaded
    // is never reset, and a mid-turn remount doesn't even refetch (the reconcile
    // poll heals any frames missed while unmounted). Only a first-touch session
    // fetches from scratch; an idle revisit refreshes in the background and
    // adopts the persisted truth.
    //
    // StrictMode note: the effect runs effect→cleanup→effect on mount; both runs
    // may fetch (the first is cancelled) — mutating with the same data is fine.
    useEffect(() => {
        if (!conversationId) return;
        const session = getAgentChatSession(conversationId);
        const hasLiveState =
            session.resumedOnce ||
            session.messages.length > 0 ||
            session.isStreaming;
        // Mid-turn remount: state is live and authoritative — don't touch it.
        if (hasLiveState && (session.isStreaming || externallyBusy)) return;

        const fetchStartedAt = Date.now();
        let cancelled = false;
        void (async () => {
            try {
                const resp = await transport.resume(conversationId);
                if (cancelled) return;
                const persisted = persistedEventsToChatMessages(resp.messages);
                session.resumedOnce = true;
                if (persisted.length === 0) return;
                // If a terminal frame landed during the resume window, the live
                // tail already shows the same turn the persisted snapshot just
                // re-includes. Skip the apply to avoid the duplicate bubble.
                if (session.lastFinishedAt > fetchStartedAt) return;
                if (!session.isStreaming && session.messages.length > 0) {
                    // Idle revisit: the persisted transcript is the fresh truth (cards
                    // and tool timelines are persisted) — adopt it wholesale.
                    session.messages = dedupeConsecutiveErrors(persisted);
                    return;
                }
                setMessages((prev) => {
                    // A live builder card that raced this fetch is also in the
                    // persisted snapshot — drop the live copy by proposal_id.
                    const pids = new Set(
                        persisted
                            .map((m) => m.builderPrompt?.proposal_id)
                            .filter(Boolean)
                    );
                    const live = prev.filter(
                        (m) =>
                            !m.builderPrompt?.proposal_id ||
                            !pids.has(m.builderPrompt.proposal_id)
                    );
                    return dedupeConsecutiveErrors([...persisted, ...live]);
                });
            } catch (err) {
                if (!cancelled)
                    console.warn('[useAgentChat] resume failed', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [conversationId, transport, externallyBusy, setMessages]);

    // Listen to chat:message / agent:state for this conversation via the
    // transport. Events for OTHER conversations are ignored — different agent
    // nodes / different keys must not bleed into each other's transcripts.
    useEffect(() => {
        if (!conversationId) return;

        const offChat = transport.onEvent(
            'chat:message',
            (data: ChatMessageEvent) => {
                if (data.conversation_id !== conversationId) return;
                setMessages((prev) => applyChatMessageEvent(prev, data));
                if (data.finished) {
                    setIsStreaming(false);
                    markFinished(Date.now());
                    // A turn that ended cleanly retires the previous turn's banner. The
                    // clear used to live only in addUserMessage, so it ran for turns the
                    // CHAT started and not for turns dispatched from the canvas — and a
                    // failure from two turns ago sat under the new answer. agent:state is
                    // the wrong hook for this: its terminal set is stopped/finished/error/
                    // rejected/paused, and a successful turn ends on this frame.
                    setErrorReason(null);
                }
            }
        );

        // agent:state — the only signal we get when a run dies on a hard backend
        // error (rate limit, exception, …) without ever emitting finished:true.
        // Without this the UI is stuck "Streaming…" indefinitely.
        const offState = transport.onEvent(
            'agent:state',
            (data: AgentStateEvent) => {
                if (data.conversation_id !== conversationId) return;
                const state = (data.state || '').toLowerCase();
                if (TERMINAL_AGENT_STATES.has(state)) {
                    setIsStreaming(false);
                    // Mark the turn resolved so a resume fetch already in flight skips its
                    // prepend (the same guard chat:message uses) — without this an error
                    // turn's persisted copy is prepended on top of this live bubble.
                    markFinished(Date.now());
                    const isErrorState =
                        state === 'error' || state === 'rejected';
                    // Authoritative in BOTH directions. errorReason describes the turn that
                    // just ended, and it was only ever cleared on the next send — so a turn
                    // that ended cleanly left the previous failure's banner sitting under
                    // its answer. (The transcript's own guard only covers the case where
                    // the error is the LAST message; once a successful reply lands after
                    // it, the guard passes and the stale banner renders.)
                    setErrorReason(
                        isErrorState && data.reason
                            ? formatAgentError(data.reason)
                            : null
                    );
                    // If the last bubble is an in-flight agent message, close it so the
                    // streaming cursor disappears AND drop its stale `status` (e.g.
                    // "Sandbox ready, running agent…") so the error banner isn't shown
                    // alongside a misleading in-flight progress line.
                    // Also append a synthetic error bubble for terminal-error states so
                    // the failure stays visible in the transcript across remounts (the
                    // agent:state event itself isn't replayed by the backend on resume;
                    // the corresponding agent_state_changed observation is, but only
                    // for the LLM path. CLI handlers persist a separate `action:error`
                    // event via runner.persist_agent_error).
                    setMessages((prev) => {
                        let next = prev;
                        const tailIdx = liveTailIndex(prev);
                        const last = tailIdx >= 0 ? prev[tailIdx] : undefined;
                        if (last && !last.isUser && !last.isComplete) {
                            next = [
                                ...prev.slice(0, tailIdx),
                                {
                                    ...last,
                                    isComplete: true,
                                    status: undefined,
                                    steps: finalizeSteps(last.steps),
                                },
                                ...prev.slice(tailIdx + 1),
                            ];
                        }
                        if (isErrorState && data.reason) {
                            next = next.concat({
                                isUser: false,
                                text: '',
                                isComplete: true,
                                error: formatAgentError(data.reason),
                            });
                        }
                        return dedupeConsecutiveErrors(next);
                    });
                }
            }
        );

        return () => {
            offChat();
            offState();
        };
    }, [
        conversationId,
        transport,
        markFinished,
        setMessages,
        setIsStreaming,
        setErrorReason,
    ]);

    const addUserMessage = useCallback(
        (
            text: string,
            content?: ContentItem[],
            attachments?: AgentChatFileAttachment[]
        ) => {
            setMessages((prev) =>
                prev.concat({
                    isUser: true,
                    text,
                    isComplete: true,
                    content,
                    attachments,
                })
            );
            setIsStreaming(true);
            setErrorReason(null);
        },
        [setMessages, setIsStreaming, setErrorReason]
    );

    // Relay-independent terminal-state reconciler. The live agent:state /
    // chat:message frames arrive over the event relay relay, which is fire-and-
    // forget (the backend logs-and-swallows send failures) and can miss a frame
    // if it flaps or the tab wasn't subscribed yet — leaving the chat pinned on
    // "Sandbox ready, running agent…" forever (2026-07-09: a creditless-key turn
    // failed server-side and persisted its error, but the interface only showed
    // it after a tab-switch remount reran the resume fetch). While streaming —
    // or while the presence beat says a turn this tab never saw the send for is
    // running (externallyBusy: reload mid-turn, run started from another
    // surface) — poll the SAME persisted conversation the resume path reads; if
    // a terminal frame has landed that our live tail never received, adopt it
    // and stop.
    const reconcileActive = isStreaming || externallyBusy;
    useEffect(() => {
        if (!conversationId || !reconcileActive) return;
        let cancelled = false;

        // Message signature — adoption fires only when the persisted transcript
        // contains MORE copies of the terminal-tail signature than are already
        // rendered. Counting (not mere presence) is what distinguishes a repeated
        // identical answer — turn 2's "Done." with turn 1's "Done." already on
        // screen (persisted 2 vs rendered 1 → adopt) — from an already-delivered
        // or already-adopted tail (counts equal → no-op poll), and from an old
        // turn's tail while a NEW turn streams live frames (equal → the in-flight
        // bubble is never wiped). Subsumes the old "relay won" timestamp guard.
        const sigOf = (m: AgentChatMessage | undefined) =>
            m
                ? `${m.isUser ? 'u' : 'a'}|${m.isComplete ? '1' : '0'}|${m.text}|${m.error ?? ''}`
                : '';

        const poll = async () => {
            try {
                const resp = await transport.resume(conversationId);
                if (cancelled) return;
                // Dedupe BEFORE counting: adoption also dedupes, so counting the raw
                // list would keep persisted > rendered for collapsed duplicate errors
                // and re-adopt on every poll.
                const persisted = dedupeConsecutiveErrors(
                    persistedEventsToChatMessages(resp.messages)
                );
                const lastPersisted = persisted[persisted.length - 1];
                // Terminal iff the newest persisted entry is a completed assistant
                // message carrying real content (text or an error). An in-flight or
                // user entry means the turn genuinely hasn't finished — keep waiting.
                const isTerminal =
                    !!lastPersisted &&
                    !lastPersisted.isUser &&
                    lastPersisted.isComplete &&
                    ((lastPersisted.text?.trim().length ?? 0) > 0 ||
                        !!lastPersisted.error);
                if (!isTerminal) return;
                const tailSig = sigOf(lastPersisted);
                const countIn = (arr: readonly AgentChatMessage[]) =>
                    arr.reduce((n, m) => (sigOf(m) === tailSig ? n + 1 : n), 0);
                if (
                    countIn(getAgentChatSession(conversationId).messages) >=
                    countIn(persisted)
                )
                    return;
                markFinished(Date.now());
                setIsStreaming(false);
                // Same rule as the live path: this replaces the whole transcript with
                // persisted truth, so it owns the banner state too — including
                // clearing it when the tail is a successful reply.
                setErrorReason(
                    lastPersisted.error
                        ? formatAgentError(lastPersisted.error)
                        : null
                );
                // Replace the whole transcript with the persisted truth — this drops
                // the stale in-flight "running agent…" bubble the live path would have
                // closed, and is idempotent if some frames did arrive.
                setMessages(persisted);
            } catch (err) {
                if (!cancelled)
                    console.warn('[useAgentChat] reconcile poll failed', err);
            }
        };

        // First reconcile after a short grace (let the fast relay path win the
        // common case), then on a steady interval until streaming ends.
        const timer = setInterval(poll, RECONCILE_INTERVAL_MS);
        const kickoff = setTimeout(poll, RECONCILE_GRACE_MS);
        return () => {
            cancelled = true;
            clearInterval(timer);
            clearTimeout(kickoff);
        };
    }, [
        conversationId,
        reconcileActive,
        transport,
        markFinished,
        setMessages,
        setIsStreaming,
        setErrorReason,
    ]);

    return {
        messages,
        isStreaming,
        errorReason,
        addUserMessage,
        lastFinishedAt,
    };
}
