// Live socket subscription primitive for builder runs.
//
// After the builder_generations collapse, "snapshot recovery" is gone — the
// only thing this module still owns is the singleton-per-gen subscription
// helper used by the canvas hook + headless builder to route a run's
// response events to a single in-page listener.
//
// Cross-session resume (paused-on-ask) now works through conversations.events
// directly: useSidebarConversation.restoreForEditor reads the conversation,
// the trailing assistant carries pending_ask, and BuilderInputBridge surfaces
// the drawer. No FE-side hydration step required.

import { onSocketEvent } from '~/lib/socket-receiver';

/**
 * Timeout for a `workflow:builder:edit` request. The agentic builder runs
 * multiple LLM turns and can sit on <ask/> for minutes-to-hours, so the
 * default sendEventAsync timeout (30s) would tear down the response listener
 * mid-stream and drop every subsequent chunk.
 */
export const BUILDER_EDIT_TIMEOUT_MS = 3 * 60 * 60 * 1000;

// Per-gen subscriptions. At most one active subscription exists per
// generation_id — a second subscriber for the same gen kicks the previous
// one off the socket. This prevents the dupe-text bug when control of an
// in-flight gen hands off between drivers (e.g. headless → canvas hook).
const _activeSubscriptions = new Map<string, () => void>();

export function subscribeToBuilderResponse(
    generationId: string,
    handlers: {
        onEvent: (eventData: any) => void;
        onError?: (error: string) => void;
    },
): () => void {
    const previous = _activeSubscriptions.get(generationId);
    if (previous) previous();

    const responseHandler = (response: any) => {
        if (!response || response.request_id !== generationId) return;
        if (response.error) {
            handlers.onError?.(response.error);
            return;
        }
        handlers.onEvent(response.data || response);
    };
    const socketUnsub = onSocketEvent('response', responseHandler);

    const myUnsub = () => {
        if (_activeSubscriptions.get(generationId) !== myUnsub) return;
        socketUnsub();
        _activeSubscriptions.delete(generationId);
    };
    _activeSubscriptions.set(generationId, myUnsub);
    return myUnsub;
}
