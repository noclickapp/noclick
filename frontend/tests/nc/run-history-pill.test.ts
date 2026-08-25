// Verifies the run-history UI after the "open the results popup, switch runs
// inside it" redesign:
//   • RunHistoryPill — always-on top-left button; shows the latest run's status +
//     relative time, and fires onOpen when clicked.
//   • RunSwitcher — the Story results replacement for the removed RunPicker;
//     lists loaded runs, selects an older run, and explicitly pages more.
// Both components are mounted standalone with mock data (the canvas needs auth
// the bridge tab lacks). Queries are scoped to each mount container so a real
// app pill can't collide.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { nc } from '~/lib/nc';
import { RunHistoryPill } from '~/components/workflow/canvas/RunHistoryPill';
import {
    RunSwitcher,
    type RunSwitcherData,
    type SwitcherRun,
} from '~/components/design/run-results/variants';
import {
    formatDuration,
    type WorkflowExecutionLog,
} from '~/components/workflow/WorkflowExecutionLogs';

const MIN = 60 * 1000,
    HOUR = 60 * MIN,
    DAY = 24 * HOUR;

function mount(el: React.ReactElement) {
    const container = document.createElement('div');
    container.style.cssText = 'position:fixed;inset:0;z-index:99999;';
    container.setAttribute('data-test-host', '1');
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(el);
    return {
        container,
        cleanup: () => {
            root.unmount();
            container.remove();
        },
    };
}

const findIn = (root: ParentNode, sel: string, needle: string) =>
    Array.from(root.querySelectorAll(sel)).find((e) =>
        (e.textContent || '').includes(needle)
    ) as HTMLElement | undefined;

function logs(now: number): WorkflowExecutionLog[] {
    return [
        {
            id: 'exec-1',
            timestamp: new Date(now - 2 * MIN),
            status: 'success',
            message: 'ok',
            duration: 1200,
            trigger: 'manual',
        },
        {
            id: 'exec-2',
            timestamp: new Date(now - 1 * HOUR),
            status: 'success',
            message: 'ok',
            duration: 3400,
            trigger: 'webhook',
        },
        {
            id: 'exec-3',
            timestamp: new Date(now - 3 * HOUR),
            status: 'error',
            message: 'boom',
            duration: 800,
            trigger: 'manual',
        },
        {
            id: 'exec-4',
            timestamp: new Date(now - 1 * DAY),
            status: 'success',
            message: 'ok',
            duration: 2100,
            trigger: 'cron',
        },
    ];
}

// Enough runs (20) to exercise a full loaded page before explicit pagination.
function manyLogs(now: number): WorkflowExecutionLog[] {
    const filler: WorkflowExecutionLog[] = Array.from(
        { length: 16 },
        (_, i) => ({
            id: `fill-${i}`,
            timestamp: new Date(now - (i + 2) * DAY),
            status: 'success',
            message: 'ok',
            duration: 1500,
            trigger: 'manual',
        })
    );
    return [...logs(now), ...filler];
}

function toSwitcherRuns(items: WorkflowExecutionLog[]): SwitcherRun[] {
    return items.map((log) => ({
        id: log.id,
        iso: log.timestamp.toISOString(),
        failed: log.status === 'error',
        durationLabel:
            log.duration === undefined
                ? undefined
                : formatDuration(log.duration),
        triggerSlug: log.trigger,
        nodes: log.nodesExecuted,
        error: log.status === 'error' ? log.message : undefined,
    }));
}

export default async function () {
    const now = Date.now();
    const opened: number[] = [];
    const selected: string[] = [];
    const loadedMore: number[] = [];

    // ── A. RunHistoryPill: always-on, summarises latest run, fires onOpen ──
    const pillMount = mount(
        React.createElement(
            RunHistoryPill as never,
            {
                logs: logs(now),
                onOpen: () => opened.push(1),
            } as never
        )
    );
    let pill: HTMLElement | undefined;
    await nc.wait.until(
        () => !!(pill = findIn(pillMount.container, 'button', 'Runs')),
        4000
    );
    const pillText = pill!.textContent || '';
    nc.assert.truthy(pillText.includes('Runs'), 'Pill labelled "Runs"');
    nc.assert.truthy(
        /2m ago/.test(pillText),
        `Pill shows latest run time, got "${pillText}"`
    );
    pill!.click();
    await nc.wait.until(() => opened.length > 0, 2000);
    nc.assert.equal(opened.length, 1, 'Clicking the pill fires onOpen');
    pillMount.cleanup();

    // Empty: pill still renders (always-on).
    const emptyPill = mount(
        React.createElement(
            RunHistoryPill as never,
            { logs: [], onOpen: () => {} } as never
        )
    );
    let ep: HTMLElement | undefined;
    await nc.wait.until(
        () => !!(ep = findIn(emptyPill.container, 'button', 'Runs')),
        4000
    );
    nc.assert.truthy(ep, 'Pill renders with zero runs (always-on)');
    emptyPill.cleanup();
    await nc.wait.ms(30);

    // ── B. RunSwitcher: current run + dropdown + explicit pagination ─────
    const switcherData: RunSwitcherData = {
        runs: toSwitcherRuns(manyLogs(now)),
        currentId: 'exec-1',
        latestId: 'exec-1',
        hasMore: true,
        loadingMore: false,
        onLoadMore: () => loadedMore.push(1),
        onSelect: (id) => selected.push(id),
    };
    const picker = mount(
        React.createElement(
            RunSwitcher as never,
            {
                data: switcherData,
                icons: {},
            } as never
        )
    );
    let switcher: HTMLElement | undefined;
    await nc.wait.until(
        () => !!(switcher = findIn(picker.container, 'button', 'Latest run')),
        4000
    );
    nc.assert.truthy(switcher, 'Switcher identifies the current run as latest');

    // Open the dropdown and scope queries to its panel.
    switcher!.click();
    let panelTitle: HTMLElement | undefined;
    await nc.wait.until(
        () => !!(panelTitle = findIn(picker.container, 'p', 'Runs')),
        3000
    );
    const panel = panelTitle!.parentElement as HTMLElement;
    const rows = Array.from(
        panel.querySelectorAll('[data-testid="run-trigger-mark"]')
    )
        .map((mark) => mark.closest('button'))
        .filter((row): row is HTMLButtonElement => row !== null);
    nc.assert.equal(
        rows.length,
        20,
        'Dropdown lists all loaded runs (no recent-only cap)'
    );
    const dur = Array.from(panel.querySelectorAll('span'))
        .map((e) => e.textContent || '')
        .join(' ');
    nc.assert.truthy(
        dur.includes('3.4s') && dur.includes('800ms'),
        `Durations render in the dropdown, got "${dur}"`
    );

    // Explicitly request an older page.
    const loadOlder = findIn(panel, 'button', 'Load older runs');
    nc.assert.truthy(
        loadOlder,
        'Older-page action renders when hasMore is true'
    );
    loadOlder!.click();
    await nc.wait.until(() => loadedMore.length > 0, 4000);
    nc.assert.equal(loadedMore.length, 1, 'Load older runs fires onLoadMore');

    // Pick the failed older run → onSelect fires with its id and closes.
    const older = findIn(panel, 'button', 'boom')!;
    older.click();
    await nc.wait.until(() => selected.length > 0, 3000);
    nc.assert.includes(
        selected,
        'exec-3',
        'Picking an older run fires onSelect with its id'
    );
    await nc.wait.until(() => !findIn(picker.container, 'p', 'Runs'), 2000);
    nc.assert.falsy(
        findIn(picker.container, 'p', 'Runs'),
        'Dropdown closes after selecting a run'
    );
    picker.cleanup();

    // ── C. RunSwitcher loading-more state replaces the paging action ─────
    const loadingPicker = mount(
        React.createElement(
            RunSwitcher as never,
            {
                data: { ...switcherData, loadingMore: true },
                icons: {},
            } as never
        )
    );
    let loadingButton: HTMLElement | undefined;
    await nc.wait.until(
        () =>
            !!(loadingButton = findIn(
                loadingPicker.container,
                'button',
                'Latest run'
            )),
        3000
    );
    loadingButton!.click();
    await nc.wait.until(
        () => !!loadingPicker.container.querySelector('.animate-spin'),
        3000
    );
    nc.assert.truthy(
        loadingPicker.container.querySelector('.animate-spin'),
        'Switcher shows a spinner while paging'
    );
    nc.assert.falsy(
        findIn(loadingPicker.container, 'button', 'Load older runs'),
        'Paging action hides while loading'
    );
    loadingPicker.cleanup();

    return {
        pillText,
        opened: opened.length,
        selected,
        loadedMore: loadedMore.length,
        rows: rows.length,
    };
}
