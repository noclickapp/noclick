// Bridge component that connects agentic builder input_request events to the ChatDrawer.
// Lives inside ChatDrawerProvider context. Listens for DOM events, registers the
// BuilderInputDrawer when inputs arrive, and sends responses back via socket.
//
// Two ways an ask can show up:
//   1. Live: backend emits an input_request socket event during a turn
//      that hits <ask/>; the canvas hook / headless builder dispatches
//      noclick:builder:input:request with the payload.
//   2. Restored: the user opens a workflow whose latest conversation is
//      paused on <ask/>. useSidebarConversation pulls the conversation
//      from conversations.events; the trailing assistant carries
//      pendingAsk; this bridge watches the messages prop and dispatches
//      noclick:builder:input:request itself.
//
// Ownership model: each input_request carries the workflowId it belongs to.
// The bridge subscribes to the active workflow editor; if the user navigates
// to a different workflow (or out of any editor), the drawer self-closes.

import { useEffect, useCallback, useState, useRef, lazy, Suspense } from 'react';
import { useSnapshot } from 'valtio';
import { useDrawer } from '~/hooks/useDrawer';
// Lazy: this drawer reuses editor config fields (DynamicOptionsField →
// ReferenceAutocompleteContext) that pull the node registry; the chat is always
// mounted, so it loads only when the builder actually asks for input.
const BuilderInputDrawer = lazy(() =>
    import('~/components/chat/drawer/BuilderInputDrawer').then(m => ({ default: m.BuilderInputDrawer }))
);
import { sendEvent, sendEventAsync } from '~/lib/socket-sender';
import { getBackendGraphSnapshot } from '~/lib/liveGraphStore';
import { useActiveWorkflowEditorId } from '~/components/workflow/WorkflowContext';
import { setPendingBuilderAsk } from '~/lib/pendingBuilderAsk';
import { activeGenStore, registerOptimisticGen } from '~/lib/activeGenStore';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';
import type { Message } from '~/components/chat/types';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

const INPUT_TYPES = new Set<InputRequest['type']>([
    'credential',
    'selection',
    'text',
    'config',
    'env',
]);

function isInputRequest(value: unknown): value is InputRequest {
    if (!value || typeof value !== 'object') return false;
    const candidate = value as Record<string, unknown>;
    return (
        typeof candidate.id === 'string' &&
        typeof candidate.nodeId === 'string' &&
        typeof candidate.type === 'string' &&
        INPUT_TYPES.has(candidate.type as InputRequest['type']) &&
        typeof candidate.label === 'string' &&
        typeof candidate.description === 'string' &&
        typeof candidate.required === 'boolean'
    );
}

const DRAWER_ID = 'builder-input';

// Module-level FIFO of ask_ids the user has already answered or
// dismissed in this session. Survives component remounts within the
// same tab so a persisted conversation that still carries
// `pending_ask` (because the BE didn't clear it on resume terminal)
// can't re-surface the same ask drawer. Bounded to prevent unbounded
// growth on long sessions.
const DISMISSED_ASK_LIMIT = 250;
const _dismissedAskOrder: string[] = [];
const _dismissedAskIds = new Set<string>();
function recordDismissedAsk(askId: string): void {
    if (_dismissedAskIds.has(askId)) return;
    _dismissedAskIds.add(askId);
    _dismissedAskOrder.push(askId);
    while (_dismissedAskOrder.length > DISMISSED_ASK_LIMIT) {
        const evicted = _dismissedAskOrder.shift();
        if (evicted) _dismissedAskIds.delete(evicted);
    }
}

interface PendingAskState {
    inputs: InputRequest[];
    title?: string;
    /** Conversation this ask belongs to. The backend's input_response
     *  handler keys on conversation_id (not generation_id) for *routing*
     *  the resume to the right paused turn. */
    conversationId: string | null;
    askId: string | null;
    /**
     * Workflow this ask belongs to. When the user navigates to a different
     * workflow editor (or out of any editor), the bridge self-closes. Null
     * means "untagged" — older dispatch sites; we treat those as
     * workflow-agnostic and don't auto-close.
     */
    workflowId: string | null;
    /**
     * Generation ID the canvas hook is subscribed to for THIS resume. The
     * dispatcher (useCanvasWorkflowEdit.resumeFromPending /
     * .handleEditEvent input_request) mints this BEFORE opening the drawer
     * and subscribes to the per-gen ResponseEvent stream. We forward it on
     * submit so the BE tags its events with the same id — without this,
     * the BE mints its own UUID, the FE's subscription never matches, and
     * every per-gen frame (node_updated with credentialIds, text_chunk,
     * generation_complete, …) goes to /dev/null on the canvas side.
     */
    generationId: string | null;
}

interface BuilderInputBridgeProps {
    /** Messages from the active conversation. The bridge surfaces the ask
     *  drawer when the trailing assistant has pendingAsk set. */
    messages?: Message[];
    /** The conversation_id the messages belong to — sent on input_response
     *  so the backend can route the answer to the right conversation. */
    conversationId?: string;
}

export function BuilderInputBridge({ messages, conversationId }: BuilderInputBridgeProps = {}) {
    const { registerDrawer, unregisterDrawer } = useDrawer();
    const { logActivity } = useAnalytics();
    // Dedup the "drawer shown" event by ask_id so a re-dispatch (restore + resume
    // race) doesn't double-count the same ask.
    const lastShownAskRef = useRef<string | null>(null);
    const [pending, setPending] = useState<PendingAskState | null>(null);
    const activeWorkflowEditorId = useActiveWorkflowEditorId();
    // Latest editor id, addressable from inside the request handler closure
    // without re-running the listener subscription on every editor change.
    // Assign synchronously during render so the ref reflects the very-latest
    // value the moment a hydrate-driven `input:request` arrives — using a
    // post-commit useEffect would leave a window where the bridge sees a
    // stale value and rejects a legitimate request.
    const activeEditorRef = useRef<string | undefined>(activeWorkflowEditorId);
    activeEditorRef.current = activeWorkflowEditorId;

    // Live mirror of the drawer's partially-filled answers (cleaned). The drawer
    // owns the form state; it reports changes via onValuesChange so a free-form
    // chatbox reply or field affordance can fold the answers already given into
    // the resume payload — the user never has to repeat themselves.
    const latestAskValuesRef = useRef<Record<string, string>>({});
    const handleValuesChange = useCallback((vals: Record<string, string>) => {
        latestAskValuesRef.current = vals;
    }, []);

    const closeDrawer = useCallback(() => {
        setPending(null);
        latestAskValuesRef.current = {};
        unregisterDrawer(DRAWER_ID);
    }, [unregisterDrawer]);

    // Synchronous mismatch guard: if our pending state belongs to a workflow
    // that isn't the currently-mounted editor, treat it as if we had no
    // pending at all for this render. The post-commit effect will still
    // unregister via closeDrawer, but in the meantime the register/update
    // effect can't re-render the drawer with stale content. This eliminates
    // the "drawer still visible after editor unmount" race that effects-only
    // cleanup leaves open.
    const effectivePending =
        pending && pending.workflowId !== null && pending.workflowId !== activeWorkflowEditorId
            ? null
            : pending;

    // Remote answer auto-close: when this ask's run resumes WITHOUT us (a
    // bridge-link submit, or an answer from another tab), an active generation
    // appears for the conversation — the ask is consumed, so a drawer left
    // open would submit into a mismatched ask_id and be ignored. Close it and
    // remember the ask so the still-persisted pending_ask can't re-surface it
    // before the resume's finalize replaces the conversation tail.
    const activeGenConversations = useSnapshot(activeGenStore).byConversation;
    useEffect(() => {
        const convId = effectivePending?.conversationId;
        if (!convId) return;
        // Exclude the generation that PRODUCED this ask: the input_request
        // arrives before that gen's 'paused' terminal drops it from the
        // active map, so counting it would close the drawer as it opens. A
        // locally-submitted resume also registers a gen, but submit/dismiss
        // null pending in the same handler, so this only fires for remote ones.
        const foreign = (activeGenConversations[convId] ?? []).filter(
            g => g !== effectivePending?.generationId,
        );
        if (!foreign.length) return;
        if (effectivePending?.askId) recordDismissedAsk(effectivePending.askId);
        closeDrawer();
    }, [activeGenConversations, effectivePending, closeDrawer]);

    // Resuming a parked build includes backend startup and state loading, so
    // keep the pending state visible until `active_gen:started` arrives.
    // sometimes tens of seconds in cold containers — during which the chat
    // would otherwise show NO sign that anything is happening (the drawer
    // closes, but no streaming bubble appears and no spinner). Registering
    // an optimistic gen the moment the user submits flips the trailing
    // assistant to in-flight immediately, so MessagesView shows the
    // "Thinking" spinner without waiting for the BE round trip. The real
    // `active_gen:started` evicts the optimistic placeholder on arrival
    // (see the eviction listener in activeGenStore).
    const sendResumePayload = useCallback((extra: Record<string, unknown>) => {
        const pending = effectivePending;
        if (!pending?.conversationId) {
            closeDrawer();
            return;
        }
        registerOptimisticGen({
            workflow_id: pending.workflowId,
            conversation_id: pending.conversationId,
            // Empty prompt = continuation: composeMessages extends the
            // trailing assistant bubble instead of appending a new
            // [user, asst] pair.
            prompt: '',
        });
        // Hand the brain the live canvas graph so a resume reflects the nodes
        // the agent already added, instead of the debounced/stale
        // public.workflows row the backend would otherwise read (B8). Only when
        // the store is a trustworthy source and non-empty; else the backend
        // falls back to the DB.
        const liveGraph = pending.workflowId ? getBackendGraphSnapshot(pending.workflowId) : null;
        sendEvent({
            event_name: 'workflow:builder:input_response' as any,
            conversation_id: pending.conversationId,
            ask_id: pending.askId || undefined,
            ...(pending.generationId ? { generation_id: pending.generationId } : {}),
            ...(liveGraph && liveGraph.nodes.length ? { current_graph: liveGraph } : {}),
            ...extra,
        });
        // Same guard as dismiss — once an ask has been answered,
        // never re-surface it on persisted-state re-render.
        if (pending.askId) {
            recordDismissedAsk(pending.askId);
        }
        closeDrawer();
    }, [closeDrawer, effectivePending]);

    const handleSubmit = useCallback((values: Record<string, string>) => {
        sendResumePayload({ values, dismissed: false });
    }, [sendResumePayload]);

    // Free-form answer: the user typed a message in the chatbox (or picked a
    // field affordance) instead of filling the whole ask form (e.g. "don't have
    // a credential yet, proceed"). Routes to the same input_response handler
    // with a `message` payload AND any fields already answered in the form, so
    // the backend resumes with the partial answers plus the user's words — they
    // never have to re-enter what they already filled in.
    const handleSubmitMessage = useCallback((message: string) => {
        const text = message.trim();
        if (!text) return;
        sendResumePayload({ message: text, values: latestAskValuesRef.current, dismissed: false });
    }, [sendResumePayload]);

    // Dismiss = "skip this ask". The BE still resumes the brain turn (with
    // a system message telling it the user declined), so we want the same
    // optimistic-streaming UX as submit/message — the bubble flips to
    // in-flight immediately instead of waiting for the BE round trip.
    //
    // The dismissedAskIds bookkeeping inside sendResumePayload guards the
    // re-surface effect below: without it, BE pause-on-ask flows that end
    // without a terminal frame leave pending_ask in persisted events, and
    // the ask drawer would pop a second time on re-render.
    const handleDismiss = useCallback(() => {
        sendResumePayload({ values: {}, dismissed: true });
    }, [sendResumePayload]);


    // Listen for input_request events from the builder. Reject at intake
    // when the request is for a workflow other than the currently-mounted
    // editor — without this, the drawer briefly opens on cache-restored
    // hydrate dispatches and closes a render later via the self-close
    // effect, producing a visible flash.
    useEffect(() => {
        const handler = (event: CustomEvent<{
            inputs: InputRequest[];
            title?: string;
            conversationId?: string;
            askId?: string;
            workflowId?: string;
            generationId?: string;
        }>) => {
            const { inputs, title, conversationId: convId, askId, workflowId, generationId } = event.detail;
            if (!inputs?.length) return;
            // Never re-surface an ask the user already answered/dismissed this
            // session. Guards against late/duplicate dispatches — the B3
            // terminal re-surface, or a restored-messages re-render — that
            // would otherwise re-open a drawer the user already dealt with.
            if (askId && _dismissedAskIds.has(askId)) return;
            // Tagged asks must match the active editor. Untagged asks
            // (workflowId omitted) remain workflow-agnostic.
            if (workflowId && workflowId !== activeEditorRef.current) return;
            if (askId && lastShownAskRef.current !== askId) {
                lastShownAskRef.current = askId;
                logActivity(EVENTS.BUILDER_INPUT_BRIDGE_SHOWN, { ask_id: askId, conversation_id: convId ?? null });
            }
            setPending(prev => ({
                inputs,
                title,
                conversationId: convId || null,
                askId: askId || null,
                workflowId: workflowId || null,
                // Preserve a previously-seen generationId when the latest
                // dispatch doesn't carry one. The restored-conversation
                // re-dispatch (no gen_id) can race with
                // resumeFromPending's dispatch (with gen_id) on remount;
                // losing the gen_id would orphan the canvas hook's
                // per-gen subscription.
                generationId: generationId || prev?.generationId || null,
            }));
        };
        document.addEventListener('noclick:builder:input:request', handler as EventListener);
        return () => {
            document.removeEventListener('noclick:builder:input:request', handler as EventListener);
        };
    }, [logActivity]);

    // Restored conversations: when the trailing assistant has pendingAsk
    // set, surface the drawer. Tracked by askId so we don't re-fire when
    // messages re-render for unrelated reasons (text_chunk updates etc.).
    const lastSurfacedAskRef = useRef<string | null>(null);
    useEffect(() => {
        if (!messages || messages.length === 0) return;
        const lastAsst = [...messages].reverse().find(m => !m.isUser);
        const ask = lastAsst?.pendingAsk;
        if (!ask || !ask.ask_id) {
            lastSurfacedAskRef.current = null;
            return;
        }
        if (lastSurfacedAskRef.current === ask.ask_id) return;
        // Already answered/dismissed in this tab session — don't
        // re-surface even if the BE's persisted view still carries
        // pending_ask (BE bug: paused-on-ask resumes that complete
        // without emitting a terminal frame leave pending_ask in the
        // conversation events).
        if (_dismissedAskIds.has(ask.ask_id)) return;
        lastSurfacedAskRef.current = ask.ask_id;
        document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
            detail: {
                inputs: ask.inputs.filter(isInputRequest),
                title: ask.title || undefined,
                conversationId: conversationId,
                askId: ask.ask_id,
                workflowId: activeEditorRef.current,
            },
        }));
        // The dispatch above carries no generationId. Route the restored ask
        // through the canvas hook (resumeFromPending) so it mints a gen and
        // subscribes to the resume's stream — otherwise the answer's frames are
        // orphaned and the run looks stuck after submit (B10). Additive: the
        // hook upgrades the drawer's gen if mounted; the bare dispatch still
        // opens the drawer if it isn't.
        document.dispatchEvent(new CustomEvent('noclick:builder:resume-pending', {
            detail: { conversationId, pendingAsk: ask },
        }));
    }, [messages, conversationId]);

    // Backwards-compatible explicit clear (used by useCanvasWorkflowEdit when
    // it determines the resumed conversation has no pending ask).
    useEffect(() => {
        document.addEventListener('noclick:builder:input:clear', closeDrawer);
        return () => {
            document.removeEventListener('noclick:builder:input:clear', closeDrawer);
        };
    }, [closeDrawer]);

    // Publish the live ask to the pendingBuilderAsk store so the chatbox send
    // path (NoClick.handleWorkflowEditSubmit) can route a typed message into
    // this ask instead of starting a fresh edit turn. effectivePending is
    // already editor-matched, so a non-null value is always valid to route to.
    useEffect(() => {
        setPendingBuilderAsk(
            effectivePending
                ? {
                    workflowId: effectivePending.workflowId,
                    conversationId: effectivePending.conversationId,
                    askId: effectivePending.askId,
                }
                : null,
        );
    }, [effectivePending]);

    // Clear the store on unmount so a stale ask can't outlive the bridge.
    useEffect(() => () => setPendingBuilderAsk(null), []);

    // Mirror the ask open/close transition so the mobile layout (Dashboard) can
    // redirect the user to the chat view while the ask is pending and restore
    // them afterwards. Keyed on the boolean so it fires once per transition.
    const askOpen = !!effectivePending?.inputs.length;
    useEffect(() => {
        document.dispatchEvent(new CustomEvent(askOpen ? 'noclick:builder:ask:open' : 'noclick:builder:ask:close'));
    }, [askOpen]);

    // A chatbox message answering the ask — dispatched by NoClick when the
    // user submits while this ask is pending.
    useEffect(() => {
        const handler = (event: CustomEvent<{ message?: string }>) => {
            const message = event.detail?.message;
            if (message) handleSubmitMessage(message);
        };
        document.addEventListener('noclick:builder:input:submit-message', handler as EventListener);
        return () => {
            document.removeEventListener('noclick:builder:input:submit-message', handler as EventListener);
        };
    }, [handleSubmitMessage]);

    // Post-commit cleanup of mismatched pending state: the synchronous
    // mismatch guard above already prevents the drawer from rendering with
    // stale content this render, but we still need to actually clear pending
    // and unregister so future renders don't accumulate state.
    useEffect(() => {
        if (!pending || pending.workflowId === null) return;
        if (pending.workflowId !== activeWorkflowEditorId) {
            closeDrawer();
        }
    }, [pending, activeWorkflowEditorId, closeDrawer]);

    // Mint (or reuse) the public input-bridge link for the current ask so the
    // user can hand these questions to someone WITHOUT a NoClick account —
    // the same /b/{id} links agent-initiated runs mint automatically. The
    // backend is idempotent per (conversation, ask); answering via the link
    // resumes the run exactly like submitting this drawer would.
    const handleShare = useCallback(async (): Promise<string | null> => {
        const pending = effectivePending;
        if (!pending?.conversationId || !pending.askId) return null;
        try {
            const res = await sendEventAsync<{ success: boolean; url?: string }>({
                event_name: 'workflow:builder:share_ask',
                conversation_id: pending.conversationId,
                ask_id: pending.askId,
            });
            return res.success && res.url ? res.url : null;
        } catch {
            return null;
        }
    }, [effectivePending]);

    // Register/update drawer when effective pending changes (i.e. a pending
    // that's still valid for the current editor). When the editor mismatches,
    // effectivePending is null and we simply skip — the cleanup effect above
    // unregisters whatever was registered last time.
    useEffect(() => {
        if (!effectivePending?.inputs.length) return;
        const canShare = !!(effectivePending.conversationId && effectivePending.askId);
        registerDrawer(
            DRAWER_ID,
            <Suspense fallback={null}>
                <BuilderInputDrawer
                    inputs={effectivePending.inputs}
                    title={effectivePending.title}
                    onSubmit={handleSubmit}
                    onDismiss={handleDismiss}
                    onSubmitMessage={handleSubmitMessage}
                    onValuesChange={handleValuesChange}
                    onShare={canShare ? handleShare : undefined}
                />
            </Suspense>,
            { resizable: true, emphasized: true }
        );
    }, [effectivePending, handleSubmit, handleDismiss, handleSubmitMessage, handleValuesChange, handleShare, registerDrawer]);

    return null;
}
