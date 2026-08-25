// The single hook every chat surface reads from.
//
// Keyed on conversation_id (the chat thread the user is in), NOT
// workflow_id. Why: the chat sometimes runs without a workflow at all
// (the "create me a workflow" flow), and the same workflow can host
// multiple historical conversations. Workflow context resolves up at
// the caller (sidebar resolves "latest conv for this workflow" on
// workflow change; canvas surfaces that just need a "is anything
// running?" boolean use useIsStreamingForWorkflow below).
//
// Internally:
//   • Live in-flight: activeGenStore.byConversation[convId] via useSnapshot.
//   • Persisted history: cold-fetched once when the conversation changes.
//     When the gen terminates, BE's terminal frame carries the freshly-
//     committed events array, which we adopt via takeCommittedPatch — no
//     refetch round trip.
//
// Refresh recovery: the event relay sends active_gen:snapshot on every
// viewer-WS connect, so activeGenStore catches up without any work
// from this hook. On cold open the byConversation list is empty and
// the cold-fetch path returns the persisted history.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useSnapshot } from 'valtio';
import {
    activeGenStore,
    takeCommittedPatch,
    type ActiveGeneration,
} from '~/lib/activeGenStore';
import { composeMessages } from '~/lib/composeMessages';
import { sendEventAsync } from '~/lib/socket-sender';
import { readJson, writeJson } from '~/lib/chat-storage';
import type { Message } from '~/components/chat/types';
import type { PersistedMessage } from '~/hooks/conversationRestoreMapping';

const DEFAULT_WELCOME: Message[] = [
    { text: 'How can I help?', isUser: false, isComplete: true },
];

interface ResumeResponse {
    session_id: string;
    messages: PersistedMessage[];
    workflow_id: string | null;
}

/** Defensive normalization. Older conversations.events rows can carry
 *  `content` as a bare string instead of a ContentItem[], which causes
 *  MessagesView's .map call to throw. mapPersistedMessage handles this
 *  downstream, but enforcing it at every persisted-state mutation site
 *  here means the state itself can never hold a malformed row — useful
 *  for the cache (which is written from this state) and as a single
 *  point of audit for the BE shape. */
function normalizePersisted(messages: PersistedMessage[]): PersistedMessage[] {
    return messages.map(m => Array.isArray(m.content) ? m : { ...m, content: undefined });
}

// Per-conversation cache: sessionStorage so reads are synchronous and the
// first render after switching to a previously-visited conv paints with
// real content instead of "How can I help?". The BE resume runs in
// parallel and overwrites the cache + state when fresh data lands.
function cacheKey(conversationId: string): string {
    return `noclick:chat:conv:${conversationId}`;
}

function loadCachedMessages(conversationId: string): PersistedMessage[] | null {
    const parsed = readJson<PersistedMessage[] | null>(cacheKey(conversationId), null);
    return Array.isArray(parsed) ? parsed : null;
}

function saveCachedMessages(conversationId: string, messages: PersistedMessage[]): void {
    writeJson(cacheKey(conversationId), messages);
}

export interface ConversationView {
    /** Composed messages for MessagesView — persisted prefix + active gen bubbles. */
    messages: Message[];
    /** True iff one or more in-flight gens for this conversation that haven't been stopped. */
    isStreaming: boolean;
    /** Conversation id of the currently-rendered thread (echoes the input — kept on the return for callers that previously read it). */
    conversationId: string | null;
}

/**
 * Returns the composed chat view for a single conversation thread.
 *
 * - Pass the conversation_id you want to render (typically from
 *   useSidebarConversation in the sidebar).
 * - Returns the synchronously-derived view from activeGenStore plus a
 *   per-conversation cache of persisted history. Cold-fetched once per
 *   conversation; subsequent updates flow through the BE's terminal patch.
 */
export function useConversation(conversationId: string | null | undefined): ConversationView {
    const storeSnap = useSnapshot(activeGenStore);

    // Persisted history for the current conversation. Lazy-initialized
    // from the sessionStorage cache so the first render of a known
    // conversation paints with content immediately (no welcome flash).
    const [persisted, setPersisted] = useState<PersistedMessage[]>(() =>
        conversationId ? normalizePersisted(loadCachedMessages(conversationId) ?? []) : [],
    );
    // `fetchedFor` lives in a ref so the cold-fetch effect doesn't list
    // it as a dep. If it did, calling setFetchedFor inside the effect
    // would re-fire the effect, whose cleanup would cancel the in-flight
    // resume — leaving `persisted` empty even though the BE responded
    // with the right messages.
    const fetchedForRef = useRef<string | null>(null);

    // Cold fetch: runs once per conversation change. Synchronously seeds
    // from the cache (instant restore for known conversations), then
    // overwrites in the background with the BE's authoritative response.
    useEffect(() => {
        if (!conversationId) {
            setPersisted([]);
            fetchedForRef.current = null;
            return;
        }
        if (fetchedForRef.current === conversationId) return;
        fetchedForRef.current = conversationId;

        // Instant: paint cached messages now so the user sees their
        // chat on re-visit without waiting for the BE.
        const cached = loadCachedMessages(conversationId);
        setPersisted(normalizePersisted(cached ?? []));

        // Watermark the moment the fetch started. If a gen for this
        // conversation reaches terminal while resume is in flight, the
        // terminal patch (S1) is fresher than what resume read (S0) —
        // applying the resume snapshot afterward would clobber the
        // committed turn from view and from sessionStorage. The
        // terminal handler stamps activeGenStore.lastCommittedAt[conv]
        // at commit time; if that's > fetchStartedAt when resume
        // returns, drop the resume's setPersisted entirely.
        const fetchStartedAt = Date.now();

        let cancelled = false;
        void (async () => {
            try {
                const resume = await sendEventAsync({
                    event_name: 'conversation:resume',
                    session_id: conversationId,
                } as never) as ResumeResponse;
                if (cancelled) return;
                const committedAt = activeGenStore.lastCommittedAt[conversationId] ?? 0;
                if (committedAt > fetchStartedAt) {
                    // A terminal patch landed (and was applied) while resume
                    // was in flight. Trust the live channel — discard the
                    // older snapshot from the BE.
                    return;
                }
                const messages = normalizePersisted(resume.messages || []);
                setPersisted(messages);
                saveCachedMessages(conversationId, messages);
            } catch (err) {
                console.warn('[useConversation] persisted fetch failed', err);
            }
        })();
        return () => { cancelled = true; };
    }, [conversationId]);

    // External clear: prompt-submit from FlowCanvasEmptyState (and the
    // "+" button / /clear command via noclick:clear-messages) needs to
    // wipe the displayed history so the new prompt lands as the first
    // bubble.
    useEffect(() => {
        const handler = () => {
            setPersisted([]);
            fetchedForRef.current = null;
        };
        document.addEventListener('noclick:conversation:clear', handler);
        return () => document.removeEventListener('noclick:conversation:clear', handler);
    }, []);

    // External switch: the chat-history dropdown picks a specific older
    // conversation and dispatches this event with the pre-fetched
    // messages. Adopting the messages here avoids a redundant resume
    // call when the dropdown already has them.
    useEffect(() => {
        const handler = (event: Event) => {
            const detail = (event as CustomEvent<{ conversationId: string; messages: PersistedMessage[] }>).detail;
            if (!detail?.conversationId) return;
            if (detail.conversationId !== conversationId) return;
            const messages = normalizePersisted(detail.messages || []);
            setPersisted(messages);
            saveCachedMessages(detail.conversationId, messages);
            fetchedForRef.current = detail.conversationId;
        };
        document.addEventListener('noclick:conversation:switch', handler);
        return () => document.removeEventListener('noclick:conversation:switch', handler);
    }, [conversationId]);

    // Adopt terminal patches: when the BE terminates a gen for this
    // conversation, takeCommittedPatch returns the freshly updated events
    // array. Apply it; the gen has already evicted from the store, so
    // the same render swaps the in-flight bubble for the committed turn.
    useEffect(() => {
        if (!conversationId) return;
        const patch = takeCommittedPatch(conversationId);
        if (patch) {
            const normalized = normalizePersisted(patch);
            setPersisted(normalized);
            saveCachedMessages(conversationId, normalized);
        }
    }, [conversationId, storeSnap.lastCommitted]);

    // Derive the view. Memoized over the inputs that actually matter so
    // MessagesView's reference equality checks don't churn.
    const activeGens = (conversationId
        ? (storeSnap.byConversation[conversationId] || [])
            .map(id => storeSnap.gens[id])
            .filter((g): g is NonNullable<typeof g> => !!g)
        : []) as ActiveGeneration[];
    // `isStreaming` only counts gens still streaming. A gen the user
    // just hit stop on is marked `stopped` by the pause bridge — it
    // stays in the projection so its bubble keeps rendering (as a
    // completed/interrupted turn) until the BE's terminal frame swaps
    // in the committed history, but the chat-box button reads
    // `isStreaming` and flips to "Send" immediately.
    // A gen the user stopped, OR one the staleness watchdog flagged as
    // interrupted (container drained/killed mid-stream — no terminal frame is
    // ever coming), OR one that ended with outcome='failed' (we keep it marked
    // so its bubble shows the error + Retry) no longer counts as streaming: the
    // chat-box flips back to "Send" so the user can retry instead of hanging.
    const streamingGens = activeGens.filter(g => !g.stopped && !g.interrupted && !g.failed);
    return useMemo(() => {
        const composed = composeMessages(persisted, activeGens);
        const messages = composed.length > 0 ? composed : DEFAULT_WELCOME;
        return {
            messages,
            isStreaming: streamingGens.length > 0,
            conversationId: conversationId ?? null,
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [persisted, conversationId,
        // Per-gen content fingerprint. Single FIXED-arity dep (a string)
        // so React's rules-of-hooks invariants hold across gen-count
        // changes. Captures both membership (gen_id) and per-gen
        // content (text length, events, status, stopped flag), so a
        // separate byConversation-membership dep is redundant.
        // NOTE: tokensProcessed is deliberately NOT here — BuilderProgress
        // subscribes to the gen directly for the live count, so token_progress
        // frames re-render only that footer, not every bubble.
        activeGens.map(g => `${g.gen_id}:${g.text.length}:${g.events.length}:${g.edit_steps.length}:${g.status}:${g.stopped ? 1 : 0}:${g.interrupted ? 1 : 0}:${g.failed ? 1 : 0}`).join('|'),
    ]);
}

/**
 * Lightweight workflow-keyed helper for canvas surfaces (e.g.
 * FlowCanvasEmptyState) that only need to know whether ANY gen is
 * actively streaming for a workflow. The sidebar's full conversation
 * rendering is conversation-keyed (useConversation above); this hook is
 * just a workflow-bucket lookup against the same store.
 */
export function useIsStreamingForWorkflow(workflowId: string | null | undefined): boolean {
    const storeSnap = useSnapshot(activeGenStore);
    if (!workflowId) return false;
    const ids = storeSnap.byWorkflow[workflowId] || [];
    for (const id of ids) {
        const gen = storeSnap.gens[id];
        if (gen && !gen.stopped && !gen.interrupted) return true;
    }
    return false;
}
