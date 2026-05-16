// Verifies the FlowHelperView single-node Run button flips to Stop when the
// selected node enters the 'running' state and reverts to Run on terminal states.
// Run with: mcp__nc__nc_run_test({ file: "tests/nc/flow-helper-stop-button.test.ts" })

import { nc } from '~/lib/nc';

const BTN = '[data-tour-target="flow-helper-run-btn"]';

async function btn() {
  await nc.wait.forElement(BTN);
  return document.querySelector(BTN) as HTMLButtonElement;
}

export default async function () {
  const allNodes = nc.nodes.list();
  const target = allNodes.find((n: any) => n.type !== 'interface-html-react') ?? allNodes[0];
  if (!target) throw new Error('No nodes in workflow to test against');

  const restore = { executionState: target.data?.executionState, _executionId: target.data?._executionId };

  try {
    nc.nodes.select(target.id);
    await nc.wait.ms(300);

    const initial = await btn();
    const initialText = initial.textContent?.trim();

    nc.nodes.update(target.id, { executionState: 'running', _executionId: 'test-exec-1' });
    await nc.wait.until(async () => (await btn()).textContent?.trim() === 'Stop', 2000);
    const running = await btn();
    nc.assert.equal(running.textContent?.trim(), 'Stop', 'Button should show Stop while running');
    nc.assert.equal(running.getAttribute('aria-label'), 'Stop node', 'Stop button aria-label');
    nc.assert.truthy(running.className.includes('bg-zinc-800'), 'Stop button uses dark styling');
    nc.assert.falsy(running.disabled, 'Stop button must be clickable');

    nc.nodes.update(target.id, { executionState: 'completed' });
    await nc.wait.until(async () => (await btn()).textContent?.trim() === 'Run', 2000);
    const completed = await btn();
    nc.assert.equal(completed.textContent?.trim(), 'Run', 'Button reverts to Run on terminal state');

    nc.nodes.update(target.id, { executionState: 'running', _executionId: 'test-exec-2' });
    await nc.wait.until(async () => (await btn()).textContent?.trim() === 'Stop', 2000);
    nc.nodes.update(target.id, { executionState: 'error' });
    await nc.wait.until(async () => (await btn()).textContent?.trim() === 'Run', 2000);

    return { ok: true, nodeId: target.id, initialText };
  } finally {
    nc.nodes.update(target.id, restore);
  }
}
