// Tracks whether the agentic builder is currently paused on an <ask/> for the
// active workflow editor. BuilderInputBridge owns the ask lifecycle and
// publishes here; NoClick.handleWorkflowEditSubmit reads it so a typed chatbox
// message can resume the paused turn (via input_response) instead of starting
// a fresh edit turn. Added so users can answer an ask conversationally
// ("don't have a credential yet, proceed") rather than only via the form.
//
// Backed by a window global rather than module-level state on purpose: Vite's
// dev loader can hand the writer (BuilderInputBridge) and reader (NoClick)
// separate module instances, which would silently desync module-level state
// (the same hazard activeGenStore documents). A window global is a true
// singleton across duplicates.

export interface PendingBuilderAsk {
    /** Workflow editor the ask belongs to (null = workflow-agnostic). */
    workflowId: string | null;
    /** Conversation the answer must be routed to. */
    conversationId: string | null;
    /** The specific ask instance being answered. */
    askId: string | null;
}

declare global {
    interface Window {
        __noclickPendingBuilderAsk?: PendingBuilderAsk | null;
    }
}

export function getPendingBuilderAsk(): PendingBuilderAsk | null {
    if (typeof window === 'undefined') return null;
    return window.__noclickPendingBuilderAsk ?? null;
}

export function setPendingBuilderAsk(next: PendingBuilderAsk | null): void {
    if (typeof window === 'undefined') return;
    window.__noclickPendingBuilderAsk = next;
}
