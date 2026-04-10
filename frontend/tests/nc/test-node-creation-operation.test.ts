// Test: verify that nodes can be created with a default operation,
// and that buildSaveConfig produces a config the backend can validate.

import { nc } from '~/lib/nc';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';

export default async function () {
  const results: Record<string, any> = {};
  const testId = '__test_create_op';

  // Clean up
  nc.nodes.delete(testId);
  await nc.wait.ms(100);

  // Step 1: Get the default operation from schema
  const schemaInfo = getSchemaInfo('automation-google-sheets');
  const defaultOp = schemaInfo?.discriminator?.optionToValue?.get(0);
  results['schema_default_op'] = { defaultOp, pass: !!defaultOp };

  // Step 2: Create a node the way the drop handler should — with operation set
  nc.nodes.update(testId, {}); // This won't work — node doesn't exist yet

  // Use emit to create via MCP event
  nc.emit('mcp:builder_event', {
    workflow_id: nc.nodes.workflowId(),
    event_type: 'node_start',
    data: { node: {
      id: testId,
      type: 'automation-google-sheets',
      position: { x: 100, y: 500 },
      operation: defaultOp,
      label: 'Test Sheets',
    }},
  });
  await nc.wait.forNode(testId, () => true, 3000);

  // Step 3: Check the node has operation
  const node = nc.node(testId);
  results['node_has_operation'] = {
    operation: node?.operation,
    pass: node?.operation === defaultOp,
  };

  // Step 4: Check buildSaveConfig includes operation
  const rawNode = nc.nodes.list().find((n: any) => n.id === testId);
  if (rawNode) {
    const saveConfig = buildSaveConfig(rawNode as any);
    results['save_config'] = {
      hasOperation: 'operation' in saveConfig,
      operation: saveConfig.operation,
      pass: saveConfig.operation === defaultOp,
    };
  }

  // Step 5: Now simulate what happens with the EXISTING broken node (sheets_0c3l)
  // — it has no operation. Set it manually and verify save config.
  const brokenNode = nc.nodes.list().find((n: any) => n.id === 'sheets_0c3l');
  if (brokenNode) {
    // What does buildSaveConfig produce WITHOUT operation?
    const brokenConfig = buildSaveConfig(brokenNode as any);
    results['broken_node_config'] = {
      hasOperation: 'operation' in brokenConfig,
      operation: brokenConfig.operation,
      keys: Object.keys(brokenConfig),
    };
  }

  // Clean up
  nc.nodes.delete(testId);

  const allPass = Object.values(results).every((r: any) => r.pass !== false);
  return { allPass, results };
}
