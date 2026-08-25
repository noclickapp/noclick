// A message handed over from the Run popup must actually go out.
//
// Reported: it arrived in the composer unsent, with nothing on screen saying
// why. The drain used to consume the queue and then seed the composer whenever
// the credential gate tripped — but that gate is transient (a pending retire
// makes the send model the pinned one for a render, which is BYOK), so by the
// time the user looked the gate had cleared and their message was just sitting
// there. Every blocker now LEAVES IT QUEUED, and the drain re-runs when the
// blocker lifts.
//
// The socket is stubbed, so this asserts the dispatch without billing a turn.
// The send is still REAL, so `finally` must undo its persistent side effects
// (seeded echo, wedged streaming flag) via nc.agentChat.restore — and drop any
// undrained queue entry, which would otherwise fire a REAL send whenever its
// blocker lifts (see agent-switch-shows-thread-immediately.test.ts).
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';
import {
    queueAgentChatSend,
    takeQueuedAgentChatSend,
} from '~/lib/pendingAgentSendStore';

export default async function () {
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(500);
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(300);

    const agent = nc.nodes.summary().find((n) => n.type === 'agent');
    if (!agent) throw new Error('no agent on this canvas');
    const saved = nc.agentChat.capture(agent.id);
    const touched = [nc.agentChat.conversationId(agent.id)];

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const original = sock?.emit?.bind(sock);
    const sent: Array<{ event: string; payload: Record<string, unknown> }> = [];
    if (sock && original) {
        sock.emit = (...args: unknown[]) => {
            sent.push({
                event: String(args[0]),
                payload: (args[1] ?? {}) as Record<string, unknown>,
            });
            return undefined;
        };
    }

    const message = `queued-drain probe ${Math.floor(performance.now())}`;
    try {
        queueAgentChatSend(nc.nodes.workflowId(), agent.id, message);
        nc.ui.clickTab('Interface');
        await nc.wait.until(
            () => sent.some((s) => s.event === 'workflow:execute'),
            15000
        );

        const exec = sent.find((s) => s.event === 'workflow:execute')!;
        const overrides = exec.payload.config_overrides as
            | Record<string, Record<string, unknown>>
            | undefined;
        const nodes = exec.payload.nodes as
            | Array<{ id: string; config?: Record<string, unknown> }>
            | undefined;
        const carried =
            (overrides?.[agent.id]?.message as string | undefined) ??
            (nodes?.find((n) => n.id === agent.id)?.config?.message as
                | string
                | undefined);

        const draft =
            document.querySelector<HTMLTextAreaElement>(
                'textarea[placeholder^="Message"]'
            )?.value ?? '';

        nc.assert.truthy(
            carried?.includes(message),
            'the queued message must reach the backend, not the composer'
        );
        nc.assert.equal(draft, '', 'and must not be left sitting in the box');

        return {
            agentId: agent.id,
            startNodeId: exec.payload.start_node_id,
            messageReachedBackend: !!carried?.includes(message),
            draftAfter: draft,
        };
    } finally {
        if (sock && original) sock.emit = original;
        takeQueuedAgentChatSend(nc.nodes.workflowId(), agent.id);
        nc.agentChat.restore(saved, touched);
        await nc.wait.ms(600);
    }
}
