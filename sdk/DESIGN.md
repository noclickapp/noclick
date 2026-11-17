# @noclick/sdk Design

## Overview

The SDK lets custom React components (running in iframes) interact with the NoClick workflow they belong to. It provides a JavaScript API for reading data, triggering execution, managing state, and handling credentials.

**Transport**: `window.parent.postMessage()` (iframe → host). The host (HtmlReactBlock) translates messages into socket events / Valtio state mutations. A future WebSocket transport enables the same API for external web apps.

---

## Core Design Principles

1. **Components don't know about storage backends.** The SDK exposes nodes, outputs, and state — never SQL, R2, or IndexedDB directly.
2. **Edges define the data contract.** A component's primary inputs come from upstream nodes via edges (same as any workflow node). The SDK also provides escape hatches to read any node's output.
3. **State is node-scoped.** Persistent state lives in state-manager nodes. The SDK wraps read/write with an updater pattern for safe modifications.
4. **LLM-friendly API.** Separate functions for separate intents — no mode flags or overloaded parameters. Function names describe what they do.

---

## API Surface

### 1. Inputs (data flowing into this component)

The component node receives inputs from upstream nodes via edges, just like any other node. These are passed to the component automatically.

```typescript
import { useInputs, onInputsChanged } from '@noclick/sdk';

// Hook: reactive inputs (re-renders component when inputs change)
function Dashboard() {
  const inputs = useInputs();
  // inputs = { value: <upstream output>, ... } — same shape as execute(inputs)
  return <div>{JSON.stringify(inputs)}</div>;
}

// Callback: for non-React or imperative use
onInputsChanged((inputs) => {
  console.log('Inputs updated:', inputs);
});
```

**How it works**: When the workflow runs, upstream nodes produce outputs that flow into this node. The host sends them to the iframe via `postMessage`. The SDK stores them in a reactive ref and triggers re-renders.

### 2. Node Operations (read/write any node)

```typescript
import { nodes } from '@noclick/sdk';

// Read a node's last output (may be from any previous run — cron, manual, etc.)
const output = await nodes.getOutput('data-fetcher-node-id');

// Read a node's config
const config = await nodes.getConfig('form-node-id');

// Set a node's config field (e.g., fill an upstream form value)
await nodes.setConfig('http-request-node-id', { url: 'https://api.example.com/new' });

// List all nodes in the workflow (for dynamic discovery)
const allNodes = await nodes.list();
// Returns: [{ id, type, label, hasOutput }, ...]
```

### 3. Execution

Two functions, two intents. Both accept nodes as strings (use existing config) or objects with temporary config overrides:

```typescript
import { execution } from '@noclick/sdk';

// Type for node references — string or object with config overrides
type NodeRef = string | { id: string; config: Record<string, any> };
```

**Run and stream output:**

```typescript
// Run nodes and get output as each target node completes (streaming).
// First arg: nodes to execute. Second arg: nodes whose output we want.
const stream = execution.runNodesAndGetOutput(
  ['data-fetcher'],              // nodes to execute (use existing config)
  ['chart-data', 'summary']      // nodes whose output we want
);

// With config overrides — temporary, doesn't save to the node's config
const stream = execution.runNodesAndGetOutput(
  [{ id: 'http-node', config: { url: userInput } }],
  ['http-node']
);

// Stream: fires as each target completes — render incrementally
stream.on('output', (nodeId, output) => {
  if (nodeId === 'chart-data') setChartData(output);
  if (nodeId === 'summary') setSummary(output);
});

stream.on('error', (nodeId, error) => {
  console.error(`${nodeId} failed:`, error);
});

stream.on('done', () => {
  // All target nodes completed
});

// Or await all at once if streaming isn't needed
const results = await stream.all();
// { 'chart-data': { ... }, 'summary': { ... } }
```

**Fire and forget:**

```typescript
// Kick off a long-running job with existing config
execution.runNodesInBackground(['data-fetcher']);

// With config overrides
execution.runNodesInBackground([
  { id: 'llm-node', config: { prompt: 'Summarize the Q4 report' } }
]);
```

**Other:**

```typescript
// Stop a running execution
execution.stop();
```

**Stale output prevention**: `runNodesAndGetOutput()` generates a unique execution ID internally. The host only forwards output events tagged with that execution ID. Output from previous runs (cron, manual, etc.) is ignored for the stream — but `nodes.getOutput()` always returns whatever exists, stale or not.

**Config overrides**: When a `NodeRef` includes `config`, the overrides are applied only for that execution. The node's saved config is not modified. This is useful for components that need to run a node with user-provided input (search queries, form data, selected options) without mutating the workflow.

**Streaming**: The stream fires `output` events as each target node completes. This lets the UI render partially — a chart can appear while a summary is still computing. `done` fires when all targets have completed.

**Subscribing to execution state** (for loading animations, progress indicators):

```typescript
// Subscribe to node state changes (works for any execution, not just SDK-triggered)
execution.onNodeState('transformer', (state) => {
  // state = 'idle' | 'running' | 'completed' | 'error'
});

// Subscribe to streaming output from a node (e.g., LLM streaming tokens)
execution.onNodeOutput('llm-node', (output) => {
  // Fires on each emit() from the node
});
```

### 4. State (persistent key-value)

State is stored via state-manager nodes in the workflow. The SDK provides a scoped read/write API.

```typescript
import { state } from '@noclick/sdk';

// Read a value
const counter = await state.get('counter');
// Returns: the current value, or undefined if not set

// Set a value (overwrites)
await state.set('counter', 42);

// Update with a function (read-modify-write, runs locally)
await state.update('items', (current) => [...(current || []), newItem]);
await state.update('counter', (n) => (n || 0) + 1);

// Subscribe to state changes (from any source — other components, node executions)
state.onChange('counter', (newValue) => {
  console.log('Counter changed:', newValue);
});

// List available state keys (discovers what's in state-manager nodes)
const keys = await state.keys();
// Returns: ['counter', 'items', 'userPreferences', ...]
```

**How `state.keys()` works**: The host reads all state-manager nodes in the workflow and returns their keys. This is how a component discovers available state without hardcoding key names.

**How `state.update()` works**:
1. SDK sends `state:get` → host reads current value from state-manager node
2. SDK runs the updater function locally with the current value
3. SDK sends `state:set` with the new value → host writes to state-manager node
4. Not atomic (no server-side CAS), but safe for single-user UI interactions

**Scoping**: If the workflow has multiple state-manager nodes, the SDK operates on the one connected to (or nearest to) the custom component node. An optional `nodeId` parameter allows targeting a specific state-manager node:
```typescript
await state.get('key', { node: 'specific-state-manager-id' });
```

### 5. Credentials

```typescript
import { auth } from '@noclick/sdk';

// Check if a credential is available
const hasGoogle = await auth.hasCredential('google_oauth');

// Trigger OAuth flow (opens popup, resolves when complete)
const credential = await auth.requestCredential('google_oauth');
// credential = { id, type, name } or null if user cancelled

// List available credentials
const creds = await auth.listCredentials();

// Create a non-OAuth credential (API key, token, etc.)
// The component renders its own input UI, then calls this to save:
const cred = await auth.createCredential('telegram_bot_token', {
  token: apiKey
}, 'My Telegram Bot');
// cred = { id, type, name }
```

### 6. Workflow Info

```typescript
import { workflow } from '@noclick/sdk';

// Get info about the current workflow
const info = await workflow.getInfo();
// { id, name, nodeCount }

// Get this component's own node ID
const myId = workflow.nodeId;
```

---

## Message Protocol

All SDK ↔ host communication uses `postMessage` with a typed envelope:

```typescript
// SDK → Host (request)
{
  type: 'noclick:request',
  id: 'req-1',         // unique request ID for response correlation
  method: string,       // e.g. 'nodes.getOutput', 'execution.runNodesAndGetOutput', 'state.get'
  params: object,       // method-specific parameters
}

// Host → SDK (response, for request/response methods)
{
  type: 'noclick:response',
  id: 'req-1',         // matches request ID
  result?: any,         // success payload
  error?: string,       // error message (mutually exclusive with result)
}

// Host → SDK (stream event, for runNodesAndGetOutput)
{
  type: 'noclick:stream',
  id: 'req-1',         // matches the originating request ID
  event: 'output' | 'error' | 'done',
  nodeId?: string,      // which node this event is for
  data?: any,           // output data or error message
}

// Host → SDK (push event, no request ID — subscriptions)
{
  type: 'noclick:event',
  event: string,        // e.g. 'inputs:changed', 'node:state', 'node:output', 'state:changed'
  data: object,
}
```

---

## Host Implementation (HtmlReactBlock)

The `HtmlReactBlock` component listens for `message` events from the iframe and translates them:

| SDK Method | Host Action |
|---|---|
| `nodes.getOutput(id)` | Read from `node.data.output` via ReactFlow state |
| `nodes.setConfig(id, config)` | Call `setNodes()` to update node data |
| `nodes.list()` | Read all nodes from ReactFlow state |
| `execution.runNodesAndGetOutput(run, targets)` | Call `runSingleNode()` with exec ID, subscribe to `workflow:node:output` + `workflow:node:state` socket events, forward matching target outputs as `noclick:stream` messages to iframe |
| `execution.runNodesInBackground(ids)` | Call `runSingleNode()`, no output tracking |
| `execution.onNodeState(id)` | Subscribe to `workflow:node:state` socket events, forward matching ones |
| `execution.onNodeOutput(id)` | Subscribe to `workflow:node:output` socket events, forward matching ones |
| `state.get(key)` | Read from connected state-manager node's data |
| `state.set(key, value)` | Update state-manager node's data + trigger save |
| `state.keys()` | Enumerate all state-manager nodes, collect their keys |
| `auth.requestCredential(type)` | Open OAuth popup via existing credential flow |
| `auth.hasCredential(type)` | Check credential store for matching type |

The host maintains a map of pending request IDs → Promise resolvers / stream handlers. When data arrives from the socket layer, it posts the response back to the iframe.

---

## Execution ID Flow (Stale Output Prevention)

```
Component                    Host                         Backend
    |                          |                              |
    |-- runNodesAndGetOutput   |                              |
    |   (req-id: req-42)       |                              |
    |   run: ['fetcher']       |-- generate exec-id: ex-7 --> |
    |   targets: ['chart']     |-- WorkflowExecuteRequest --> |
    |                          |   (with exec-id: ex-7)       |
    |                          |                              |
    |                          | <-- node:output (ex-7) ------|
    |                          |   node: 'chart'              |
    |                          |   match exec-id + target     |
    | <-- stream:output -------|                              |
    |   { nodeId: 'chart',     |                              |
    |     data: { ... } }      |                              |
    |                          | <-- node:state (ex-7) -------|
    |                          |   node: 'chart' → completed  |
    |                          |   all targets done            |
    | <-- stream:done ---------|                              |
```

`nodes.getOutput()` bypasses this entirely — it reads whatever output is currently on the node, from any execution.

---

## Discovery: How Components Find Data

**Problem**: A workflow has many nodes with different types, outputs, and state. How does a component know what's available?

**Solution**: Three levels of discovery:

1. **Edges (implicit)**: Data from upstream nodes arrives automatically via `useInputs()`. The component developer wires edges in the canvas — no IDs needed in code.

2. **Listing (explicit)**: `nodes.list()` returns all nodes with their types and labels. `state.keys()` returns all state keys. The component can build dynamic UIs from these.

3. **Convention (agreed)**: For complex dashboards, the component developer and workflow builder agree on node labels or state keys. The component uses `nodes.list()` to find nodes by label rather than hardcoding IDs.

Example — a dashboard that auto-discovers data sources:
```typescript
function Dashboard() {
  const [dataSources, setDataSources] = useState([]);

  useEffect(() => {
    async function discover() {
      const allNodes = await nodes.list();
      // Find all nodes that have output (they've been run)
      const sources = allNodes.filter(n => n.hasOutput);
      const outputs = await Promise.all(
        sources.map(async n => ({
          label: n.label,
          data: await nodes.getOutput(n.id)
        }))
      );
      setDataSources(outputs);
    }
    discover();
  }, []);

  return dataSources.map(s => <DataCard label={s.label} data={s.data} />);
}
```

---

## State Editing Patterns

**Simple set** (overwrite):
```typescript
await state.set('theme', 'dark');
```

**Append to list**:
```typescript
await state.update('notifications', (list) => [...(list || []), newNotification]);
```

**Edit nested object**:
```typescript
await state.update('userProfile', (profile) => ({
  ...profile,
  preferences: { ...profile.preferences, language: 'fr' }
}));
```

**Increment counter**:
```typescript
await state.update('viewCount', (n) => (n || 0) + 1);
```

**Remove from list**:
```typescript
await state.update('cart', (items) => items.filter(i => i.id !== removeId));
```

All of these use the same `update()` primitive: read current value, apply function, write back. The function runs in the iframe (not on the server), so any JavaScript logic works.

---

## Storage

Three storage tiers, each with a dedicated SDK namespace:

### Key-Value State (`state`)
Simple JSON values via state-manager nodes. See section 4 above.

### Blob/File Resources (`resources`)

Files, images, documents stored in R2. The SDK handles the two-step upload flow (create resource → PUT to presigned URL).

```typescript
import { resources } from '@noclick/sdk';

// Upload a file
const { resourceId, uploadUrl } = await resources.upload('report.pdf', 'application/pdf', file.size);
await fetch(uploadUrl, { method: 'PUT', body: file });

// Get a download URL
const url = await resources.getUrl(resourceId);

// List resources in the workflow
const files = await resources.list('file');

// Delete a resource
await resources.remove(resourceId);
```

### Tabular Data (`dataset`)

Structured rows with CRUD operations, stored in `dataset_rows` table. Scalable for large datasets.

```typescript
import { dataset } from '@noclick/sdk';

// Read rows (paginated)
const page = await dataset.getRows(resourceId, { offset: 0, limit: 100 });
// page = { rows: [{ id, data, created_at, updated_at }, ...], totalCount: 1000 }

// Append rows
await dataset.appendRows(resourceId, [
  { name: 'Alice', score: 95 },
  { name: 'Bob', score: 87 },
]);

// Update a row
await dataset.updateRow(resourceId, rowId, { score: 98 });

// Delete rows
await dataset.deleteRows(resourceId, [rowId1, rowId2]);
```

**Note**: Both `resources` and `dataset` operate on resource IDs (UUIDs), not node IDs. A resource is created either by the SDK (`resources.upload`) or by interface blocks (file-upload, dataframe). The resource ID is stored on the node's config/output and can be discovered via `nodes.getOutput()`.

---

## Credentials & OAuth

Components may need to trigger authentication flows — for example, a dashboard that connects to a user's Google account.

```typescript
import { auth } from '@noclick/sdk';

// Check what's available
const creds = await auth.listCredentials();
// [{ id, type: 'google_oauth', name: 'My Google Account' }, ...]

// Check a specific type
const hasGoogle = await auth.hasCredential('google_oauth');

// Trigger OAuth (opens popup managed by the host)
const credential = await auth.requestCredential('google_oauth');
// Resolves when popup closes:
// - { id, type, name } on success
// - null if user cancelled
```

**How it works**: The host opens the standard NoClick credential popup (same one used in node config). The iframe SDK can't open popups directly (sandbox restriction). The host mediates the flow:

1. SDK sends `auth.requestCredential` request via postMessage
2. Host opens the OAuth popup via the existing credential system
3. On popup close, host posts the result back to the iframe
4. SDK resolves the promise

**Security**: The SDK can only trigger credential flows for types that exist in the workflow's node configs. It cannot access credential secrets — only the credential ID and metadata. The actual tokens are used server-side by nodes during execution.

---

## What the SDK Does NOT Do

- **Direct database access**: No SQL queries, no R2 file operations. Use nodes for that.
- **Server-side computation**: The SDK triggers node execution — the node does the work.
- **Cross-workflow communication**: SDK is scoped to the workflow the component belongs to.
- **Persistent connections**: No long-lived WebSocket from iframe. All communication is request/response via postMessage. Push events (node state, output streaming) are forwarded by the host.
- **Credential secret access**: SDK gets credential IDs and metadata, never tokens or secrets.
