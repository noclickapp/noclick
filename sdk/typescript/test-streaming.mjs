/**
 * Test: run a node and get streaming output via WebSocket transport.
 *
 * Usage:
 *   node test-streaming.mjs <api-key> <workflow-id> <node-id>
 *
 * Example:
 *   node test-streaming.mjs nk_live_... 377a8f23-... automation-serverless-function-...
 */

import { init, execution, nodes } from './dist/sdk.esm.js';

const apiKey = process.argv[2];
const workflowId = process.argv[3];
const nodeId = process.argv[4];

if (!apiKey || !workflowId || !nodeId) {
  console.error('Usage: node test-streaming.mjs <api-key> <workflow-id> <node-id>');
  process.exit(1);
}

console.log('Connecting...');
await init({
  transport: 'websocket',
  url: 'http://localhost:8005',
  apiKey,
  workflowId,
});
console.log('✓ Connected\n');

// First read existing output to compare timestamps
console.log('--- Reading existing output ---');
const before = await nodes.getOutput(nodeId);
console.log('  Existing timestamp:', before?.result?.generated_at || 'none');

// Run and stream
console.log('\n--- execution.runNodesAndGetOutput ---');
const stream = execution.runNodesAndGetOutput([nodeId], [nodeId]);

stream.on('output', (nid, data) => {
  console.log(`  [stream:output] nodeId=${nid}`);
  console.log(`    data:`, JSON.stringify(data).substring(0, 200));
});

stream.on('error', (nid, error) => {
  console.log(`  [stream:error] nodeId=${nid} error=${error}`);
});

stream.on('done', () => {
  console.log('  [stream:done] All targets completed');
});

console.log('  Waiting for stream.all()...');
try {
  const results = await stream.all();
  console.log('\n--- Results ---');
  for (const [nid, data] of Object.entries(results)) {
    console.log(`  ${nid}:`, JSON.stringify(data).substring(0, 200));
  }
} catch (e) {
  console.error('  Error:', e.message);
}

// Verify the output is fresh
console.log('\n--- Verifying fresh output ---');
const after = await nodes.getOutput(nodeId);
console.log('  New timestamp:', after?.result?.generated_at || 'none');
console.log('  Is different from before:', (before?.result?.generated_at || '') !== (after?.result?.generated_at || ''));

console.log('\n✓ Streaming test complete');
process.exit(0);
