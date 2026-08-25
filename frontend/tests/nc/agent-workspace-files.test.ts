// Live smoke for the agent workspace file view: drives the real
// agent_workspace:list socket event from the browser session against the
// local backend and asserts the response shape (access check, volume
// resolution, workspace listing). Complements the unit suites, which cover the
// resolver/token/route logic in isolation.
import { nc } from '~/lib/nc';
import { sendEventAsync } from '~/lib/socket-sender';

export default async function () {
  const agent = nc.nodes.list().find((n: { type?: string }) => n.type === 'agent');
  // Every open tab runs the test and the FIRST nc:result wins — tabs without
  // the canvas harness must lose that race, not answer it.
  if (!agent) {
    await nc.wait.ms(10000);
    return { skipped: 'no canvas harness in this tab' };
  }
  const workflowId = nc.nodes.workflowId();
  nc.assert.truthy(!!workflowId, 'workflow id resolvable from the open canvas');

  const res = await sendEventAsync<{
    success: boolean; error?: string; workspace?: string | null;
    exists?: boolean; files?: { path: string; url_path: string }[];
  }>({
    event_name: 'agent_workspace:list',
    workflow_id: workflowId as string,
    node_id: agent.id as string,
    conversation_key: '__interface_chat__',
  });

  nc.assert.truthy(res.success, `list succeeded (error: ${res.error ?? 'none'})`);
  nc.assert.equal(res.workspace, '/workspace', 'per-CK workspace mount resolved');
  const first = res.files?.[0];
  if (first) {
    nc.assert.truthy(
      first.url_path.startsWith('/agent/workspace/file?token='),
      'files carry signed streaming url paths',
    );
  }
  return {
    success: res.success,
    exists: res.exists,
    fileCount: res.files?.length ?? 0,
    firstFile: first?.path ?? null,
  };
}
