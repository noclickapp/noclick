// Live check that the Run popup's entry-point selection actually shapes the
// run: unticking everything must block Run, and running a subset must send only
// those branches' nodes plus the agent's one-shot message override.
//
// Deliberately runs BOTH paths — a lone agent path takes the chat hand-off
// instead of a workflow run (see run-path-agent-handoff), so it would not
// exercise the scoping this test is about.
//
// The socket is stubbed for the duration so the assertion reads the real
// payload without starting a billed execution.
import { nc } from '~/lib/nc';
import { socketReceiver } from '~/lib/socket-receiver';

function rows() {
    return [...document.querySelectorAll<HTMLElement>('[data-run-path]')];
}

function buttonByText(text: string) {
    return [
        ...document.querySelectorAll<HTMLButtonElement>(
            '[data-incomplete-run-dialog] button'
        ),
    ].find((b) => b.textContent?.trim() === text);
}

/** Page to the wizard's last screen — the chooser lives there, and so does
 *  the Run button. */
async function goToLastScreen() {
    for (let i = 0; i < 12; i++) {
        const next = buttonByText('Next');
        if (!next) return;
        next.click();
        await nc.wait.ms(150);
    }
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
    await goToLastScreen();
    await nc.wait.forElement('[data-run-paths]');

    // Shape-dependent: a single entry point takes the chat hand-off, which is
    // run-path-agent-handoff's job, not this test's.
    if (rows().length < 2) {
        return {
            skipped: 'canvas has fewer than 2 entry points — nothing to scope',
            paths: rows().length,
        };
    }

    // Note the agent before unticking: its message box only renders while the
    // path is selected, so it is not findable from the empty state.
    const agentId = rows()
        .find((r) => r.querySelector('textarea'))
        ?.getAttribute('data-run-path');
    if (!agentId) throw new Error('no agent entry point on this canvas');

    // 1. Untick every entry point → Run must refuse.
    for (const row of rows()) {
        if (row.getAttribute('data-run-path-selected') === 'true')
            row.querySelector<HTMLElement>('[role="checkbox"]')!.click();
    }
    await nc.wait.ms(200);
    const emptyRun = buttonByText('Run') ?? buttonByText('Run anyway');
    const blockedWhenEmpty = !!emptyRun?.disabled;

    // 2. Tick everything back, give the agent a message, and run.
    const agentRow = () => {
        const row = rows().find(
            (r) => r.getAttribute('data-run-path') === agentId
        );
        if (!row)
            throw new Error(
                `agent row ${agentId} gone; rows=${rows()
                    .map((r) => r.getAttribute('data-run-path'))
                    .join(
                        ','
                    )} dialog=${!!document.querySelector('[data-incomplete-run-dialog]')}`
            );
        return row;
    };
    for (const row of rows()) {
        if (row.getAttribute('data-run-path-selected') !== 'true')
            row.querySelector<HTMLElement>('[role="checkbox"]')!.click();
        await nc.wait.ms(120);
    }
    await nc.wait.ms(200);

    const box = agentRow().querySelector<HTMLTextAreaElement>('textarea')!;
    nc.dom.type(box, 'run-path probe');
    await nc.wait.ms(150);

    const sock = socketReceiver.getSocket('API') as unknown as {
        emit: (...args: unknown[]) => unknown;
    } | null;
    const sent: Array<{ event: string; payload: unknown }> = [];
    const original = sock?.emit?.bind(sock);
    if (sock && original) {
        sock.emit = (...args: unknown[]) => {
            sent.push({ event: String(args[0]), payload: args[1] });
            return undefined;
        };
    }
    try {
        (buttonByText('Run') ?? buttonByText('Run anyway'))!.click();
        await nc.wait.ms(400);
    } finally {
        if (sock && original) sock.emit = original;
    }

    const exec = sent.find((s) => s.event === 'workflow:execute')?.payload as
        | {
              nodes?: Array<{ id: string }>;
              replay_nodes?: Array<{ id: string }>;
              config_overrides?: Record<string, Record<string, unknown>>;
          }
        | undefined;

    return {
        blockedWhenEmpty,
        agentId,
        emitted: sent.map((s) => s.event),
        executedNodes: exec?.nodes?.map((n) => n.id).sort(),
        replayNodes: exec?.replay_nodes?.map((n) => n.id).sort(),
        overrides: exec?.config_overrides,
    };
}
