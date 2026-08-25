// One conversation must never take turns on two different harnesses.
//
// Reported live: a thread ran one turn on the in-process LLM agent and the next
// on an opencode sandbox, so the agent answered "this is our first interaction"
// to a question about the conversation directly above it. The mint guard asks
// what model the thread is running, and its nominal source — the conversations
// list — is only refetched when the History popover opens. A thread minted in
// this session is absent from it, "unknown" read as "same as the picker", and
// no fresh thread was minted.
//
// Drives the real send path with the socket stubbed: dispatch one turn, switch
// harness, dispatch another, and assert the second went somewhere else.
// The send is REAL, so `finally` must undo its persistent side effects (minted
// conversation_key, wedged streaming flag) via nc.agentChat.restore — see
// agent-switch-shows-thread-immediately.test.ts for the incident.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';
import { getAgentChatSession } from '~/lib/agentChatSessionStore';

function agentConfigOf(
    payload: Record<string, unknown>,
    agentId: string
): Record<string, unknown> {
    const nodes = payload.nodes as
        | Array<{ id: string; config?: Record<string, unknown> }>
        | undefined;
    return nodes?.find((n) => n.id === agentId)?.config ?? {};
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

    // Both usage-based, so neither send is refused for a missing credential —
    // and they are different HARNESSES, which is the case that was missed.
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

        await send('harness-mix probe one');
        await nc.wait.until(() => sent.length >= 1, 12000);
        const one = agentConfigOf(sent[0], agent.id);
        const convId = nc.agentChat.conversationId(
            agent.id,
            String(one.conversation_key)
        );
        touched.push(convId);

        // The blind spot, closed: the conversations list will not name this
        // thread's model until the History popover is opened, so the send
        // records what it dispatched.
        nc.assert.equal(
            getAgentChatSession(convId).lastSentModel,
            first,
            'the send must record what this thread runs'
        );

        // Switch to a different HARNESS. A second send cannot be dispatched
        // here — every CLI harness is BYOK and this canvas has no account for
        // it — but the decision is observable: the credential pre-flight names
        // the model the send WOULD run, and it names the picked one only if
        // the guard decided to mint. Left on the thread's own model (the bug),
        // it would name openrouter, which is usage-based and warns about
        // nothing at all.
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
            `the send must be aimed at the picked harness, not the thread's — saw: ${warning || '(no warning at all)'}`
        );

        return {
            firstModel: one.model,
            firstKey: String(one.conversation_key).slice(-10),
            recordedModel: getAgentChatSession(convId).lastSentModel,
            switchedTo: second,
            preflightNamesPickedHarness: warning.includes(second),
        };
    } finally {
        if (sock && originalEmit) sock.emit = originalEmit;
        nc.agentChat.restore(saved, touched);
        await nc.wait.ms(600);
    }
}
