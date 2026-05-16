// Verifies the "Used by interface" badge end to end: a node referenced by an
// interface-html-react node (via the SDK, by bare node ID in jsx_source) shows
// the badge; the interface node and unreferenced nodes do not; hovering opens a
// tooltip listing the interface, and clicking that link closes the tooltip; the
// badge persists whether the referenced node is isolated or wired into a flow.
// Builds a throwaway scenario on the canvas and cleans it up afterwards.
// Assertions are scoped to the test's own node IDs so a pre-existing workflow
// on the canvas is fine.

import { nc } from '~/lib/nc';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

const BADGE = '[data-testid="interface-consumer-badge"]';
const POPPER = '[data-radix-popper-content-wrapper]';

const badgeFor = (nodeId: string): HTMLElement | null =>
  document.querySelector(`${BADGE}[data-node-id="${nodeId}"]`);

export default async function () {
  const rf = (window as unknown as { __reactFlowInstance?: { addNodes?: (nodes: unknown[]) => void } })
    .__reactFlowInstance;
  if (!rf?.addNodes) throw new Error('no __reactFlowInstance.addNodes');

  const ts = Date.now();
  const refId = `dbg_ref_${ts}`;
  const interfaceId = `dbg_iface_${ts}`;
  const sinkId = `dbg_sink_${ts}`;
  const createdIds = [refId, interfaceId, sinkId];
  const ifaceLabel = `Test Dashboard ${ts}`;

  try {
    const ref = createWorkflowNode(refId, 'delay', { x: 200, y: 200 });
    const sink = createWorkflowNode(sinkId, 'delay', { x: 600, y: 200 });
    const iface = createWorkflowNode(interfaceId, 'interface-html-react', { x: 200, y: 500 }, {
      operation: 'render_jsx_react_interface',
      jsx_source: `import { nodes } from '@noclick/sdk';\nconst out = await nodes.getOutput('${refId}');\n`,
    });
    iface.data.label = ifaceLabel;
    rf.addNodes([ref, sink, iface]);

    await nc.wait.until(() => !!badgeFor(refId), 5000);

    // Badge appears on the referenced node only.
    const badge = badgeFor(refId)!;
    nc.assert.equal(badge.textContent?.includes('Used by'), true, 'badge reads "Used by ..."');
    nc.assert.equal(!!badgeFor(interfaceId), false, 'interface node itself must not show a badge');
    nc.assert.equal(!!badgeFor(sinkId), false, 'an unreferenced node must not show a badge');

    // Hover opens a tooltip that lists the interface by name.
    badge.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true }));
    badge.dispatchEvent(new PointerEvent('pointermove', { bubbles: true }));
    await nc.wait.until(() => !!document.querySelector(POPPER), 3000);
    const link = document.querySelector(`${POPPER} button`) as HTMLElement | null;
    nc.assert.equal(link?.textContent?.includes(ifaceLabel), true, 'tooltip lists the interface name');

    // Clicking a link closes the tooltip — regression guard: it used to survive
    // the canvas pan because Radix stranded the portaled content mid-unmount.
    link!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    await nc.wait.until(() => !document.querySelector(POPPER), 3000);
    nc.assert.equal(!!document.querySelector(POPPER), false, 'tooltip closes after clicking a link');

    // The badge tracks the interface reference, not connectivity — wiring the
    // node into a flow must NOT remove it.
    nc.nodes.addEdge(refId, sinkId);
    await nc.wait.ms(500);
    nc.assert.equal(!!badgeFor(refId), true, 'badge should persist after the node gets an edge');

    return { ok: true, refId, interfaceId };
  } finally {
    for (const id of createdIds) nc.nodes.delete(id);
  }
}
