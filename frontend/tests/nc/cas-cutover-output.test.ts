// E2E (nc bridge) for the CAS cutover: node outputs are served solely by the
// content-addressed store, never the workflow graph JSONB. Verifies that
// (1) workflow:get_node_outputs returns outputs from the CAS for a workflow with
// execution history, and (2) the loaded graph node configs carry NO embedded
// `output` (the legacy dual-write is gone, so a stale config.output can't shadow
// the fresh CAS value). Requires a workflow that has run at least once;
// otherwise it reports {skipped}.
// Run: mcp__nc__nc_run_test({ file: "tests/nc/cas-cutover-output.test.ts" })
import { nc } from '~/lib/nc';

export default async function () {
  const workflowId = nc.nodes.workflowId();
  if (!workflowId) return { skipped: 'no workflowId (not on a workflow?)' };

  // (1) CAS read path: outputs come back from get_node_outputs (CAS-backed).
  const resp = (await nc.send({ event_name: 'workflow:get_node_outputs', workflow_id: workflowId })) as {
    outputs?: Record<string, unknown>;
  };
  const outputs = resp?.outputs ?? {};
  const outputCount = Object.keys(outputs).length;
  if (outputCount === 0) return { skipped: 'no CAS outputs yet — run the workflow once' };

  // (2) Stale-shadow guard: the loaded graph must NOT embed config.output.
  const wf = (await nc.send({ event_name: 'workflow:get', workflow_id: workflowId })) as {
    workflow?: { workflow_data?: { nodes?: Array<{ id: string; config?: Record<string, unknown> }> } };
  };
  const nodes = wf?.workflow?.workflow_data?.nodes ?? [];
  const embedded = nodes.filter((n) => n.config && 'output' in n.config).map((n) => n.id);
  nc.assert.equal(
    embedded.length,
    0,
    `graph JSONB must not embed config.output post-cutover (offenders: ${embedded.join(', ')})`,
  );

  // (3) The canvas hydrates node.data.output from the CAS response.
  const hydrated = nc.nodes.list().filter((n) => n.data?.output !== undefined).length;

  return { ok: true, outputCount, nodeCount: nodes.length, hydrated };
}
