/**
 * End-to-end test for the external SDK via WebSocket transport.
 *
 * Prerequisites:
 *   1. Backend running on localhost:8005
 *   2. API key created:
 *      cd backend && python scripts/create_api_key.py --user-id <your-uuid> --name "Test"
 *   3. socket.io-client installed:
 *      npm install socket.io-client
 *
 * Usage:
 *   node test-external.mjs <api-key> [workflow-id]
 */

import { init, nodes, execution, state, auth, resources, dataset, workflow } from './dist/sdk.esm.js';

const apiKey = process.argv[2];
const workflowId = process.argv[3];

if (!apiKey) {
  console.error('Usage: node test-external.mjs <api-key> [workflow-id]');
  process.exit(1);
}

console.log('Connecting to NoClick backend...');
console.log('  API key: configured');
console.log(`  Workflow: ${workflowId || '(all)'}`);

try {
  await init({
    transport: 'websocket',
    url: 'http://localhost:8005',
    apiKey,
    workflowId,
  });
  console.log('✓ Connected!\n');
} catch (e) {
  console.error('✗ Connection failed:', e.message);
  process.exit(1);
}

// --- Test: workflow.getInfo ---
console.log('--- workflow.getInfo ---');
try {
  const info = await workflow.getInfo();
  console.log('  Info:', JSON.stringify(info));
} catch (e) {
  console.log('  Error:', e.message);
}

// --- Test: nodes.list ---
console.log('\n--- nodes.list ---');
try {
  const allNodes = await nodes.list();
  console.log(`  Found ${allNodes.length} nodes:`);
  allNodes.forEach(n => console.log(`    ${n.id} (${n.type}) — ${n.label}`));
} catch (e) {
  console.log('  Error:', e.message);
}

// --- Test: auth.listCredentials ---
console.log('\n--- auth.listCredentials ---');
try {
  const creds = await auth.listCredentials();
  console.log(`  Found ${creds.length} credentials`);
  creds.slice(0, 3).forEach(c => console.log(`    ${c.name} (${c.type})`));
} catch (e) {
  console.log('  Error:', e.message);
}

// --- Test: resources.list ---
console.log('\n--- resources.list ---');
try {
  const res = await resources.list();
  console.log(`  Found ${res.length} resources`);
  res.slice(0, 3).forEach(r => console.log(`    ${r.name} (${r.resourceType})`));
} catch (e) {
  console.log('  Error:', e.message);
}

// --- Test: dataset.create + appendRows + getRows ---
console.log('\n--- dataset CRUD ---');
try {
  const dsId = await dataset.create('SDK Test Dataset');
  console.log(`  Created dataset: ${dsId}`);

  await dataset.appendRows(dsId, [
    { name: 'Alice', score: 95 },
    { name: 'Bob', score: 87 },
  ]);
  console.log('  Appended 2 rows');

  const page = await dataset.getRows(dsId, { limit: 10 });
  console.log(`  Read ${page.rows.length} rows (total: ${page.totalCount})`);
  page.rows.forEach(r => console.log(`    ${r.id}: ${JSON.stringify(r.data)}`));
} catch (e) {
  console.log('  Error:', e.message);
}

console.log('\n✓ All tests complete');
process.exit(0);
