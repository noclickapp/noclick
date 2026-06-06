// Bridges the sidebar chat's per-workflow active-conversation resolution
// (useSidebarConversation — the source of truth) to the canvas edit hook
// (useCanvasWorkflowEdit), which lives in a SIBLING subtree (FlowCanvas) and so
// can't read the sidebar's state directly.
//
// Why this exists: useCanvasWorkflowEdit.checkPendingAsk reconciles the
// paused-<ask/> drawer against the server (workflow:builder:list_pending) and
// clears the drawer when no paused run matches "the active conversation". It
// used to read a stale GLOBAL slot (useCachedValtioState('chat','conversationId'))
// that diverged from the per-workflow conversation the chat actually shows — so
// on restore it reconciled against the WRONG conversation, found no match, and
// cleared the freshly-opened ask drawer (visible flash). Reading the same
// per-workflow id the sidebar resolved keeps open/clear in agreement.

import { proxy } from 'valtio';

export const activeConversationStore = proxy<{
    /** workflowId → the conversation id the sidebar chat is currently showing. */
    byWorkflow: Record<string, string>;
}>({ byWorkflow: {} });

export function setActiveConversationForWorkflow(workflowId: string, conversationId: string): void {
    if (!workflowId || !conversationId) return;
    if (activeConversationStore.byWorkflow[workflowId] === conversationId) return;
    activeConversationStore.byWorkflow[workflowId] = conversationId;
}
