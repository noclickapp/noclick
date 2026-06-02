// E2E (nc bridge) for the CAS Storage admin dashboard backend: hits the
// internal-gated /admin/cas/* endpoints through the running app with the
// session cookie and asserts the global-stats + flow-ranking shapes. Verifies
// the whole S5 path live (auth gate, stats cache read, JSON shape). Run as an
// internal user; a non-internal session would 403 here.
// Run: nc_run_test({ file: "tests/nc/cas-admin-dashboard.test.ts" })
import { nc } from '~/lib/nc';
import { getExistingBrowserClient } from '~/lib/supabase-client';

const API = (import.meta.env.VITE_API_URL as string) || '';

// Mirror the component: send the live Supabase access token as a Bearer header
// (the cookie is SameSite=Lax / app-domain-scoped, so it doesn't auth cross-origin).
async function get<T>(path: string): Promise<{ status: number; body: T }> {
  const client = getExistingBrowserClient();
  const { data } = client ? await client.auth.getSession() : { data: { session: null } };
  const token = data.session?.access_token;
  const res = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return { status: res.status, body: res.status === 200 ? await res.json() : (undefined as T) };
}

export default async function () {
  const stats = await get<Record<string, unknown>>('/admin/cas/stats');
  nc.assert.equal(stats.status, 200, `/admin/cas/stats reachable for internal user (got ${stats.status})`);
  for (const k of ['dedup_ratio', 'physical_bytes', 'logical_bytes', 'postgres_bytes', 'chunk_count', 'executions_lifetime']) {
    nc.assert.truthy(k in stats.body, `global stats has ${k}`);
  }

  const flowsRes = await get<{ flows: { workflow_id: string }[] }>('/admin/cas/flows?limit=10');
  nc.assert.equal(flowsRes.status, 200, 'flows endpoint reachable');
  const flows = flowsRes.body.flows;
  nc.assert.truthy(Array.isArray(flows), 'flows is an array');

  let breakdownOk = 'no-flows';
  if (flows.length > 0) {
    const b = await get<{ by_node: unknown[]; largest_blobs: unknown[] }>(`/admin/cas/flows/${flows[0].workflow_id}`);
    nc.assert.equal(b.status, 200, 'flow breakdown reachable');
    nc.assert.truthy(Array.isArray(b.body.by_node) && Array.isArray(b.body.largest_blobs), 'breakdown shape');
    breakdownOk = 'ok';
  }

  return { ok: true, global: stats.body, flowCount: flows.length, breakdownOk };
}
