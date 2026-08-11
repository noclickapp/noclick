// Verifies that AutomationNode renders a second source handle (id="error")
// when node.data.config._settings.onError === 'continueErrorOutput', and
// hides it for the default 'stopWorkflow' setting.

import { nc } from '~/lib/nc';

export default async function () {
  const allNodes = nc.nodes.list();
  // Pick the first automation node on the canvas — they all share AutomationNode.
  const target = allNodes.find((n: any) =>
    n.type && !['conditional', 'switch', 'iteration', 'on-error', 'sticky-note', 'agent', 'approval', 'alarm', 'mcp-server', 'noclick', 'state-manager', 'serverless-function', 'filesystem', 'interface', 'tool', 'run-trigger', 'merge', 'filter'].includes(n.type)
  );
  nc.assert.truthy(target, 'Need at least one automation node on the canvas');
  const nodeId = target.id;

  // Snapshot baseline handle count
  const handlesBefore = document.querySelectorAll(`[data-id="${nodeId}"] .react-flow__handle`).length;

  // Toggle the setting
  nc.nodes.update(nodeId, {
    config: {
      ...(target.data?.config ?? {}),
      _settings: { ...((target.data?.config as any)?._settings ?? {}), onError: 'continueErrorOutput' },
    },
  });

  await nc.wait.ms(150);
  const handlesAfter = document.querySelectorAll(`[data-id="${nodeId}"] .react-flow__handle`).length;
  const errorHandle = document.querySelector(`[data-id="${nodeId}"] .react-flow__handle[data-handleid="error"]`);

  nc.assert.truthy(errorHandle, 'Error handle (id="error") should be present');
  nc.assert.gt(handlesAfter, handlesBefore, 'Total handle count should increase after enabling error output');

  // Toggle back
  nc.nodes.update(nodeId, {
    config: {
      ...(nc.nodes.get(nodeId).data?.config ?? {}),
      _settings: { ...(nc.nodes.get(nodeId).data?.config as any)?._settings, onError: 'stopWorkflow' },
    },
  });
  await nc.wait.ms(150);
  const errorHandleAfterRevert = document.querySelector(`[data-id="${nodeId}"] .react-flow__handle[data-handleid="error"]`);
  nc.assert.truthy(!errorHandleAfterRevert, 'Error handle should disappear when onError reverts to stopWorkflow');

  return { nodeId, handlesBefore, handlesAfter };
}
