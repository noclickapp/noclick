// B3 verification: the always-on active_gen:terminal listener must re-surface
// the ask drawer from committed_messages when a run pauses, so a missed/raced
// transient `input_request` delta no longer leaves the run stuck until reload.
// Simulates an inbound terminal via the receiver's dispatch and asserts the
// drawer-open CustomEvent is (or isn't) dispatched. No backend/credits needed.
import { socketReceiver } from '~/lib/socket-receiver';
import { ensureActiveGenListener } from '~/lib/activeGenStore';

export default async function () {
    ensureActiveGenListener(); // idempotent — guarantees the terminal handler is installed

    const captured: Array<Record<string, unknown>> = [];
    const listener = (e: Event) => captured.push((e as CustomEvent).detail);
    document.addEventListener('noclick:builder:input:request', listener);

    const fire = (p: Record<string, unknown>) =>
        (socketReceiver as unknown as { handleEvent: (e: string, a: unknown[]) => void })
            .handleEvent('active_gen:terminal', [p]);
    const tick = () => new Promise((r) => setTimeout(r, 0));

    try {
        // 1. paused + pending_ask in committed_messages => drawer re-surfaced.
        fire({
            gen_id: 'gen-b3', outcome: 'paused', committed_conversation_id: 'conv-b3',
            committed_messages: [
                { role: 'user', message: 'build it' },
                { role: 'assistant', message: '', pending_ask: {
                    ask_id: 'ask-xyz', title: 'Input needed',
                    inputs: [{ id: 'ask_0', label: 'Retell From Number?' }],
                } },
            ],
        });
        await tick();
        const p = captured.find((d) => d.askId === 'ask-xyz');
        if (!p) throw new Error('paused terminal did not re-surface ask; captured=' + JSON.stringify(captured));
        if (p.generationId !== 'gen-b3') throw new Error('generationId not forwarded: ' + p.generationId);
        if (p.conversationId !== 'conv-b3') throw new Error('conversationId not forwarded: ' + p.conversationId);
        if (!Array.isArray(p.inputs) || p.inputs.length !== 1) throw new Error('inputs not forwarded');

        // 2. completed terminal must NOT re-surface an ask.
        captured.length = 0;
        fire({ gen_id: 'gen-done', outcome: 'complete', committed_conversation_id: 'c',
            committed_messages: [{ role: 'assistant', message: 'done' }] });
        await tick();
        if (captured.length) throw new Error('completed terminal must not re-surface an ask');

        // 3. paused but no pending_ask => no dispatch.
        fire({ gen_id: 'gen-np', outcome: 'paused', committed_conversation_id: 'c',
            committed_messages: [{ role: 'assistant', message: 'x' }] });
        await tick();
        if (captured.length) throw new Error('paused without pending_ask must not dispatch');

        return { ok: true, dispatchedAsk: p.askId };
    } finally {
        document.removeEventListener('noclick:builder:input:request', listener);
    }
}
