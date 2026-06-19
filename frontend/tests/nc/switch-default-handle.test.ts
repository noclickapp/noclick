// Verifies a freshly-dropped switch node (empty config) renders an always-present
// "default" fallback output handle, and that adding a case keeps it alongside the
// case handle. Guards the fix for the empty-initial-drop switch node.
import { nc } from '~/lib/nc';

const NODE_ID = 'debug-switch-default';

function sourceHandleIds(nodeId: string): string[] {
  const el = document.querySelector(`[data-id="${nodeId}"]`);
  if (!el) return [];
  // Only the switch's output handles carry an id; the input target handle has none.
  return Array.from(el.querySelectorAll('.react-flow__handle'))
    .map((h) => h.getAttribute('data-handleid') || '')
    .filter((id) => id && id !== 'null');
}

export default async function () {
  // Clean slate if a prior run left the node behind.
  nc.nodes.delete(NODE_ID);
  await nc.wait.ms(50);

  // Drop a switch node with no config (the "initially dropped" state).
  const added = nc.nodes.add(NODE_ID, 'switch', {}, { x: 400, y: 200 });
  nc.assert.equal(added, true, 'switch node should be added');
  await nc.wait.forElement(`[data-id="${NODE_ID}"]`);
  await nc.wait.ms(150); // let handles render

  // Fresh switch must expose exactly the "default" fallback handle.
  const fresh = sourceHandleIds(NODE_ID);
  nc.assert.equal(fresh.length, 1, `fresh switch should have 1 output handle, got ${fresh.join(',')}`);
  nc.assert.equal(fresh[0], 'default', 'the lone output handle should be "default"');

  // Adding a case should keep the default handle and add the case handle.
  nc.nodes.update(NODE_ID, { config: { switch_cases: [{ value: 'approved' }] } });
  await nc.wait.ms(200);
  const withCase = sourceHandleIds(NODE_ID).sort();
  nc.assert.equal(
    JSON.stringify(withCase),
    JSON.stringify(['approved', 'default']),
    `expected approved + default handles, got ${withCase.join(',')}`,
  );

  // Cleanup.
  nc.nodes.delete(NODE_ID);

  return { fresh, withCase };
}
