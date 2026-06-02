// E2E (nc bridge) for the CAS Storage admin dashboard backend: hits the
// internal-gated /admin/cas/* endpoints through the running app with the
// session cookie and asserts the global-stats + flow-ranking shapes. Verifies
// the whole S5 path live (auth gate, stats cache read, JSON shape). Run as an
// internal user; a non-internal session would 403 here.
// Run: nc_run_test({ file: "tests/nc/cas-admin-dashboard.test.ts" })
import { nc } from '~/lib/nc';

const API = (import.meta.env.VITE_API_URL as string) || '';

export default async function () {
  const statsRes = await fetch(`${API}/admin/cas/stats`, { credentials: 'include' });
  nc.assert.equal(statsRes.status, 200, `/admin/cas/stats reachable for internal user (got ${statsRes.status})`);
  const global = await statsRes.json();
  for (const k of ['dedup_ratio', 'physical_bytes', 'logical_bytes', 'postgres_bytes', 'chunk_count', 'executions_lifetime']) {
    nc.assert.truthy(k in global, `global stats has ${k}`);
  }

  const flowsRes = await fetch(`${API}/admin/cas/flows?limit=10`, { credentials: 'include' });
  nc.assert.equal(flowsRes.status, 200, 'flows endpoint reachable');
  const { flows } = await flowsRes.json();
  nc.assert.truthy(Array.isArray(flows), 'flows is an array');

  // If any flow exists, the per-flow breakdown endpoint must resolve too.
  let breakdownOk = 'no-flows';
  if (flows.length > 0) {
    const bRes = await fetch(`${API}/admin/cas/flows/${flows[0].workflow_id}`, { credentials: 'include' });
    nc.assert.equal(bRes.status, 200, 'flow breakdown reachable');
    const b = await bRes.json();
    nc.assert.truthy(Array.isArray(b.by_node) && Array.isArray(b.largest_blobs), 'breakdown shape');
    breakdownOk = 'ok';
  }

  return { ok: true, global, flowCount: flows.length, breakdownOk };
}
