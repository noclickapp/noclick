// The transcript must look continuous from the instant Send is pressed.
//
// Reported live: after changing the model, the chat showed a bare step timeline
// — no history and not even the message just typed — until the reply landed
// seconds later. The echo had gone to a thread the send was leaving. A switch
// no longer leaves the thread at all (the backend moves it into the picked
// harness — session interchange), so the transcript must stay continuous: the
// earlier turns still on screen, the new message beneath them, at once.
//
// The socket is stubbed, so this asserts what is on screen without billing a
// turn — and deliberately checks BEFORE any reply could arrive, which is the
// window the user was complaining about.
//
// Cleanup matters as much as the assertion here: the send is REAL and seeds a
// session whose streaming flag nothing will ever clear (the dispatch was
// swallowed). nc.agentChat.restore drops every touched session and puts the
// thread identity back — without it this test wedges the user's chat on a
// ghost thread (2026-07-27).
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

function transcriptText(): string {
    return (
        document.querySelector<HTMLElement>(
            '[data-testid="agent-chat-transcript"]'
        )?.innerText ?? ''
    );
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

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const originalEmit = sock?.emit?.bind(sock);
    const sent: Array<Record<string, unknown>> = [];

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
        nc.ui.clickTab('Interface');
        await nc.wait.ms(1600);
        const before = transcriptText();

        // A canvas probed repeatedly may hold a session wedged mid-turn, which
        // would refuse the send before anything is observable.
        const { agentChatSessionStore } = await import(
            '~/lib/agentChatSessionStore'
        );
        const live = agentChatSessionStore.sessions[touched[0]];
        if (live) live.isStreaming = false;

        if (sock && originalEmit) {
            sock.emit = (...args: unknown[]) => {
                if (args[0] === 'workflow:execute')
                    sent.push((args[1] ?? {}) as Record<string, unknown>);
                return undefined;
            };
        }

        // Change harness, then send — the sequence that blanked the transcript.
        const swapped =
            saved.model === 'opencode'
                ? 'openrouter/openai/gpt-5.6-luna'
                : 'opencode';
        nc.nodes.update(agent.id, { config: { model: swapped } });
        await nc.wait.ms(1400);
        await send('continuity probe');
        await nc.wait.until(() => sent.length >= 1, 15000);
        // Nothing has replied — this is exactly the window that was blank.
        await nc.wait.ms(600);
        const during = transcriptText();

        const nodes = sent[0]?.nodes as
            | Array<{ id: string; config?: Record<string, unknown> }>
            | undefined;
        const dispatchedKey = nodes?.find((n) => n.id === agent.id)?.config
            ?.conversation_key as string | undefined;
        if (dispatchedKey)
            touched.push(nc.agentChat.conversationId(agent.id, dispatchedKey));

        nc.assert.truthy(
            !dispatchedKey || touched[0].endsWith(dispatchedKey),
            'the switch must continue the thread on screen, not mint one'
        );
        nc.assert.truthy(
            during.includes('continuity probe'),
            `the message just sent must be on screen — saw: ${during.slice(0, 160)}`
        );
        const earlier = before.trim().slice(0, 60);
        nc.assert.truthy(
            !earlier || during.includes(earlier),
            'the earlier turns must still be on screen beneath the switch'
        );

        return {
            swappedTo: swapped,
            dispatchedKey: dispatchedKey?.slice(-10),
            hadHistoryBefore: before.trim().length > 0,
            ownMessageVisible: during.includes('continuity probe'),
            earlierTurnsStillVisible: before.trim()
                ? during.includes(before.trim().slice(0, 60))
                : null,
        };
    } finally {
        if (sock && originalEmit) sock.emit = originalEmit;
        nc.agentChat.restore(saved, touched);
        await nc.wait.ms(600);
    }
}
