// Conversation-id manager for the sidebar chat.
//
// Resolves the active conversation_id from a layered set of sources,
// each tried in priority order, every time the active workflow changes:
//
//   1. activeGenStore — any in-flight gen for the workflow wins.
//   2. sessionStorage map (this tab's record of "wf X has been chatted
//      against conv Y", populated automatically as gens register).
//   3. BE `conversation:get_latest_for_workflow` — fallback for the
//      first encounter in this tab.
//   4. Fresh uuid (optimistic placeholder during the BE lookup).
//
// Why the sessionStorage layer: in practice the BE's lookup is not
// reliable — `conversations.workflow_id` isn't always populated when a
// chat is saved, so the lookup can return null even for workflows the
// user has actively chatted in. Recording the (workflow_id,
// conversation_id) pair locally as soon as a gen registers gives us a
// reliable same-tab restoration story; the BE lookup remains the
// fallback for cross-tab / cross-session restoration on first encounter.
//
// For the no-workflow context (standalone chats), the scratch slot
// lives in its own sessionStorage key so it persists across canvas
// navigations within the tab without sharing the per-workflow map.

import { useCallback, useEffect, useRef, useState } from 'react';
import { subscribe } from 'valtio';
import { sendEventAsync, GetLatestConversationForWorkflowRequest } from '~/lib/socket-sender';
import { activeGenStore } from '~/lib/activeGenStore';
import { setActiveConversationForWorkflow } from '~/lib/activeConversationStore';
import { readJson, writeJson, readString, writeString, freshConversationId } from '~/lib/chat-storage';

const SCRATCH_KEY = 'noclick:chat:scratchConversationId';
const MAP_KEY = 'noclick:chat:convByWorkflow';

function loadScratch(): string {
    const stored = readString(SCRATCH_KEY);
    if (stored) return stored;
    const id = freshConversationId();
    writeString(SCRATCH_KEY, id);
    return id;
}

function getMappedConv(workflowId: string): string | null {
    return readJson<Record<string, string>>(MAP_KEY, {})[workflowId] ?? null;
}

function recordMapping(workflowId: string, conversationId: string): void {
    const m = readJson<Record<string, string>>(MAP_KEY, {});
    if (m[workflowId] === conversationId) return;
    m[workflowId] = conversationId;
    writeJson(MAP_KEY, m);
}

function liveGenConvForWorkflow(workflowId: string): string | null {
    const ids = activeGenStore.byWorkflow[workflowId];
    if (!ids?.length) return null;
    return activeGenStore.gens[ids[0]]?.conversation_id ?? null;
}

export interface SidebarConversationApi {
    conversationId: string;
    setConversationId: (id: string) => void;
    startFreshConversation: () => void;
    switchToConversation: (id: string) => void;
}

export function useSidebarConversation(
    activeWorkflowId: string | null | undefined,
): SidebarConversationApi {
    const [conversationId, setConvIdState] = useState<string>(loadScratch);

    // Resolve on workflow change. Synchronous-first sources (live gens,
    // local map), then async BE fallback with an optimistic placeholder
    // so a send during the lookup window doesn't write to the previous
    // slot's id.
    useEffect(() => {
        if (!activeWorkflowId) {
            setConvIdState(loadScratch());
            return;
        }
        const liveConv = liveGenConvForWorkflow(activeWorkflowId);
        if (liveConv) {
            setConvIdState(liveConv);
            recordMapping(activeWorkflowId, liveConv);
            return;
        }
        const mapped = getMappedConv(activeWorkflowId);
        if (mapped) {
            setConvIdState(mapped);
            return;
        }
        // No local knowledge → optimistic placeholder, then BE lookup.
        const optimistic = freshConversationId();
        setConvIdState(optimistic);
        let cancelled = false;
        void (async () => {
            try {
                const lookup = await sendEventAsync(
                    GetLatestConversationForWorkflowRequest.create({ workflow_id: activeWorkflowId }),
                ) as { conversation_id?: string | null };
                if (cancelled) return;
                // Race-check: if the user already sent on the optimistic id,
                // their active work wins.
                if (activeGenStore.byConversation[optimistic]?.length) {
                    recordMapping(activeWorkflowId, optimistic);
                    return;
                }
                if (liveGenConvForWorkflow(activeWorkflowId)) return; // subscription handles
                if (lookup.conversation_id) {
                    setConvIdState(lookup.conversation_id);
                    recordMapping(activeWorkflowId, lookup.conversation_id);
                }
                // else: keep the optimistic — it'll be recorded when the
                // user sends and a gen registers (the mirror effect below).
            } catch (err) {
                console.warn('[useSidebarConversation] lookup failed', err);
            }
        })();
        return () => { cancelled = true; };
    }, [activeWorkflowId]);

    // Subscribe to activeGenStore — adopt any gen that appears for the
    // currently-active workflow, and record (workflow_id, conv_id) pairs
    // into the local map.
    //
    // Dedup via `recordedRef`: gen-store mutations fire on every
    // text_chunk frame (~10/sec while streaming). Without the dedup,
    // recordMapping's sessionStorage.getItem + JSON.parse would run for
    // every gen on every frame.
    const recordedRef = useRef<Set<string>>(new Set());
    useEffect(() => {
        const onGenStoreChange = () => {
            for (const gen of Object.values(activeGenStore.gens)) {
                if (!gen?.workflow_id || !gen?.conversation_id) continue;
                const key = `${gen.workflow_id}:${gen.conversation_id}`;
                if (!recordedRef.current.has(key)) {
                    recordedRef.current.add(key);
                    recordMapping(gen.workflow_id, gen.conversation_id);
                }
                if (gen.workflow_id === activeWorkflowId) {
                    setConvIdState(prev =>
                        prev === gen.conversation_id ? prev : gen.conversation_id!,
                    );
                }
            }
        };
        onGenStoreChange();
        return subscribe(activeGenStore, onGenStoreChange);
    }, [activeWorkflowId]);

    // Publish the resolved (workflow → conversation) pair to the shared store so
    // the canvas edit hook (sibling subtree) reconciles its paused-ask drawer
    // against the SAME conversation the chat shows — see activeConversationStore.
    useEffect(() => {
        if (activeWorkflowId && conversationId) {
            setActiveConversationForWorkflow(activeWorkflowId, conversationId);
        }
    }, [activeWorkflowId, conversationId]);

    const setConversationId = useCallback((id: string) => {
        setConvIdState(id);
        if (activeWorkflowId) {
            recordMapping(activeWorkflowId, id);
        } else {
            writeString(SCRATCH_KEY, id);
        }
    }, [activeWorkflowId]);

    const startFreshConversation = useCallback(() => {
        const id = freshConversationId();
        setConversationId(id);
        document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
    }, [setConversationId]);

    const switchToConversation = useCallback((id: string) => {
        setConversationId(id);
        document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
    }, [setConversationId]);

    return {
        conversationId,
        setConversationId,
        startFreshConversation,
        switchToConversation,
    };
}
