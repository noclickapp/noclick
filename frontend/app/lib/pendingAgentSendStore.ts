// Carries an opening message from the Run popup to an agent's chat block,
// which lives in a sibling subtree (WorkflowInterface) and mounts a few frames
// after the hand-off is decided.
//
// Why a store rather than a custom event: the block does not exist yet when the
// popup's Run is pressed — the Interface tab has to render and reconcile its
// sub-tabs first — so a one-shot dispatch lands before anyone is listening.
// Sticky state is drained whenever the block gets there, however late. (Same
// lesson as any one-shot event whose listener mounts after the producer.)
//
// The message is delivered by the chat's OWN submit path, not by a raw
// workflow:execute — that is what echoes the user's bubble locally (the backend
// does not replay chat:message to its sender), and it also picks up the chat's
// model resolution, credential check and streaming state for free.

import { proxy } from 'valtio';

// Keyed by workflow AND node: duplicating a workflow keeps its node ids, so a
// node-only key would let a message queued in one workflow drain — and bill a
// turn — in its copy's chat.
const keyOf = (workflowId: string | null | undefined, nodeId: string) =>
    `${workflowId ?? ''}:${nodeId}`;

export const pendingAgentSendStore = proxy<{
    /** workflow:node → the message its chat should send as soon as it mounts. */
    byNode: Record<string, string>;
}>({ byNode: {} });

export function queueAgentChatSend(
    workflowId: string | null | undefined,
    nodeId: string,
    message: string
): void {
    if (!nodeId) return;
    pendingAgentSendStore.byNode[keyOf(workflowId, nodeId)] = message;
}

/** Read and clear in one step, so a re-render can't send the message twice. */
export function takeQueuedAgentChatSend(
    workflowId: string | null | undefined,
    nodeId: string
): string | undefined {
    const key = keyOf(workflowId, nodeId);
    const message = pendingAgentSendStore.byNode[key];
    if (message === undefined) return undefined;
    delete pendingAgentSendStore.byNode[key];
    return message;
}
