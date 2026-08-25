// "Run from here" on an agent must still ask for its opening message.
//
// The bug this pins: entry points were only derived for a whole-workflow run,
// on the reasoning that starting from a specific node already answers "where
// does this begin". True for the CHOICE — but the message is a separate
// question, and a node-scoped run silently used the node's saved one with no
// chance to change it.
//
// The message rides config_overrides on the very run the gate intercepted; it
// does NOT hand off to the chat, because the user stayed on the canvas.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

const DIALOG = '[data-incomplete-run-dialog]';

async function closeAnyDialog() {
    document
        .querySelectorAll<HTMLElement>(`${DIALOG} button[aria-label="Close"]`)
        .forEach((b) => b.click());
    await nc.wait.ms(250);
}

export default async function () {
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(300);
    // A previous stubbed run can leave the toolbar on "Stop", which would
    // read as this test's press doing nothing.
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(300);
    await closeAnyDialog();

    const agent = nc.nodes.summary().find((n) => n.type === 'agent');
    if (!agent) throw new Error('no agent on this canvas');

    document.dispatchEvent(
        new CustomEvent('noclick:run-from-node', {
            detail: { nodeId: agent.id },
        })
    );
    await nc.wait.forElement(DIALOG, 10000);
    await nc.wait.ms(400);

    // Page to the end: the agent may have setup steps of its own.
    for (let i = 0; i < 12; i++) {
        const next = [
            ...document.querySelectorAll<HTMLButtonElement>(`${DIALOG} button`),
        ].find((b) => b.textContent?.trim() === 'Next');
        if (!next) break;
        next.click();
        await nc.wait.ms(200);
    }

    const box = document.querySelector<HTMLTextAreaElement>(
        `[data-run-path-message="${agent.id}"]`
    );
    nc.assert.truthy(
        box,
        'run-from-here on an agent must offer its opening message'
    );
    const note =
        document.querySelector<HTMLElement>('[data-run-paths]')?.innerText ??
        '';
    nc.assert.falsy(
        note.includes('Answers in the chat'),
        'a node-scoped run stays on the canvas, so it must not promise a chat'
    );

    const message = `from-node probe ${Math.floor(performance.now())}`;
    nc.dom.type(box!, message);
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
        [...document.querySelectorAll<HTMLButtonElement>(`${DIALOG} button`)]
            .find((b) => /^Run/.test(b.textContent?.trim() ?? ''))!
            .click();
        await nc.wait.until(
            () => sent.some((s) => s.event === 'workflow:execute'),
            15000
        );

        const exec = sent.find((s) => s.event === 'workflow:execute')!;
        const overrides = exec.payload.config_overrides as
            | Record<string, Record<string, unknown>>
            | undefined;
        nc.assert.equal(
            overrides?.[agent.id]?.message,
            message,
            'the typed message must ride the run as a one-shot override'
        );
        nc.assert.equal(
            exec.payload.start_node_id,
            agent.id,
            'and it must still be the run-from-here run, not a chat send'
        );
        return {
            agentId: agent.id,
            message,
            startNodeId: exec.payload.start_node_id,
            overrides,
        };
    } finally {
        if (sock && original) sock.emit = original;
        await closeAnyDialog();
    }
}
