// The popup must be the same width from every entry point when it shows the
// same thing.
//
// The bug this pins: the widening rule keyed off the tool-provider allowlist
// only, so a step whose requirement was the node's OWN action — the same
// searchable operation list, rendered by the same picker — got the narrow
// dialog. "Run from here" hits that case constantly, and next to the main Run
// button's popup it read as a different component.
//
// A probe node with no operation is the shortest path to that requirement.
import { nc } from '~/lib/nc';

const PROBE = 'nc_width_probe';
const DIALOG = '[data-incomplete-run-dialog]';

async function closeAnyDialog() {
    document
        .querySelectorAll<HTMLElement>(`${DIALOG} button[aria-label="Close"]`)
        .forEach((b) => b.click());
    await nc.wait.ms(250);
}

function dialogWidth() {
    const d = document.querySelector<HTMLElement>(DIALOG);
    if (!d) return null;
    // Radix opens with zoom-in-95, and a backgrounded tab pauses animations —
    // measuring mid-open reads 95% of the real width and the two entry points
    // disagree for reasons that have nothing to do with the size class.
    d.getAnimations().forEach((a) => a.finish());
    return Math.round(d.getBoundingClientRect().width);
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

    // A node with no action chosen: its only requirement is the action picker.
    if (!nc.node(PROBE)) {
        nc.nodes.add(PROBE, 'automation-google-drive', {}, { x: 700, y: 700 });
        await nc.wait.until(() => !!nc.node(PROBE), 8000);
    }
    nc.nodes.update(PROBE, { operation: undefined, config: {} });
    await nc.wait.ms(400);

    try {
        // 1. Run from here, on the probe itself.
        document.dispatchEvent(
            new CustomEvent('noclick:run-from-node', {
                detail: { nodeId: PROBE },
            })
        );
        await nc.wait.forElement(DIALOG, 10000);
        await nc.wait.ms(400);
        const fromNode = {
            width: dialogWidth(),
            steps: document
                .querySelector(DIALOG)
                ?.getAttribute('data-step-ids'),
            hasPicker: !!document.querySelector(
                `[data-step-operation="${PROBE}"]`
            ),
        };
        await closeAnyDialog();

        // 2. The main Run button, same probe in the step set.
        [...document.querySelectorAll('button')]
            .find((b) => b.textContent?.trim() === 'Run')
            ?.click();
        await nc.wait.forElement(DIALOG, 10000);
        await nc.wait.ms(400);
        const fromRunButton = {
            width: dialogWidth(),
            steps: document
                .querySelector(DIALOG)
                ?.getAttribute('data-step-ids'),
        };

        nc.assert.truthy(
            fromNode.hasPicker,
            'the probe must present the action picker'
        );
        nc.assert.equal(
            fromNode.width,
            fromRunButton.width,
            'both entry points must size the popup the same'
        );
        nc.assert.truthy(
            (fromNode.width ?? 0) > 500,
            'a popup showing an operation list must get the wide layout'
        );

        return { fromNode, fromRunButton };
    } finally {
        await closeAnyDialog();
        nc.nodes.delete(PROBE);
    }
}
