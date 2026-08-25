// Verifies the run-history UI after the "open the results popup, switch runs
// inside it" redesign:
//   • RunHistoryPill — always-on top-left button; shows the latest run's status +
//     relative time, and fires onOpen when clicked.
//   • RunPicker — the in-popup run switcher; shows the current run, and its inline
//     (non-portaled) dropdown lists older runs, fires onSelectRun on pick and
//     onViewAll on "View all".
// Both components are mounted standalone with mock data (the canvas needs auth the
// bridge tab lacks), exercising the real components. RunPicker's dropdown is inline
// (not portaled), so unlike a Radix popover its clicks land under the test's root
// and the callbacks ARE exercised here. Queries are scoped to each mount container
// so a real app pill can't collide.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { nc } from '~/lib/nc';
import { RunHistoryPill } from '~/components/workflow/canvas/RunHistoryPill';
import { RunPicker } from '~/components/workflow/RunPicker';
import type { WorkflowExecutionLog } from '~/components/workflow/WorkflowExecutionLogs';

const MIN = 60 * 1000, HOUR = 60 * MIN, DAY = 24 * HOUR;

function mount(el: React.ReactElement) {
    const container = document.createElement('div');
    container.style.cssText = 'position:fixed;inset:0;z-index:99999;';
    container.setAttribute('data-test-host', '1');
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(el);
    return { container, cleanup: () => { root.unmount(); container.remove(); } };
}

const findIn = (root: ParentNode, sel: string, needle: string) =>
    Array.from(root.querySelectorAll(sel)).find((e) => (e.textContent || '').includes(needle)) as HTMLElement | undefined;

function logs(now: number): WorkflowExecutionLog[] {
    return [
        { id: 'exec-1', timestamp: new Date(now - 2 * MIN), status: 'success', message: 'ok', duration: 1200, trigger: 'manual' },
        { id: 'exec-2', timestamp: new Date(now - 1 * HOUR), status: 'success', message: 'ok', duration: 3400, trigger: 'webhook' },
        { id: 'exec-3', timestamp: new Date(now - 3 * HOUR), status: 'error', message: 'boom', duration: 800, trigger: 'manual' },
        { id: 'exec-4', timestamp: new Date(now - 1 * DAY), status: 'success', message: 'ok', duration: 2100, trigger: 'cron' },
    ];
}

// Enough runs (20) to make the dropdown scroll, so the infinite-scroll sentinel
// sits below the fold and only fires onLoadMore once scrolled near.
function manyLogs(now: number): WorkflowExecutionLog[] {
    const filler: WorkflowExecutionLog[] = Array.from({ length: 16 }, (_, i) => ({
        id: `fill-${i}`, timestamp: new Date(now - (i + 2) * DAY), status: 'success', message: 'ok', duration: 1500, trigger: 'manual',
    }));
    return [...logs(now), ...filler];
}

export default async function () {
    const now = Date.now();
    const opened: number[] = [];
    const selected: string[] = [];
    const loadedMore: number[] = [];

    // ── A. RunHistoryPill: always-on, summarises latest run, fires onOpen ──
    const pillMount = mount(React.createElement(RunHistoryPill as never, {
        logs: logs(now), onOpen: () => opened.push(1),
    } as never));
    let pill: HTMLElement | undefined;
    await nc.wait.until(() => !!(pill = findIn(pillMount.container, 'button', 'Runs')), 4000);
    const pillText = pill!.textContent || '';
    nc.assert.truthy(pillText.includes('Runs'), 'Pill labelled "Runs"');
    nc.assert.truthy(/2m ago/.test(pillText), `Pill shows latest run time, got "${pillText}"`);
    pill!.click();
    await nc.wait.until(() => opened.length > 0, 2000);
    nc.assert.equal(opened.length, 1, 'Clicking the pill fires onOpen');
    pillMount.cleanup();

    // Empty: pill still renders (always-on).
    const emptyPill = mount(React.createElement(RunHistoryPill as never, { logs: [], onOpen: () => {} } as never));
    let ep: HTMLElement | undefined;
    await nc.wait.until(() => !!(ep = findIn(emptyPill.container, 'button', 'Runs')), 4000);
    nc.assert.truthy(ep, 'Pill renders with zero runs (always-on)');
    emptyPill.cleanup();
    await nc.wait.ms(30);

    // ── B. RunPicker: current run + inline dropdown w/ infinite scroll ────
    const picker = mount(React.createElement(RunPicker as never, {
        runs: manyLogs(now), currentExecId: 'exec-1', loading: false,
        hasMore: true, loadingMore: false,
        onLoadMore: () => loadedMore.push(1),
        onSelectRun: (l: WorkflowExecutionLog) => selected.push(l.id),
    } as never));
    let switcher: HTMLElement | undefined;
    await nc.wait.until(() => !!(switcher = findIn(picker.container, 'button', '2m ago')), 4000);
    nc.assert.truthy(switcher, 'Switcher shows the current run (2m ago)');

    // Open the dropdown. Scope to the dropdown panel itself (.top-full) so the
    // switcher button (also "…ago") isn't counted as a row.
    switcher!.click();
    await nc.wait.until(() => !!picker.container.querySelector('.top-full'), 3000);
    const panel = picker.container.querySelector('.top-full') as HTMLElement;
    nc.assert.truthy(findIn(panel, 'div', 'Switch run'), 'Dropdown header present');
    const rows = Array.from(panel.querySelectorAll('button')).filter((b) => (b.textContent || '').includes('ago'));
    nc.assert.equal(rows.length, 20, 'Dropdown lists all loaded runs (no recent-only cap)');
    nc.assert.truthy(findIn(panel, 'span', 'Webhook'), 'Reused TriggerBadge (Webhook) in dropdown');
    nc.assert.truthy(findIn(panel, 'span', 'Schedule'), 'cron → Schedule badge in dropdown');
    const dur = Array.from(panel.querySelectorAll('span')).map((e) => e.textContent || '').join(' ');
    nc.assert.truthy(dur.includes('3.4s') && dur.includes('800ms'), `Reused formatDuration in dropdown, got "${dur}"`);
    // The Logs shortcut is gone — infinite scroll replaces it.
    nc.assert.falsy(findIn(picker.container, 'button', 'View all runs'), 'No "View all runs" button (infinite scroll instead)');

    // Scroll to the bottom → the sentinel intersects → onLoadMore pages in more.
    const scroller = panel.querySelector('.overflow-y-auto') as HTMLElement;
    nc.assert.gt(scroller.scrollHeight, scroller.clientHeight, 'Dropdown list is scrollable');
    scroller.scrollTop = scroller.scrollHeight;
    await nc.wait.until(() => loadedMore.length > 0, 4000);
    nc.assert.gt(loadedMore.length, 0, 'Scrolling to the bottom fires onLoadMore (lazy load)');

    // Pick an older run → onSelectRun fires (inline dropdown ⇒ click lands).
    const older = rows.find((b) => /3h ago/.test(b.textContent || ''))!;
    older.click();
    await nc.wait.until(() => selected.length > 0, 3000);
    nc.assert.includes(selected, 'exec-3', 'Picking an older run fires onSelectRun with its id');
    await nc.wait.until(() => !findIn(picker.container, 'div', 'Switch run'), 2000);
    nc.assert.falsy(findIn(picker.container, 'div', 'Switch run'), 'Dropdown closes after selecting a run');
    picker.cleanup();

    // ── C. RunPicker loading state shows a spinner, not a stale time ──────
    const loadingPicker = mount(React.createElement(RunPicker as never, {
        runs: logs(now), currentExecId: 'exec-2', loading: true,
        hasMore: false, loadingMore: false, onLoadMore: () => {}, onSelectRun: () => {},
    } as never));
    await nc.wait.until(() => !!loadingPicker.container.querySelector('.animate-spin'), 3000);
    nc.assert.truthy(loadingPicker.container.querySelector('.animate-spin'), 'Switcher shows a spinner while loading');
    loadingPicker.cleanup();

    return { pillText, opened: opened.length, selected, loadedMore: loadedMore.length, rows: rows.length };
}
