// A workflow that is ONE fully-configured agent must still get the Run popup.
//
// The bug this pins: the popup was mounted on `open && steps.length > 0`, a
// guard from when it only ever explained missing setup. Once the gate also took
// over the press to ask which entry points to run, a workflow with nothing
// wrong had no steps — so the gate suppressed the run and rendered nothing, and
// the Run button looked dead.
//
// Works on any canvas: every node but the agent is disabled for the duration,
// which is exactly how the gate and the entry-point list treat "not part of
// this run". Harness writes are local-only, so nothing persists.
import { nc } from '~/lib/nc';

function setDisabled(nodeId: string, disabled: boolean) {
    nc.nodes.update(nodeId, { disabled });
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

    const all = nc.nodes.summary();
    const agent = all.find((n) => n.type === 'agent');
    if (!agent) throw new Error('no agent on this canvas');
    const others = all.filter((n) => n.id !== agent.id).map((n) => n.id);

    for (const id of others) setDisabled(id, true);
    await nc.wait.ms(600);

    try {
        [...document.querySelectorAll('button')]
            .find((b) => b.textContent?.trim() === 'Run')
            ?.click();
        await nc.wait.ms(900);

        const d = document.querySelector<HTMLElement>(
            '[data-incomplete-run-dialog]'
        );
        // Whether the ZERO-step path was exercised. It is the sharpest form of
        // the regression — an agent with nothing to set up produced no steps,
        // and the popup used to need one to mount at all — but it depends on
        // the agent being fully configured, which is a property of whatever
        // canvas is open. Reported so a run that missed it says so.
        const steps = (d?.getAttribute('data-step-ids') ?? '')
            .split(',')
            .filter(Boolean);
        for (let i = 0; i < 12; i++) {
            const next = [
                ...document.querySelectorAll<HTMLButtonElement>(
                    '[data-incomplete-run-dialog] button'
                ),
            ].find((b) => b.textContent?.trim() === 'Next');
            if (!next) break;
            next.click();
            await nc.wait.ms(200);
        }
        const paths = [...document.querySelectorAll('[data-run-path]')].map(
            (r) => r.getAttribute('data-run-path')
        );
        const hasMessageBox = !!document.querySelector(
            `[data-run-path-message="${agent.id}"]`
        );
        const runButton = [
            ...document.querySelectorAll<HTMLButtonElement>(
                '[data-incomplete-run-dialog] button'
            ),
        ].find((b) => /^Run/.test(b.textContent?.trim() ?? ''));

        nc.assert.truthy(d, 'Run must open the popup, not silently do nothing');
        nc.assert.equal(
            d?.getAttribute('data-current-screen'),
            'paths',
            'the wizard must end on the entry-point screen'
        );
        nc.assert.deepEqual(paths, [agent.id], 'the agent is the entry point');
        nc.assert.truthy(
            hasMessageBox,
            'a lone agent gets a box for its opening message'
        );
        nc.assert.truthy(runButton, 'and a Run button to send it');
        nc.assert.falsy(
            runButton?.disabled,
            'which must not be disabled — the single path is selected'
        );

        return {
            disabledForTest: others,
            exercisedZeroSteps: steps.length === 0,
            steps,
            screen: d?.getAttribute('data-current-screen'),
            paths,
            hasMessageBox,
            runLabel: runButton?.textContent?.trim(),
        };
    } finally {
        document
            .querySelectorAll<HTMLElement>(
                '[data-incomplete-run-dialog] button[aria-label="Close"]'
            )
            .forEach((b) => b.click());
        for (const id of others) setDisabled(id, false);
    }
}
