// Changing an agent's model must not touch the chat, and the switch happens
// at SEND, into the SAME thread.
//
// Two bugs this pins. The retire used to fire on detection, so the transcript
// emptied on its own and a message dispatched near that moment landed in the
// conversation being left. Then (until 2026-09-13) the send minted a fresh
// conversation and carried the transcript as text, so every switch looked
// like a new chat and the thread never moved natively. The backend now moves
// the thread into the picked harness (session interchange); this client just
// sends the picked model on the thread it is looking at.
//
// The socket is stubbed, so this asserts the dispatch without billing a turn.
// The send is still REAL, so `finally` must undo its persistent side effects
// (wedged streaming flag) via nc.agentChat.restore — see
// agent-switch-shows-thread-immediately.test.ts for the incident.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

function convKey(): string | undefined {
    const n = ((window as any).__workflowTest?.getNodes() ?? []).find(
        (x: { type?: string }) => x.type === 'agent'
    );
    return n?.data?.config?.conversation_key as string | undefined;
}

export default async function () {
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(500);
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(300);

    const agent = nc.nodes.summary().find((n) => n.type === 'agent');
    if (!agent) throw new Error('no agent on this canvas');
    const saved = nc.agentChat.capture(agent.id);
    const original = saved.model as string;
    const touched: string[] = [nc.agentChat.conversationId(agent.id)];

    nc.ui.clickTab('Interface');
    await nc.wait.ms(1500);
    const keyBeforeSwitch = convKey();
    const swapped = original === 'opencode' ? 'openclaw' : 'opencode';

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const originalEmit = sock?.emit?.bind(sock);
    const sent: Array<{ event: string; payload: Record<string, unknown> }> = [];

    try {
        nc.nodes.update(agent.id, { config: { model: swapped } });
        await nc.wait.ms(1200);

        // The switch has NOT happened yet: nothing was sent, so the thread the
        // user is looking at is untouched.
        const keyAfterSwitch = convKey();

        if (sock && originalEmit) {
            sock.emit = (...args: unknown[]) => {
                sent.push({
                    event: String(args[0]),
                    payload: (args[1] ?? {}) as Record<string, unknown>,
                });
                return undefined;
            };
        }

        // The half that needs no send: changing the model must leave the
        // thread alone. This IS the reported bug — the transcript used to
        // empty itself the moment the pin was spotted.
        nc.assert.equal(
            keyAfterSwitch,
            keyBeforeSwitch,
            'changing the model must not touch the thread on its own'
        );

        const box = document.querySelector<HTMLTextAreaElement>(
            'textarea[placeholder^="Message"]'
        );
        if (!box) throw new Error('composer not mounted');
        nc.dom.type(box, 'switch-at-send probe');
        await nc.wait.ms(300);
        box.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
        );
        try {
            await nc.wait.until(
                () => sent.some((s) => s.event === 'workflow:execute'),
                8000
            );
        } catch {
            // The send is refused when the picked model is BYOK and this
            // canvas has no account for it. Say so rather than reporting a
            // pass on assertions that never ran.
            const warning = document
                .querySelector<HTMLElement>(
                    '[data-testid="agent-chat-credential-hint"]'
                )
                ?.innerText.trim();
            nc.dom.type(box, '');
            return {
                keyBeforeSwitch,
                keyAfterSwitch,
                threadUntouchedByModelChange: true,
                skipped: `send blocked: ${warning ?? 'unknown reason'}`,
            };
        }

        const exec = sent.find((s) => s.event === 'workflow:execute')!;
        const nodes = exec.payload.nodes as
            | Array<{ id: string; config?: Record<string, unknown> }>
            | undefined;
        const sentConfig = nodes?.find((n) => n.id === agent.id)?.config ?? {};
        const keyAfterSend = convKey();
        if (keyAfterSend)
            touched.push(nc.agentChat.conversationId(agent.id, keyAfterSend));

        nc.assert.equal(
            keyAfterSend,
            keyBeforeSwitch,
            'the send must continue the thread, not mint a new one'
        );
        nc.assert.equal(
            sentConfig.conversation_key,
            keyBeforeSwitch,
            'and must dispatch INTO that thread'
        );
        nc.assert.equal(
            sentConfig.model,
            swapped,
            'under the picked model'
        );
        nc.assert.truthy(
            !String(sentConfig.message ?? '').includes(
                'NOCLICK_CARRIED_CONTEXT'
            ),
            'the client carries nothing — the backend moves the thread'
        );

        return {
            original,
            swapped,
            keyBeforeSwitch,
            keyAfterSwitch,
            keyAfterSend,
            dispatchedKey: sentConfig.conversation_key,
            dispatchedModel: sentConfig.model,
        };
    } finally {
        if (sock && originalEmit) sock.emit = originalEmit;
        nc.agentChat.restore(saved, touched);
        await nc.wait.ms(600);
    }
}
