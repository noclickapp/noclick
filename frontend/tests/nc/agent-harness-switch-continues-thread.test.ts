// A harness switch continues the SAME conversation, and picking a thread from
// History never changes the model.
//
// Before 2026-09-13 this file guarded the opposite: one conversation must never
// take turns on two harnesses, so a switch minted a fresh thread on the next
// send and clicking a thread of another harness re-aligned the model picker
// to it — which is how a click in History silently switched the agent's model.
// The thread now follows the picker: the backend moves it into the picked
// harness at the next send (session interchange), so nothing is minted here
// and the picker is never touched by a click.
//
// Drives the real send path with the socket stubbed. Every CLI harness is
// BYOK and this canvas has no account for one, so the second send cannot be
// dispatched — the decision is observable through the credential pre-flight,
// which names the model the send WOULD run. The send is REAL, so `finally`
// must undo its persistent side effects via nc.agentChat.restore — see
// agent-switch-shows-thread-immediately.test.ts for the incident.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

function agentConfigOf(
    payload: Record<string, unknown>,
    agentId: string
): Record<string, unknown> {
    const nodes = payload.nodes as
        | Array<{ id: string; config?: Record<string, unknown> }>
        | undefined;
    return nodes?.find((n) => n.id === agentId)?.config ?? {};
}

type CanvasNode = { id: string; data?: { config?: Record<string, unknown> } };

function currentConfig(agentId: string): Record<string, unknown> {
    const canvas = (
        window as unknown as { __workflowTest?: { getNodes(): CanvasNode[] } }
    ).__workflowTest;
    const n = (canvas?.getNodes() ?? []).find((x) => x.id === agentId);
    return n?.data?.config ?? {};
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
    const touched: string[] = [nc.agentChat.conversationId(agent.id)];

    // Usage-based, so the first send is not refused for a missing credential;
    // the second is a different HARNESS.
    const first = 'openrouter/openai/gpt-5.6-luna';
    const second = 'opencode';

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const originalEmit = sock?.emit?.bind(sock);
    const sent: Array<Record<string, unknown>> = [];
    if (sock && originalEmit) {
        sock.emit = (...args: unknown[]) => {
            if (args[0] === 'workflow:execute')
                sent.push((args[1] ?? {}) as Record<string, unknown>);
            return undefined;
        };
    }

    const send = async (text: string) => {
        const box = document.querySelector<HTMLTextAreaElement>(
            'textarea[placeholder^="Message"]'
        );
        if (!box) throw new Error('composer not mounted');
        nc.dom.type(box, text);
        await nc.wait.ms(250);
        box.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
        );
    };

    try {
        nc.nodes.update(agent.id, { config: { model: first } });
        nc.ui.clickTab('Interface');
        await nc.wait.ms(1600);

        await send('harness-switch probe one');
        await nc.wait.until(() => sent.length >= 1, 12000);
        const one = agentConfigOf(sent[0], agent.id);
        const threadKey = String(one.conversation_key);
        touched.push(nc.agentChat.conversationId(agent.id, threadKey));

        // Switch harness. The pre-flight names the picked harness, because
        // that is what the send runs — on the same thread.
        nc.nodes.update(agent.id, { config: { model: second } });
        await nc.wait.ms(1500);
        const warning =
            document
                .querySelector<HTMLElement>(
                    '[data-testid="agent-chat-credential-hint"]'
                )
                ?.innerText.trim() ?? '';
        nc.assert.truthy(
            warning.includes(second),
            `the send must be aimed at the picked harness — saw: ${warning || '(no warning at all)'}`
        );
        nc.assert.equal(
            currentConfig(agent.id).conversation_key,
            threadKey,
            'switching the model must keep the thread'
        );

        // Pick the thread from History while a different harness is
        // selected: the thread loads, the model stays as picked.
        nc.dom.click('[data-testid="agent-chat-history-trigger"]');
        await nc.wait.forElement('[data-testid="agent-chat-history-panel"]');
        const row = document.querySelector<HTMLElement>(
            '[data-testid="agent-chat-history-row"]'
        );
        if (!row) throw new Error('no history row rendered for the thread');
        nc.assert.truthy(
            !row.querySelector('[data-testid="agent-chat-history-row-harness"]'),
            'rows carry no harness tag — which harness a thread last ran on is not something the user manages'
        );
        row.click();
        await nc.wait.ms(800);
        const after = currentConfig(agent.id);
        nc.assert.equal(
            after.model,
            second,
            'picking a thread of another harness must not change the model'
        );

        return {
            threadKey: threadKey.slice(-10),
            switchedTo: second,
            preflightNamesPickedHarness: warning.includes(second),
            modelAfterPick: after.model,
            keyAfterPick: String(after.conversation_key ?? '').slice(-10),
        };
    } finally {
        if (sock && originalEmit) sock.emit = originalEmit;
        nc.agentChat.restore(saved, touched);
        await nc.wait.ms(600);
    }
}
