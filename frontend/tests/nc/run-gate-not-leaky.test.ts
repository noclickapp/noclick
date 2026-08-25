// The gate must catch EVERY press, not every press after the first.
//
// "Run anyway" sets a one-shot bypass so the run it re-invokes is not caught by
// the gate again. For run-from-here and single-node runs that flag is consumed,
// because those entry points re-enter the gate. A whole-workflow run does not —
// it calls runWorkflow directly — so the flag survived the press and silently
// disarmed the gate for the NEXT one.
//
// The socket is stubbed so this never starts a real run. One consequence: on a
// canvas whose only entry point is an agent, the stubbed send never gets a
// reply, so that chat stays "streaming" and the NEXT hand-off queues behind it.
// Re-running this back-to-back against such a canvas can therefore time out
// waiting for the run — reload the page (or wait out the turn) between runs.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

/** Generous: the tab is usually backgrounded, which clamps chained timers. */
const SLOW_MS = 15000;

function dialog() {
    return document.querySelector<HTMLElement>('[data-incomplete-run-dialog]');
}

function dialogButton(match: (text: string) => boolean) {
    return [
        ...document.querySelectorAll<HTMLButtonElement>(
            '[data-incomplete-run-dialog] button'
        ),
    ].find((b) => match(b.textContent?.trim() ?? ''));
}

function pressRun() {
    [...document.querySelectorAll('button')]
        .find((b) => b.textContent?.trim() === 'Run')
        ?.click();
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

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const original = sock?.emit?.bind(sock);
    let runs = 0;
    if (sock && original) {
        sock.emit = (...args: unknown[]) => {
            if (args[0] === 'workflow:execute') runs++;
            return undefined;
        };
    }

    try {
        // First press → popup, then run through it.
        pressRun();
        await nc.wait.forElement('[data-incomplete-run-dialog]');
        await nc.wait.ms(250);
        const firstPressOpened = !!dialog();
        for (let i = 0; i < 12; i++) {
            const next = dialogButton((t) => t === 'Next');
            if (!next) break;
            next.click();
            await nc.wait.ms(150);
        }
        dialogButton((t) => /^Run/.test(t))!.click();
        // Poll rather than sleep. A workflow run goes out on the click, but a
        // lone agent's rides a tab switch, block mount and drain — and this
        // suite runs against a background tab, where Chrome clamps the chained
        // timers that cascade through. A fixed wait tuned for a focused tab
        // fails there for reasons that have nothing to do with the gate.
        await nc.wait.until(() => runs > 0, SLOW_MS);
        const runsAfterFirst = runs;

        // The stub swallows workflow:execute, so no workflow:started ever
        // comes back and the button stays on "Stop" for a minute. Settle the
        // optimistic run by hand — otherwise there is no Run button to press
        // and "no popup" would be an artefact of the test, not the bug.
        const workflowId = nc.nodes.workflowId();
        nc.emit('workflow:started', {
            workflow_id: workflowId,
            execution_id: 'gate-probe',
        });
        nc.emit('workflow:complete', {
            workflow_id: workflowId,
            execution_id: 'gate-probe',
            success: true,
        });
        // The run may have handed off to the Interface tab, so come back to
        // the canvas before pressing again.
        nc.ui.clickTab('Workflow');
        await nc.wait.ms(600);
        document
            .querySelectorAll<HTMLElement>(
                '[data-run-results-dialog] button[aria-label="Close"]'
            )
            .forEach((b) => b.click());
        await nc.wait.ms(200);
        const runButtonPresent = !![
            ...document.querySelectorAll('button'),
        ].find((b) => b.textContent?.trim() === 'Run');

        // Second press → the popup must come back.
        pressRun();
        await nc.wait.ms(600);
        const secondPressOpened = !!dialog();
        const runsAfterSecond = runs;

        nc.assert.truthy(firstPressOpened, 'first press must open the popup');
        nc.assert.equal(
            runsAfterFirst,
            1,
            'the popup Run must start exactly one run, by either delivery'
        );
        nc.assert.truthy(
            runButtonPresent,
            'Run must be back before the second press'
        );
        nc.assert.truthy(
            secondPressOpened,
            'second press must open the popup too — the bypass leaked'
        );
        nc.assert.equal(
            runsAfterSecond,
            runsAfterFirst,
            'a gated second press must not start a run of its own'
        );

        return {
            firstPressOpened,
            runsAfterFirst,
            runButtonPresent,
            secondPressOpened,
            runsAfterSecond,
        };
    } finally {
        if (sock && original) sock.emit = original;
    }
}
