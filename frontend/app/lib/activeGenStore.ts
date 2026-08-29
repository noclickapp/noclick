// In-memory store of the user's active builder runs.
//
// Why this exists: the FE used to be a smart cache for both committed
// and in-flight conversation state, with multiple writers (mount-time
// restoreForEditor, conversations:updated push, live socket listener,
// switchToConversation, startFreshConversation, the started/text_chunk
// edit-event handlers). Every additional writer added a coherence bug.
//
// New model: scope the smart cache to ONLY in-flight state. Committed
// turns live in conversations.events on the BE, fetched once when the
// workflow opens with no active gen for it. The FE store holds the
// active runs — short-lived, mutated by a single always-on listener
// against the per-event wire contract emitted by the backend.
//
// Identity: gens are keyed on generation_id. We maintain two secondary
// indices over the same set:
//   • byWorkflow:     workflow_id     → list of gen_ids — for canvas
//                     surfaces ("what's editing this workflow right now").
//   • byConversation: conversation_id → list of gen_ids — for the chat
//                     sidebar ("what's running on this conversation").
//
// Both lists are O(1) lookups. A gen can live in both indices simultaneously
// (the common case: an existing-workflow edit), in just byConversation (a
// "create me a workflow" run before the brain has stamped a workflow_id),
// or in just byWorkflow (a run whose conversation_id was lost or never set
// — defensive, doesn't happen in practice).
//
// Refresh / multi-tab / multi-device: the event relay mirrors this
// store and sends `active_gen:snapshot` on every viewer connect, so a
// freshly-mounted FE catches up without polling.

import { proxy, ref } from 'valtio';
import { onSocketEvent } from '~/lib/socket-receiver';
import { sendEvent, AgentPauseRequest } from '~/lib/socket-sender';
import { applyAgenticGraphEvent, clearGraphAnimations } from '~/lib/liveGraphStore';
import type { PersistedMessage } from '~/hooks/conversationRestoreMapping';

export interface ActiveGeneration {
    gen_id: string;
    workflow_id: string | null;
    conversation_id: string;
    prompt: string;
    started_at: number;
    /** Brain text accumulated from active_gen:text_chunk deltas. */
    text: string;
    /** Graph mutation events (node_added, node_updated, etc.) in arrival order. */
    events: Array<Record<string, unknown>>;
    /** Reasoning-log entries from active_gen:edit_step. */
    edit_steps: string[];
    /** The current status string (cosmetic — render-only, replaced on each status frame). */
    status: string;
    /** Heuristic "tokens processed" from active_gen:token_progress — an
     *  absolute cumulative count the backend composes (real committed total of
     *  finished phases + chars/4 for the in-flight brain/node drafting stream).
     *  Render-only anti-stall signal; overwritten per frame (not accumulated),
     *  so a dropped tick self-heals. Resets naturally on a new gen. */
    tokensProcessed?: number;
    /** Set true the moment the user clicks stop. Used to flip
     *  `isStreaming` to false instantly while the bubble itself stays
     *  visible (rendered as an interrupted/completed turn) until the
     *  BE's terminal frame replaces it with the committed history. */
    stopped?: boolean;
    /** Wall-clock (Date.now()) of the most recent frame for this gen
     *  (started / text_chunk / status / graph_event / edit_step). The
     *  staleness watchdog reads this to tell a live-but-slow run (socket
     *  up, events still trickling) from a dead one (container drained or
     *  hard-killed → no more frames will ever arrive). */
    lastEventAt: number;
    /** Set true by the staleness watchdog when this gen's container is
     *  almost certainly gone (no frames after a reconnect, or absolute
     *  silence past the backstop). Like `stopped`, it flips `isStreaming`
     *  false and lets the chat render a "run interrupted — retry" turn
     *  instead of hanging on "Modifying workflow" forever. Self-corrects:
     *  a later snapshot/frame for a genuinely-alive gen clears it. */
    interrupted?: boolean;
    /** Set when the run ends with outcome='failed' (e.g. a mid-stream LLM
     *  error). Like `interrupted`, the gen is kept (not evicted) so the bubble
     *  stays with the error + a Retry, instead of silently vanishing. */
    failed?: boolean;
    /** Error message carried on the failed terminal frame. */
    error?: string;
    /** Machine-readable failure class + details (provider_key_missing carries env_var, provider, model). */
    errorCode?: string;
    errorMeta?: Record<string, string>;
}

interface ActiveGenStoreState {
    /** All active gens, keyed by gen_id. */
    gens: Record<string, ActiveGeneration>;
    /** workflow_id → list of active gen_ids ordered by started_at. */
    byWorkflow: Record<string, string[]>;
    /** conversation_id → list of active gen_ids ordered by started_at.
     *  Populated for every gen with a conversation_id (always, in practice).
     *  Lets the chat sidebar render in-flight bubbles for runs that have no
     *  workflow_id yet — e.g. "create me a workflow" before the brain has
     *  decided what to build. */
    byConversation: Record<string, string[]>;
    /** Per-conversation patch from the latest terminal frame. The FE
     *  consumer (useConversation) uses this to update its persistedMessages
     *  in the same render that the gen evicts — no flicker, no refetch. */
    lastCommitted: Record<string /* conversation_id */, PersistedMessage[]>;
    /** Monotonic timestamp (Date.now()) of the most recent terminal commit
     *  per conversation. Used by useConversation to detect that a terminal
     *  patch landed while a conversation:resume was in flight — in which
     *  case the resume snapshot is older than the committed turn and
     *  applying it would clobber the freshly-committed messages from view
     *  AND from sessionStorage. */
    lastCommittedAt: Record<string /* conversation_id */, number>;
}

export const activeGenStore = proxy<ActiveGenStoreState>({
    gens: {},
    byWorkflow: {},
    byConversation: {},
    lastCommitted: {},
    lastCommittedAt: {},
});

// ── Always-on listener ──────────────────────────────────────────────────

let _listenerInstalled = false;

export function ensureActiveGenListener(): void {
    if (_listenerInstalled) return;
    _listenerInstalled = true;

    // Snapshot replaces the local store with the relay's view. Sent on every
    // viewer-WS connect; subsequent deltas apply on top.
    //
    // Preserve any locally-registered optimistic gens — a reconnect
    // landing between the user's submit and the BE's first `started`
    // frame would otherwise erase the just-clicked bubble. The optimistic
    // entry remains until its matching real `started` lands (eviction
    // logic below).
    onSocketEvent('active_gen:snapshot' as any, (data: any) => {
        const gens: ActiveGeneration[] = Array.isArray(data?.gens) ? data.gens : [];
        const optimisticGens: ActiveGeneration[] = Object.values(activeGenStore.gens)
            .filter(g => g.gen_id.startsWith('optimistic_'));
        // Wholesale reset: anything not in the snapshot (and not a local
        // optimistic) is no longer active.
        activeGenStore.gens = {};
        activeGenStore.byWorkflow = {};
        activeGenStore.byConversation = {};
        for (const gen of gens) {
            // The relay just confirmed this gen is genuinely active — treat the
            // snapshot as a fresh frame so the watchdog's reconnect-silence
            // judgment resets and any prior `interrupted` mark self-corrects.
            gen.lastEventAt = Date.now();
            gen.interrupted = false;
            activeGenStore.gens[gen.gen_id] = gen;
            indexByWorkflow(gen);
            indexByConversation(gen);
            // Mirror the gen's accumulated graph events into
            // liveGraphStore so the canvas surfaces the nodes/edges
            // on restore. Without this, snapshot restore would
            // populate the chat (which reads gen.events directly)
            // but leave the canvas empty (it reads
            // liveGraphStore.graphRecords, which is only mutated by
            // the per-event mirror that runs for fresh
            // active_gen:graph_event frames — not for snapshot replay).
            if (gen.workflow_id && Array.isArray(gen.events)) {
                for (const event of gen.events) {
                    applyAgenticGraphEvent(gen.workflow_id, event as Parameters<typeof applyAgenticGraphEvent>[1]);
                }
            }
        }
        // Re-insert any optimistic gens that didn't match a snapshot
        // entry by conversation_id (those will be cleared by the next
        // active_gen:started for the same conv via the eviction logic).
        for (const opt of optimisticGens) {
            const sameConvMatched = gens.some(g => g.conversation_id === opt.conversation_id);
            if (sameConvMatched) continue;
            activeGenStore.gens[opt.gen_id] = opt;
            indexByWorkflow(opt);
            indexByConversation(opt);
        }
    });

    onSocketEvent('active_gen:started' as any, (data: any) => {
        if (!data?.gen_id) return;
        const incomingConv = data.conversation_id || '';
        // Evict any optimistic gen we registered locally for the same
        // conversation_id. The optimistic gen exists only to bridge
        // the round-trip between the user's submit click and the BE's
        // started frame — once the real gen lands, it's authoritative
        // and the optimistic placeholder must go, otherwise the chat
        // renders two bubble pairs for the same submit.
        if (incomingConv) {
            for (const [gid, g] of Object.entries(activeGenStore.gens)) {
                if (gid.startsWith('optimistic_') && g.conversation_id === incomingConv) {
                    removeFromIndices(gid, g.workflow_id, g.conversation_id);
                    delete activeGenStore.gens[gid];
                }
            }
        }
        // A fresh build for this workflow supersedes any prior DEAD gen
        // (`failed` = errored, `stopped` = user-stopped). Without this they
        // linger forever — eviction otherwise only happens on a same-conversation
        // commit or a reconnect snapshot — and, because gens render by
        // workflow, a crashed/stopped run shadows every later build as a
        // phantom "Response interrupted by user" turn (the only cure being a
        // reload). `interrupted` gens are left alone: they auto-resume and the
        // resumed turn merges onto them via composeMessages' continuesInterrupted.
        const startedWf = data.workflow_id;
        if (startedWf) {
            for (const [gid, g] of Object.entries(activeGenStore.gens)) {
                if (gid !== data.gen_id && g.workflow_id === startedWf && (g.failed || g.stopped)) {
                    removeFromIndices(gid, g.workflow_id, g.conversation_id);
                    delete activeGenStore.gens[gid];
                }
            }
        }
        const gen: ActiveGeneration = {
            gen_id: data.gen_id,
            workflow_id: data.workflow_id || null,
            conversation_id: incomingConv,
            prompt: data.prompt || '',
            started_at: typeof data.started_at === 'number' ? data.started_at : Date.now() / 1000,
            text: '',
            events: [],
            edit_steps: [],
            status: '',
            lastEventAt: Date.now(),
        };
        activeGenStore.gens[gen.gen_id] = gen;
        indexByWorkflow(gen);
        indexByConversation(gen);
    });

    onSocketEvent('active_gen:text_chunk' as any, (data: any) => {
        const gen = activeGenStore.gens[data?.gen_id];
        if (gen) { gen.text += (data.delta as string) || ''; touch(gen); }
    });

    onSocketEvent('active_gen:status' as any, (data: any) => {
        const gen = activeGenStore.gens[data?.gen_id];
        if (gen) { gen.status = (data.status as string) || ''; touch(gen); }
    });

    onSocketEvent('active_gen:token_progress' as any, (data: any) => {
        const gen = activeGenStore.gens[data?.gen_id];
        if (gen && typeof data.total_tokens === 'number') {
            // Absolute count — overwrite, don't accumulate. touch() makes this
            // a liveness frame: during a long suppressed <field> body or a
            // node drafting LLM call it's the only signal proving the run is alive,
            // so the staleness watchdog won't false-flag it as interrupted.
            gen.tokensProcessed = data.total_tokens;
            touch(gen);
        }
    });

    onSocketEvent('active_gen:graph_event' as any, (data: any) => {
        const gen = activeGenStore.gens[data?.gen_id];
        if (gen && data.event && typeof data.event === 'object') {
            touch(gen);
            gen.events.push(data.event);
            // Mirror the mutation into liveGraphStore so the canvas
            // surfaces nodes that arrived while it was unmounted (or
            // before the canvas response stream had subscribed). The
            // import is at module top — liveGraphStore + activeGenStore
            // form a cycle, but listener code only runs after both
            // module bodies have completed, so this is safe.
            if (gen.workflow_id) {
                applyAgenticGraphEvent(gen.workflow_id, data.event);
            }
        }
    });

    onSocketEvent('active_gen:edit_step' as any, (data: any) => {
        const gen = activeGenStore.gens[data?.gen_id];
        if (!gen) return;
        touch(gen);
        const step = (data.step as string) || '';
        if (!step) return;
        const last = gen.edit_steps[gen.edit_steps.length - 1];
        if (last !== step) gen.edit_steps.push(step);
    });

    onSocketEvent('active_gen:terminal' as any, (data: any) => {
        const gen_id = data?.gen_id;
        if (!gen_id) return;
        // outcome:'interrupted' = the event relay observed the producer (backend
        // container) drop mid-run — the PRIMARY, event-driven liveness signal.
        // Don't evict: mark the gen interrupted so InterruptedRunBanner surfaces
        // it and auto-resumes from the checkpoint (same path the FE staleness
        // watchdog drives as a slow backstop — it skips already-interrupted
        // gens, so the two never conflict). There's no committed history to
        // adopt here, so we skip the rest of the terminal handling.
        if (data.outcome === 'interrupted') {
            const gen = activeGenStore.gens[gen_id];
            if (gen && !gen.stopped) gen.interrupted = true;
            return;
        }
        // outcome:'failed' = the run errored (e.g. a mid-stream LLM error). Like
        // interrupted, KEEP the gen (don't evict) so the bubble stays with the
        // error + a Retry, instead of silently vanishing.
        if (data.outcome === 'failed') {
            const gen = activeGenStore.gens[gen_id];
            if (gen && !gen.stopped) {
                gen.failed = true;
                gen.error = (data.error as string) || 'Generation failed';
                gen.errorCode = (data.error_code as string) || undefined;
                gen.errorMeta = (data.error_meta as Record<string, string>) || undefined;
            }
            return;
        }
        commitTerminal(gen_id, data);
    });
}

/** The commit half of the terminal handling — shared by the socket listener
    and the silent-pause reconciler, which rebuilds a dropped terminal frame
    from the durable conversation row. */
function commitTerminal(gen_id: string, data: any): void {
    {
        // Stash the committed patch so useConversation can adopt it on the
        // same render that the gen evicts. ref() prevents Valtio from
        // deeply proxying the message array (it's read-only from our POV).
        if (data.committed_conversation_id && Array.isArray(data.committed_messages)) {
            activeGenStore.lastCommitted[data.committed_conversation_id] =
                ref(data.committed_messages as PersistedMessage[]);
            activeGenStore.lastCommittedAt[data.committed_conversation_id] = Date.now();
        }
        // A commit supersedes any lingering interrupted ("dead run") gen for the
        // same conversation: the resumed turn is now in committed history, so the
        // dead gen would otherwise re-render as a duplicate turn on top of it.
        if (data.committed_conversation_id) {
            for (const [gid, g] of Object.entries(activeGenStore.gens)) {
                if (gid !== gen_id && (g.interrupted || g.failed) && g.conversation_id === data.committed_conversation_id) {
                    removeFromIndices(gid, g.workflow_id, g.conversation_id);
                    delete activeGenStore.gens[gid];
                }
            }
        }
        // Drop from active map + indices.
        const gen = activeGenStore.gens[gen_id];
        let wfToCollapse: string | null = null;
        if (gen) {
            const wfId = gen.workflow_id;
            const wasLastForWorkflow = removeFromIndices(gen_id, wfId, gen.conversation_id);
            // Last gen for this workflow ended — collapse any lingering
            // editing animations. Mirrors the pause-bridge collapse so
            // natural completion also drops nodes out of the glow.
            if (wfId && wasLastForWorkflow) wfToCollapse = wfId;
        }
        // B3: the live `input_request` delta that opens the ask drawer is
        // transient and lands on the canvas hook's per-gen subscription, which
        // can miss it (cold start / reconnect / not-yet-subscribed) — leaving
        // the run looking stuck until a full reload. The terminal carries the
        // pending_ask in committed_messages and is handled by THIS always-on
        // listener, so re-surface the drawer from it. The bridge de-dups (same
        // ask is idempotent; answered/dismissed asks are filtered), so a double
        // dispatch alongside the live path is harmless.
        if (data.outcome === 'paused' && Array.isArray(data.committed_messages)) {
            const lastAsst = [...data.committed_messages]
                .reverse()
                .find((m: PersistedMessage) => m && m.role === 'assistant');
            const ask = lastAsst?.pending_ask;
            if (ask?.ask_id && Array.isArray(ask.inputs) && ask.inputs.length) {
                document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
                    detail: {
                        inputs: ask.inputs,
                        title: ask.title || undefined,
                        conversationId: data.committed_conversation_id || gen?.conversation_id || null,
                        askId: ask.ask_id,
                        generationId: gen_id,
                        workflowId: gen?.workflow_id || undefined,
                    },
                }));
            }
        }
        delete activeGenStore.gens[gen_id];
        if (wfToCollapse) clearGraphAnimations(wfToCollapse);
    }
}

function insertSorted(list: string[], gen_id: string): string[] {
    if (list.includes(gen_id)) return list;
    list.push(gen_id);
    list.sort((a, b) => {
        const aT = activeGenStore.gens[a]?.started_at ?? 0;
        const bT = activeGenStore.gens[b]?.started_at ?? 0;
        return aT - bT;
    });
    return list;
}

function indexByWorkflow(gen: ActiveGeneration): void {
    if (!gen.workflow_id) return;
    activeGenStore.byWorkflow[gen.workflow_id] = insertSorted(
        activeGenStore.byWorkflow[gen.workflow_id] || [],
        gen.gen_id,
    );
}

function indexByConversation(gen: ActiveGeneration): void {
    if (!gen.conversation_id) return;
    activeGenStore.byConversation[gen.conversation_id] = insertSorted(
        activeGenStore.byConversation[gen.conversation_id] || [],
        gen.gen_id,
    );
}

/** Remove a gen from both indices. Returns true iff the workflow's
 *  list became empty (so the caller can collapse any per-workflow side
 *  effects, e.g. lingering editing animations). */
function removeFromIndices(
    gen_id: string,
    workflow_id: string | null,
    conversation_id: string | null | undefined,
): boolean {
    let wfBecameEmpty = false;
    if (workflow_id && activeGenStore.byWorkflow[workflow_id]) {
        const next = activeGenStore.byWorkflow[workflow_id].filter(id => id !== gen_id);
        if (next.length === 0) {
            delete activeGenStore.byWorkflow[workflow_id];
            wfBecameEmpty = true;
        } else {
            activeGenStore.byWorkflow[workflow_id] = next;
        }
    }
    if (conversation_id && activeGenStore.byConversation[conversation_id]) {
        const next = activeGenStore.byConversation[conversation_id].filter(id => id !== gen_id);
        if (next.length === 0) {
            delete activeGenStore.byConversation[conversation_id];
        } else {
            activeGenStore.byConversation[conversation_id] = next;
        }
    }
    return wfBecameEmpty;
}

// ── Staleness watchdog ───────────────────────────────────────────────────
// A run whose container is drained/hard-killed mid-stream stops emitting
// frames but never sends active_gen:terminal, so the gen would otherwise sit
// "streaming" forever (the 2026-06-17 stuck-on-"Modifying workflow" bug).
// Frame-silence alone is NOT a usable signal: a legitimately slow node drafter
// streams a single large field with no intermediate frames. The reliable
// signal is the socket — a live-but-slow run keeps its connection, a dead
// container drops it and the gen receives no frames after the reconnect. So
// we mark a gen interrupted on post-reconnect silence (primary), with an
// absolute-silence backstop for the rare socket-up-but-wedged case.

const RECONNECT_SILENCE_MS = 20_000;     // no frame within 20s of a reconnect → container gone
const ABSOLUTE_SILENCE_MS = 5 * 60_000;  // 5min total silence → wedged, even with the socket up
const WATCHDOG_TICK_MS = 5_000;

let _lastReconnectAt: number | null = null;

function touch(gen: ActiveGeneration): void {
    gen.lastEventAt = Date.now();
    // A fresh frame proves the run is alive — undo any prior stale judgment.
    if (gen.interrupted) gen.interrupted = false;
}

/** Mark active gens whose container is almost certainly gone as interrupted.
 *  Exported so tests (and callers) can drive it deterministically instead of
 *  waiting on the interval. `now`/`reconnectedAt` are injectable for the same
 *  reason. Returns the gen_ids newly marked. */
export function markStaleGensInterrupted(
    now: number = Date.now(),
    reconnectedAt: number | null = _lastReconnectAt,
): string[] {
    const marked: string[] = [];
    for (const gen of Object.values(activeGenStore.gens)) {
        if (gen.stopped || gen.interrupted || gen.failed) continue;
        if (gen.gen_id.startsWith('optimistic_')) continue; // pre-`started` placeholder, not a real run yet
        const postReconnectSilence =
            reconnectedAt !== null &&
            gen.lastEventAt < reconnectedAt &&
            now - reconnectedAt > RECONNECT_SILENCE_MS;
        const absoluteSilence = now - gen.lastEventAt > ABSOLUTE_SILENCE_MS;
        if (postReconnectSilence || absoluteSilence) {
            gen.interrupted = true;
            marked.push(gen.gen_id);
        }
    }
    return marked;
}

// ── Silent-pause reconciler ─────────────────────────────────────────────
// The paused terminal is a SINGLE frame; when the relay drops it, the run
// finished backend-side while the FE shimmer spun for the full 5-minute
// wedge backstop, then auto-resumed — costing the user five stuck minutes
// and a duplicate brain turn (2026-08-10). A dropped PAUSE is cheaply
// detectable: conversations.pending_ask is durable BEFORE the terminal is
// sent, so a gen that is frame-silent while its conversation carries a
// pending_ask has definitively parked. Probe after short silence and
// rebuild the terminal from the conversation row. Silence WITHOUT a
// pending ask stays ambiguous (a slow node drafter streams no frames) — that
// case keeps the 5-minute judgment.

const PROBE_SILENCE_MS = 30_000;
const _lastProbeAt = new Map<string, number>();

async function probeSilentGen(gen: ActiveGeneration): Promise<void> {
    const { sendEventAsync } = await import('~/lib/socket-sender');
    try {
        const status: any = await sendEventAsync({
            event_name: 'conversation:get_latest_for_workflow',
            workflow_id: gen.workflow_id,
        } as never);
        const live = activeGenStore.gens[gen.gen_id];
        if (!live || live.stopped || live.interrupted || live.failed) return;
        if (Date.now() - live.lastEventAt < PROBE_SILENCE_MS) return; // frames resumed
        if (!status?.has_pending_ask) return; // ambiguous — the backstop owns it
        const convId = status.conversation_id as string | null;
        if (live.conversation_id && convId && live.conversation_id !== convId) return;
        let messages: unknown[] = [];
        if (convId) {
            try {
                const resume: any = await sendEventAsync({
                    event_name: 'conversation:resume',
                    session_id: convId,
                } as never);
                if (Array.isArray(resume?.messages)) messages = resume.messages;
            } catch {
                // Committing without messages still unwedges the shimmer;
                // the drawer then rehydrates via the normal resume path.
            }
        }
        commitTerminal(gen.gen_id, {
            outcome: 'paused',
            committed_conversation_id: convId ?? live.conversation_id ?? null,
            ...(messages.length ? { committed_messages: messages } : {}),
        });
    } catch {
        // Probe failure: leave the 5-minute backstop to judge.
    }
}

function probeSilentGens(now: number = Date.now()): void {
    for (const gen of Object.values(activeGenStore.gens)) {
        if (gen.stopped || gen.interrupted || gen.failed) continue;
        if (gen.gen_id.startsWith('optimistic_')) continue;
        if (!gen.workflow_id) continue;
        if (now - gen.lastEventAt < PROBE_SILENCE_MS) continue;
        const last = _lastProbeAt.get(gen.gen_id) ?? 0;
        if (now - last < PROBE_SILENCE_MS) continue; // one probe per silence window
        _lastProbeAt.set(gen.gen_id, now);
        void probeSilentGen(gen);
    }
}

let _watchdogStarted = false;
function startStalenessWatchdog(): void {
    if (_watchdogStarted || typeof window === 'undefined') return;
    _watchdogStarted = true;
    // socket-receiver dispatches this on the main socket's reconnect; a gen
    // silent across the reconnect boundary is one whose old container is gone.
    document.addEventListener('noclick:socket:reconnected', () => {
        _lastReconnectAt = Date.now();
    });
    window.setInterval(() => {
        markStaleGensInterrupted();
        probeSilentGens();
    }, WATCHDOG_TICK_MS);
}

startStalenessWatchdog();

// Install eagerly on first import — see header comment.
ensureActiveGenListener();

// ── Cross-module pause bridge ───────────────────────────────────────────
// Vite's dev module loader can produce duplicate module instances when
// the same file is imported via slightly different specifiers (with vs
// without `.ts`, alias-resolved vs absolute, etc.). When that happens,
// the socket listener populates ONE instance's proxy and the React
// closure reads from ANOTHER, so a "stop" click iterates an empty
// `gens` map and quietly emits nothing.
//
// The fix: route stop clicks through a CustomEvent that EVERY duplicate
// of this module listens for. Each instance pauses what its own proxy
// holds — since one of them is the populated one, the gen always gets
// paused regardless of which instance the click closure reached.

let _pauseBridgeInstalled = false;

function pauseAllGensInThisInstance(): void {
    // 1. Tell the BE to cancel each gen's CancelScope (one pause per
    //    unique conversation_id; deduped because multiple gens can
    //    share a conv).
    const sentConvIds = new Set<string>();
    for (const gen of Object.values(activeGenStore.gens)) {
        const cid = gen.conversation_id;
        if (cid && !sentConvIds.has(cid)) {
            sentConvIds.add(cid);
            sendEvent(AgentPauseRequest.create({ conversation_id: cid }));
        }
    }
    // 2. Mark every gen `stopped`. Doing this instead of evicting
    //    keeps the in-flight bubble visible while the BE drains its
    //    stream (which can take seconds) — composeMessages reads the
    //    flag and renders the bubble as a completed/interrupted turn
    //    rather than a streaming one. `isStreaming` (driven by
    //    activeGensForWorkflow().length, which now filters out
    //    stopped gens) flips false synchronously, so the chat-box
    //    button + spinner snap to the stopped state instantly.
    //
    //    The BE's terminal frame, when it lands, evicts the gen from
    //    `gens`/`byWorkflow` and writes `lastCommitted` — which
    //    useConversation adopts to swap the optimistic stopped bubble
    //    for the canonical persisted turn (with "Response interrupted
    //    by user" appended by the BE).
    const wfsToCollapse = new Set<string>();
    for (const gen of Object.values(activeGenStore.gens)) {
        gen.stopped = true;
        if (gen.workflow_id) wfsToCollapse.add(gen.workflow_id);
    }
    // 3. Collapse the editing/adding animation on every node that was
    //    actively being edited. The BE doesn't emit per-node `complete`
    //    frames on user-interruption (CancelScope trips mid-config),
    //    so without this the canvas would render half-edited nodes in
    //    the active-edit glow forever.
    for (const wfId of wfsToCollapse) {
        clearGraphAnimations(wfId);
    }
    // Keep byWorkflow intact — the bubbles need to keep showing until
    // the BE's terminal frame swaps them for the committed history.
    // `isStreaming` filters out `stopped` gens (see useConversation),
    // so the chat-box button still flips state synchronously.
}

function installPauseBridge(): void {
    if (_pauseBridgeInstalled || typeof document === 'undefined') return;
    _pauseBridgeInstalled = true;
    document.addEventListener('noclick:active-gens:pause-all', pauseAllGensInThisInstance);
}

installPauseBridge();

/** Register a placeholder gen entry the moment the user submits a
 *  fresh prompt, so the chat switches to the new conversation INSTANTLY
 *  (showing the user's bubble + a streaming-thinking bubble) instead
 *  of flashing the welcome view during the BE round-trip to `started`.
 *
 *  When the real `active_gen:started` arrives for the same
 *  conversation_id, the listener above evicts the optimistic entry
 *  and registers the authoritative gen. The chat continues seamlessly
 *  because both gens compose the same [user, asst-streaming] shape.
 *
 *  Returns the optimistic gen_id so callers can target it if needed
 *  (e.g. to update its prompt mid-flight, though normally the real
 *  gen takes over before that's needed). */
export function registerOptimisticGen(args: {
    workflow_id?: string | null;
    conversation_id: string;
    prompt: string;
}): string {
    // crypto.randomUUID gives a collision-free id; the `optimistic_` prefix
    // is what the eviction logic and snapshot-preserve filter key off.
    const uniq = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const gen_id = `optimistic_${uniq}`;
    const gen: ActiveGeneration = {
        gen_id,
        workflow_id: args.workflow_id || null,
        conversation_id: args.conversation_id,
        prompt: args.prompt,
        started_at: Date.now() / 1000,
        text: '',
        events: [],
        edit_steps: [],
        status: '',
        lastEventAt: Date.now(),
    };
    activeGenStore.gens[gen_id] = gen;
    indexByWorkflow(gen);
    indexByConversation(gen);
    return gen_id;
}

/** Dispatched by the FE stop button. Every duplicate-loaded copy of
 *  this module pauses what its own proxy contains, so the right
 *  instance always responds even when Vite has loaded the module
 *  twice. Safe to call from any importer. */
export function dispatchPauseAllActiveGens(): void {
    if (typeof document === 'undefined') return;
    document.dispatchEvent(new CustomEvent('noclick:active-gens:pause-all'));
}

/** Remove a gen from the store + both indices. Used by the interrupted-run
 *  auto-resume to drop a dead run once its resume has been kicked off, so the
 *  fresh run's bubble takes over the chat instead of leaving a stale duplicate. */
export function evictGen(genId: string): void {
    const gen = activeGenStore.gens[genId];
    if (!gen) return;
    removeFromIndices(genId, gen.workflow_id, gen.conversation_id);
    delete activeGenStore.gens[genId];
}

// ── Read helpers (used by useConversation hook) ─────────────────────────

export function activeGensForWorkflow(workflowId: string): ActiveGeneration[] {
    const ids = activeGenStore.byWorkflow[workflowId];
    if (!ids || ids.length === 0) return [];
    return ids
        .map(id => activeGenStore.gens[id])
        .filter((g): g is ActiveGeneration => !!g);
}

export function activeGensForConversation(conversationId: string): ActiveGeneration[] {
    const ids = activeGenStore.byConversation[conversationId];
    if (!ids || ids.length === 0) return [];
    return ids
        .map(id => activeGenStore.gens[id])
        .filter((g): g is ActiveGeneration => !!g);
}

/** Pop and return the latest committed patch for a conversation, if any.
 *  Caller is expected to apply it to its persistedMessages and clear via
 *  this same call's return — read-once semantics avoid the patch being
 *  reapplied on subsequent renders. */
export function takeCommittedPatch(conversationId: string): PersistedMessage[] | null {
    const patch = activeGenStore.lastCommitted[conversationId];
    if (!patch) return null;
    delete activeGenStore.lastCommitted[conversationId];
    return patch;
}
