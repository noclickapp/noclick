// Live check for the Run popup's entry-point chooser: it is the wizard's LAST
// screen, reached by paging past the setup steps, and an agent path there
// carries an editable opening message prefilled from its node.
import { nc } from '~/lib/nc';

function buttonByText(text: string) {
    return [
        ...document.querySelectorAll<HTMLButtonElement>(
            '[data-incomplete-run-dialog] button'
        ),
    ].find((b) => b.textContent?.trim() === text);
}

export default async function () {
    // The single-agent hand-off leaves the app on the Interface tab, so a
    // re-run of this test would find no canvas Run button. The canvas tab is
    // labelled "Workflow" — nc.ui.goToCanvas() looks for "Canvas" and misses.
    nc.ui.clickTab('Workflow');
    await nc.wait.ms(300);
    // A previous stubbed run can leave the toolbar on "Stop", which would
    // read as this test's press doing nothing.
    nc.run.settlePending();
    nc.run.closePopups();
    await nc.wait.ms(300);
    // Close anything already open so the press below is the one under test.
    document
        .querySelectorAll<HTMLElement>(
            '[data-incomplete-run-dialog] button[aria-label="Close"]'
        )
        .forEach((b) => b.click());
    await nc.wait.ms(200);

    const runButton = [...document.querySelectorAll('button')].find(
        (b) => b.textContent?.trim() === 'Run'
    ) as HTMLButtonElement | undefined;
    if (!runButton) throw new Error('no Run button on the canvas');
    runButton.click();

    await nc.wait.forElement('[data-incomplete-run-dialog]');
    await nc.wait.ms(300);

    // The chooser must NOT be visible while the wizard is on a setup step.
    const dialog = () =>
        document.querySelector<HTMLElement>('[data-incomplete-run-dialog]')!;
    const firstScreen = dialog().getAttribute('data-current-screen');
    const chooserOnFirstScreen = !!document.querySelector('[data-run-paths]');

    for (let i = 0; i < 12; i++) {
        const next = buttonByText('Next');
        if (!next) break;
        next.click();
        await nc.wait.ms(150);
    }

    const chooser = document.querySelector('[data-run-paths]');
    // Shape-dependent: with one entry point there is nothing to choose between,
    // and the chooser renders as a bare message box instead (see
    // run-gate-single-agent). Say so rather than passing on a canvas that never
    // exercised the assertions.
    if (document.querySelectorAll('[data-run-path]').length < 2) {
        return {
            skipped: 'canvas has fewer than 2 entry points — nothing to choose',
            paths: document.querySelectorAll('[data-run-path]').length,
        };
    }
    const rows = [...document.querySelectorAll('[data-run-path]')].map(
        (el) => ({
            nodeId: el.getAttribute('data-run-path'),
            selected: el.getAttribute('data-run-path-selected'),
            hasCheckbox: !!el.querySelector('[role="checkbox"]'),
            message:
                (el.querySelector('textarea') as HTMLTextAreaElement | null)
                    ?.value ?? null,
        })
    );

    // Only the navigation row — the step body holds a whole operation picker,
    // and dumping every button in the dialog buries the result.
    const nav = [
        ...document.querySelectorAll<HTMLButtonElement>(
            '[data-incomplete-run-dialog] button'
        ),
    ]
        .filter((b) =>
            ['Back', 'Next', 'Run', 'Run anyway'].includes(
                b.textContent?.trim() ?? ''
            )
        )
        .map((b) => ({ text: b.textContent?.trim(), disabled: b.disabled }));

    return {
        firstScreen,
        chooserOnFirstScreen,
        lastScreen: dialog().getAttribute('data-current-screen'),
        chooserShown: !!chooser,
        title: dialog().querySelector('h2')?.textContent?.trim(),
        segments: document.querySelectorAll(
            '[data-incomplete-run-dialog] [aria-label^="Go to"]'
        ).length,
        rows,
        nav,
    };
}
