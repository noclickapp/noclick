// A lone agent entry point is delivered through its CHAT, not as a raw
// workflow run.
//
// The bug this pins: running it as a workflow:execute put the user in front of
// a chat with no sign of the message they had just typed. The backend does not
// replay chat:message to its sender, so the user's bubble only exists if the
// chat's own submit echoed it locally — which a raw run never does.
//
// The socket is stubbed so nothing is billed; the assertion is that the bubble
// appears and that the send went out on the chat's path (start_node_id), not
// the popup's path-scoped one.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

function rows() {
    return [...document.querySelectorAll<HTMLElement>('[data-run-path]')];
}

function dialogButton(match: (text: string) => boolean) {
    return [
        ...document.querySelectorAll<HTMLButtonElement>(
            '[data-incomplete-run-dialog] button'
        ),
    ].find((b) => match(b.textContent?.trim() ?? ''));
}

export default async function () {
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(300);
    // A previous stubbed run can leave the toolbar on "Stop", which would
    // read as this test's press doing nothing.
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(300);
    document
        .querySelectorAll<HTMLElement>(
            '[data-incomplete-run-dialog] button[aria-label="Close"]'
        )
        .forEach((b) => b.click());
    await nc.wait.ms(200);

    [...document.querySelectorAll('button')]
        .find((b) => b.textContent?.trim() === 'Run')
        ?.click();
    await nc.wait.forElement('[data-incomplete-run-dialog]');
    await nc.wait.ms(250);
    for (let i = 0; i < 12; i++) {
        const next = dialogButton((t) => t === 'Next');
        if (!next) break;
        next.click();
        await nc.wait.ms(150);
    }
    await nc.wait.forElement('[data-run-paths]');

    const agentId = rows()
        .find((r) => r.querySelector('textarea'))
        ?.getAttribute('data-run-path');
    if (!agentId) throw new Error('no agent entry point on this canvas');

    // Leave ONLY the agent ticked — that is the shape that hands off.
    for (const row of rows()) {
        const isAgent = row.getAttribute('data-run-path') === agentId;
        const on = row.getAttribute('data-run-path-selected') === 'true';
        if (on !== isAgent)
            row.querySelector<HTMLElement>('[role="checkbox"]')!.click();
        await nc.wait.ms(150);
    }

    const message = `handoff probe ${Math.floor(performance.now())}`;
    const box = rows()
        .find((r) => r.getAttribute('data-run-path') === agentId)!
        .querySelector<HTMLTextAreaElement>('textarea')!;
    nc.dom.type(box, message);
    await nc.wait.ms(200);

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

    try {
        dialogButton((t) => /^Run/.test(t))!.click();
        // Tab switch → block mount → sub-tab activate → drain → send.
        await nc.wait.ms(1500);

        const exec = sent.find((s) => s.event === 'workflow:execute');
        const transcript = document.body.innerText;

        nc.assert.truthy(exec, 'the hand-off must still start a run');
        nc.assert.equal(
            exec?.payload.start_node_id,
            agentId,
            'the run must go out on the chat path, keyed to the agent'
        );
        nc.assert.truthy(
            transcript.includes(message),
            'the message the user typed must be visible in the chat'
        );

        return {
            agentId,
            message,
            emitted: sent.map((s) => s.event),
            startNodeId: exec?.payload.start_node_id,
            messageVisible: transcript.includes(message),
        };
    } finally {
        if (sock && original) sock.emit = original;
    }
}
