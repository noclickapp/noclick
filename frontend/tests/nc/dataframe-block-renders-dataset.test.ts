// Verifies the DataframeBlock renders rows from a configured dataset resource,
// not the SAMPLE_ROWS fallback. Regression test for the bug where selecting a
// dataset in the Table block dropdown only ever showed dummy data.

import { nc } from '~/lib/nc';
import { sendEventAsync } from '~/lib/socket-sender';
import {
  ResourceCreateRequest,
  ResourceDatasetAppendRequest,
  ResourceDatasetRowsRequest,
  ResourceDeleteRequest,
} from '~/types/socket-events.generated';

const TEST_ROWS = [
  { sku: 'NC-001', label: 'Hydrofoil', stock: 7 },
  { sku: 'NC-002', label: 'Caliper', stock: 12 },
  { sku: 'NC-003', label: 'Turbine', stock: 3 },
];

export default async function () {
  const workflowId = nc.nodes.workflowId();
  if (!workflowId) throw new Error('No workflow loaded');

  // 1. Create a fresh dataset resource and append rows.
  const createRes = await sendEventAsync(
    ResourceCreateRequest.create({
      workflow_id: workflowId,
      resource_type: 'dataset',
      name: 'nc-dataframe-regression',
      node_id: 'nc-dataframe-test',
      metadata: { row_count: TEST_ROWS.length },
    }),
  );
  const resourceId = createRes.resource!.id;
  const nodeId = `nc-table-${Date.now()}`;

  try {
    await sendEventAsync(
      ResourceDatasetAppendRequest.create({ resource_id: resourceId, rows: TEST_ROWS }),
    );

    // Sanity-check the round-trip the block now uses.
    const rowsRes = await sendEventAsync(
      ResourceDatasetRowsRequest.create({ resource_id: resourceId, limit: 100 }),
    );
    nc.assert.equal(rowsRes.rows.length, TEST_ROWS.length, 'dataset rows persisted');
    nc.assert.equal(
      (rowsRes.rows[0].data as Record<string, unknown>).sku,
      TEST_ROWS[0].sku,
      'first row roundtrip',
    );

    // 2. Drop an interface-dataframe node into the workflow with resource_id set.
    const added = nc.nodes.add(nodeId, 'interface-dataframe', { resource_id: resourceId });
    nc.assert.truthy(added, 'addNode succeeded');

    // 3. Open the Interface tab and wait for the grid to render real rows.
    nc.ui.clickTab('Interface');
    await nc.wait.until(() => {
      const cells = nc.dom.qsa('.ag-cell-value').map(c => c.textContent?.trim() ?? '');
      return cells.includes('NC-001') && cells.includes('Hydrofoil');
    }, 8000);

    const cellTexts = nc.dom.qsa('.ag-cell-value').map(c => c.textContent?.trim() ?? '');
    nc.assert.truthy(cellTexts.includes('NC-001'), 'sku cell rendered');
    nc.assert.truthy(cellTexts.includes('Hydrofoil'), 'label cell rendered');
    nc.assert.truthy(cellTexts.includes('Turbine'), 'third row rendered');
    nc.assert.falsy(cellTexts.includes('Alpha'), 'SAMPLE_ROWS not shown');

    // 4. Refresh button is portaled into the BlockWrapper title bar and
    //    re-runs the dataset fetch when clicked.
    const refreshBtn = nc.dom.qs('button[title="Refresh dataset"]') as HTMLButtonElement | null;
    nc.assert.truthy(refreshBtn, 'refresh button rendered in BlockWrapper header');
    await sendEventAsync(
      ResourceDatasetAppendRequest.create({
        resource_id: resourceId,
        rows: [{ sku: 'NC-999', label: 'Refreshed', stock: 1 }],
      }),
    );
    refreshBtn!.click();
    await nc.wait.until(() => {
      const cells = nc.dom.qsa('.ag-cell-value').map(c => c.textContent?.trim() ?? '');
      return cells.includes('NC-999') && cells.includes('Refreshed');
    }, 5000);

    return { ok: true, resourceId, nodeId, cellTexts: cellTexts.slice(0, 12) };
  } finally {
    nc.nodes.delete(nodeId);
    try {
      await sendEventAsync(ResourceDeleteRequest.create({ resource_id: resourceId }));
    } catch {
      // best-effort cleanup
    }
  }
}
