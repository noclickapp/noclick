// Example nc test demonstrating the test file pattern.
// Run with: mcp__nc__nc_run_test({ file: "tests/nc/example.test.ts" })

import { nc } from '~/lib/nc';

export default async function () {
  const title = document.title;
  const url = window.location.href;

  const workflowId = nc.nodes.workflowId();
  const nodeCount = nc.nodes.count();
  const nodeTypes = nc.nodes.list().map((n: any) => n.type);
  const activeTab = nc.ui.getActiveTab();

  return {
    title,
    url,
    workflowId,
    nodeCount,
    nodeTypes,
    activeTab,
  };
}
