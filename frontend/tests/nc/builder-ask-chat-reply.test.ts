// Regression test for "answer an <ask/> by typing in the chatbox".
//
// When the agentic builder pauses on <ask/>, BuilderInputBridge surfaces the
// ask drawer AND publishes the paused ask to the pendingBuilderAsk store. The
// chatbox send path reads that store: instead of starting a fresh edit turn, a
// typed message is routed to BuilderInputBridge via the
// `noclick:builder:input:submit-message` DOM event, which sends a
// `workflow:builder:input_response` carrying a free-form `message` payload.
//
// This drives the REAL BuilderInputBridge: it dispatches a synthetic
// `input:request` (the same event the live builder/canvas dispatches), asserts
// the store is populated, then dispatches `submit-message` and asserts the
// outgoing socket event is an input_response carrying the message (NOT a fresh
// builder:edit turn) and that the ask is cleared.
//
// Run: mcp__nc__nc_run_test({ file: "tests/nc/builder-ask-chat-reply.test.ts" })

import { nc } from '~/lib/nc';
import { getPendingBuilderAsk, setPendingBuilderAsk } from '~/lib/pendingBuilderAsk';
import { socketReceiver } from '~/lib/socket-receiver';

const ASK_ID = '__nc_ask_chat_reply__';
const CONV_ID = '__nc_conv_chat_reply__';

interface SentEvent { event: string; data: any }

export default async function () {
    const out: Record<string, unknown> = {};

    // ── Store: window-backed, set / get / clear ──────────────────────────
    setPendingBuilderAsk(null);
    nc.assert.falsy(getPendingBuilderAsk(), 'store starts clear');
    setPendingBuilderAsk({ workflowId: 'w', conversationId: 'c', askId: 'a' });
    nc.assert.equal(getPendingBuilderAsk()?.askId, 'a', 'store holds the published ask');
    setPendingBuilderAsk(null);
    nc.assert.falsy(getPendingBuilderAsk(), 'store clears to null');
    out.storeOk = true;

    // ── Integration: drive the real BuilderInputBridge ───────────────────
    // Spy the socket layer so we can inspect the input_response without a
    // live backend round-trip.
    const sent: SentEvent[] = [];
    const realSend = socketReceiver.sendEvent.bind(socketReceiver);
    (socketReceiver as any).sendEvent = (event: string, data: any, env?: any) => {
        sent.push({ event, data });
        // Swallow the resume (no backend in this test); forward everything else.
        if (event === 'workflow:builder:input_response') return true;
        return (realSend as (...args: unknown[]) => boolean)(event, data, env);
    };

    try {
        // A live, untagged ask (workflowId omitted → workflow-agnostic, so it
        // surfaces regardless of which editor is open).
        document.dispatchEvent(new CustomEvent('noclick:builder:input:request', {
            detail: {
                inputs: [{
                    id: 'cred_1',
                    nodeId: 'node_1',
                    type: 'text',
                    label: 'API key',
                    description: 'Paste your API key',
                    required: false,
                }],
                title: 'Setup Required',
                conversationId: CONV_ID,
                askId: ASK_ID,
            },
        }));

        // The bridge re-renders, then its publish effect populates the store.
        await nc.wait.until(() => getPendingBuilderAsk()?.askId === ASK_ID, 4000);
        const published = getPendingBuilderAsk();
        out.published = published;
        nc.assert.equal(published?.conversationId, CONV_ID,
            'paused ask is published to the store with its conversation id');

        // Simulate the chatbox send path: the user typed a message while the
        // ask was pending. NoClick.handleWorkflowEditSubmit dispatches this.
        const REPLY = "don't have a key yet, proceed without it";
        document.dispatchEvent(new CustomEvent('noclick:builder:input:submit-message', {
            detail: { message: REPLY },
        }));

        await nc.wait.until(
            () => sent.some(e => e.event === 'workflow:builder:input_response'),
            4000,
        );
        const resp = sent.find(e => e.event === 'workflow:builder:input_response');
        out.responsePayload = resp?.data;
        nc.assert.truthy(resp, 'a workflow:builder:input_response was sent');
        nc.assert.equal(resp!.data.message, REPLY, 'the typed message is sent verbatim');
        nc.assert.equal(resp!.data.conversation_id, CONV_ID, 'routed to the ask conversation');
        nc.assert.equal(resp!.data.ask_id, ASK_ID, 'carries the ask id');
        nc.assert.falsy(resp!.data.dismissed, 'a message reply is not a dismissal');
        // It must NOT have started a fresh edit turn.
        nc.assert.falsy(
            sent.some(e => e.event === 'workflow:builder:edit'),
            'a pending-ask reply must not start a fresh builder:edit turn',
        );

        // The ask is consumed — store clears so a later message would start a
        // fresh edit turn rather than re-answer.
        await nc.wait.until(() => getPendingBuilderAsk() == null, 4000);
        nc.assert.falsy(getPendingBuilderAsk(), 'store clears once the ask is answered');
    } finally {
        (socketReceiver as any).sendEvent = realSend;
        setPendingBuilderAsk(null);
        document.dispatchEvent(new CustomEvent('noclick:builder:input:clear'));
    }

    out.ok = true;
    return out;
}
