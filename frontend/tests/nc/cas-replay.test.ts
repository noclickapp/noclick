// E2E (nc bridge) for the execution-log replay interaction. The replay now
// renders THROUGH the live FlowCanvas itself (isReplayMode swaps the displayed
// nodes/edges and gates every mutation entry point), so this asserts:
//   - banner appears on row click
//   - the live canvas wrapper [data-testid="flow-canvas"] stays mounted (same
//     ReactFlow, same FlowHelperView, same keyboard shortcuts)
//   - rendered xyflow nodes carry the `nodrag` class (nodesDraggable=false)
//   - selecting a node opens FlowHelperView with all 4 tabs (UX / Nodes /
//     Config / Credentials)
//   - Exit replay clears the banner
// Requires a workflow that has execution history; otherwise reports {skipped}.
// Run: mcp__nc__nc_run_test({ file: "tests/nc/cas-replay.test.ts" })
import { nc } from '~/lib/nc';

const hasText = (t: string): boolean => nc.dom.qsa('*').some((el) => (el.textContent || '').includes(t));
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
// The canvas tab buttons key off visible text, not a `title` attr, so nc.ui.clickTab
// (which matches button[title=...]) can't find them — click by text instead.
const clickTabByText = (text: string): boolean => {
    const btn = nc.dom.qsa('button').find((b) => (b.textContent || '').trim() === text) as HTMLElement | undefined;
    if (btn) { btn.click(); return true; }
    return false;
};

export default async function () {
    if (!clickTabByText('Logs')) return { skipped: 'no Logs tab (not on a workflow?)' };

    // Log rows carry role="button" + the per-status left accent rail (border-l-2).
    // Poll — the Logs tab content mounts on click and rows render a tick later.
    let rows: Element[] = [];
    for (let i = 0; i < 20 && rows.length === 0; i++) {
        rows = nc.dom.qsa('[role="button"]').filter((el) => el.className.includes('border-l-2'));
        if (rows.length === 0) await sleep(100);
    }
    if (rows.length === 0) return { skipped: 'no execution runs to replay' };

    (rows[0] as HTMLElement).click();

    // Switched to the Workflow tab + replay banner appears.
    await nc.wait.forElement('[data-testid="flow-canvas"]');
    let bannerShown = false;
    for (let i = 0; i < 20 && !bannerShown; i++) {
        bannerShown = hasText('Viewing execution run');
        if (!bannerShown) await sleep(100);
    }
    nc.assert.equal(bannerShown, true, 'replay banner shown after clicking a run');

    // Wait for xyflow nodes to render inside the live canvas (replay snapshot
    // is rendered through it now — there is no separate replay canvas wrapper).
    let nodeEls: Element[] = [];
    for (let i = 0; i < 30 && nodeEls.length === 0; i++) {
        nodeEls = nc.dom.qsa('[data-testid="flow-canvas"] .react-flow__node');
        if (nodeEls.length === 0) await sleep(100);
    }
    nc.assert.gt(nodeEls.length, 0, 'replay snapshot renders through the live canvas');

    // Locked: every rendered xyflow node carries xyflow's `nodrag` class (set
    // when nodesDraggable=false) or has `draggable="false"`.
    const allLocked = nodeEls.every((el) =>
        el.className.includes('nodrag') || (el as HTMLElement).getAttribute('draggable') === 'false',
    );
    nc.assert.equal(allLocked, true, 'all replay nodes are non-draggable');

    // Click a node → FlowHelperView opens with all 4 tabs (UX / Nodes / Config / Credentials).
    (nodeEls[0] as HTMLElement).click();
    await sleep(300);
    const findTab = (label: string) =>
        nc.dom.qsa('button').some((b) => {
            const text = (b.textContent || '').trim();
            return text.startsWith(label) || (b.getAttribute('title') || '').startsWith(label);
        });
    nc.assert.equal(findTab('UX'), true, 'UX tab present (live FlowHelperView mounted)');
    nc.assert.equal(findTab('Nodes'), true, 'Nodes tab present');
    nc.assert.equal(findTab('Config'), true, 'Config tab present');
    nc.assert.equal(findTab('Credentials'), true, 'Credentials tab present');

    // Exit replay → banner clears, back to the live flow.
    const exitBtn = nc.dom.qsa('button').find((b) => (b.textContent || '').includes('Exit replay')) as HTMLElement | undefined;
    nc.assert.equal(!!exitBtn, true, 'Exit replay button present');
    exitBtn!.click();
    await sleep(250);
    nc.assert.equal(hasText('Viewing execution run'), false, 'banner cleared after exit replay');

    return { ok: true, rowsAvailable: rows.length, replayNodeCount: nodeEls.length };
}
