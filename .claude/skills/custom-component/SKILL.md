---
name: Custom Component Builder
description: Build custom React/JSX interface components with the @noclick/sdk. Use when the user asks to create a custom component, build an interface, create a dashboard, add a custom UI, use the SDK, or mentions component, interface-html-react, jsx_source, fullscreen component, or @noclick/sdk.
---

# Custom Component Builder

This skill guides you through creating custom React/JSX components that run inside NoClick workflows, with full access to workflow data, execution, state, credentials, and storage via the `@noclick/sdk`.

## Architecture Overview

Custom components are React apps rendered in sandboxed iframes. The flow:

1. **JSX source** stored in node config (`jsx_source` field, code editor widget)
2. **Backend transpilation** via Sucrase (QuickJS) → produces browser-ready JS
3. **Import map** auto-generated with React 19 (esm.sh), Tailwind CDN, npm packages, and `@noclick/sdk` (base64 data URI)
4. **srcdoc** assembled into complete HTML document → rendered in iframe
5. **SDK bridge** (`useSDKBridge` hook) translates `postMessage` calls from iframe to NoClick actions

## Security model (opaque-origin capability)

Component `srcdoc` runs with `allow-scripts` but **never** `allow-same-origin`. The
browser therefore gives author code an opaque origin: it can render and use the SDK's
`postMessage` transport, but it cannot read `window.parent` DOM, host globals,
cookies, local storage, or the Supabase session. Public/read-only components receive
no popup or top-navigation sandbox capabilities. Public interface embeds mount no SDK
bridge; read-only canvas/replay bridges expose only allowlisted reads from their
host-provided graph snapshot and never call credentials, resources, or mutations.

The host verifies every bridge message comes from that component's `contentWindow`.
Node reads, config writes, state access, and execution targets are resolved against
the current mounted workflow graph before any mutation or backend dispatch; guessed,
stale, collaborator-only, and cross-workflow node IDs are rejected. Read-only bridge
contexts use an explicit method allowlist so a newly added SDK method cannot become a
public data channel by default. Do not re-add `allow-same-origin`, host-DOM access, or
an unscoped node-targeting method.

## Key Files

| File | Purpose |
|------|---------|
| `backend/nodes/interface/component_node.py` | Backend node: stores JSX, transpiles on execute |
| `backend/utils/jsx_transpiler.py` | Sucrase transpilation, import map generation, srcdoc assembly |
| `backend/utils/sucrase_bundle.js` | Pre-built Sucrase for QuickJS (~295KB) |
| `sdk/typescript/src/core/` | SDK TypeScript source (transport, nodes, execution, state, auth, resources, dataset) |
| `sdk/typescript/src/transports/` | Transport implementations (postmessage.ts; websocket.ts future) |
| `sdk/typescript/src/react.ts` | React hooks (useInputs, onInputsChanged) — optional peer dep |
| `sdk/typescript/dist/sdk.esm.js` | Built SDK ES module (~11KB), injected as base64 data URI |
| `sdk/typescript/build.js` | esbuild script to bundle SDK |
| `sdk/python/` | Python SDK placeholder (future WebSocket transport) |
| `frontend/app/hooks/useSDKBridge.ts` | Host-side bridge: postMessage → NoClick actions |
| `frontend/app/components/interface/blocks/HtmlReactBlock.tsx` | Iframe renderer with SDK bridge + OAuth + srcdoc cache |
| `frontend/app/components/interface/WorkflowInterface.tsx` | Grid + fullscreen tab layout with draggable tabs |

## Creating a Custom Component

### Step 1: Add the node

Via MCP:
```xml
<add_node type="interface-html-react" name="my-ui" label="My Dashboard" />
<update_config id="my-ui" operation="jsx" fullscreen="true" />
```

Or drag "Custom Component" from the UX panel in the Interface tab.

### Step 2: Set JSX source

Use the `field="jsx_source"` body syntax to avoid XML escaping of JSX angle brackets:

```xml
<update_config id="my-ui" field="jsx_source">
import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

function App() {
  const [count, setCount] = useState(0);
  return (
    &lt;div className="p-4"&gt;
      &lt;button onClick={() =&gt; setCount(c =&gt; c + 1)}&gt;Count: {count}&lt;/button&gt;
    &lt;/div&gt;
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(&lt;App /&gt;);
</update_config>
```

**Important**: The XML parser's `html.unescape()` converts `&lt;` → `<` and `&gt;` → `>` in body tags. Always use `&lt;` and `&gt;` for JSX angle brackets in MCP XML.

### Step 3: Run the node to transpile

```xml
<!-- Run via MCP -->
run_nodes(workflow_id, [node_id])
```

Or the component auto-transpiles when the user switches to the Interface tab.

### Step 4: Use npm packages

Just import them — the transpiler auto-detects imports and adds esm.sh URLs to the import map:

```jsx
import { BarChart, Bar, XAxis, YAxis } from 'recharts';
import { format } from 'date-fns';
```

Packages are loaded via `esm.sh` with `&bundle` (bundles transitive deps) and `?external=react,react-dom` (single React instance).

## @noclick/sdk API

### Nodes — Read/write any node's data

```jsx
import { nodes } from '@noclick/sdk';

// Read last output (may be from any previous run)
const output = await nodes.getOutput('node-id');

// Read config
const config = await nodes.getConfig('node-id');

// Set config fields
await nodes.setConfig('node-id', { url: 'https://...' });

// List all nodes
const allNodes = await nodes.list();
// [{ id, type, label, hasOutput }, ...]
```

### Execution — Run nodes and get results

```jsx
import { execution } from '@noclick/sdk';

// Fire and forget
execution.runNodesInBackground(['node-id']);

// Run with temporary config overrides (doesn't save)
execution.runNodesInBackground([
  { id: 'http-node', config: { url: userInput } }
]);

// Run and stream output as targets complete
const stream = execution.runNodesAndGetOutput(
  ['data-fetcher'],           // nodes to run
  ['chart-data', 'summary']   // nodes whose output we want
);
stream.on('output', (nodeId, data) => { ... });
stream.on('done', () => { ... });
const results = await stream.all(); // or await all at once

// Subscribe to node state changes (works for any trigger: manual, cron, webhook)
execution.onNodeState('node-id', (state) => {
  // 'idle' | 'running' | 'completed' | 'error'
});

// Subscribe to node output in real-time (e.g., cron-triggered data refresh)
execution.onNodeOutput('data-node', (output) => {
  // Fires whenever the node produces output, from any source
  setData(output);
});

// Stop execution
execution.stop();
```

### State — Persistent key-value via state-manager nodes

```jsx
import { state } from '@noclick/sdk';

const val = await state.get('counter');
await state.set('counter', 42);
await state.del('counter'); // remove key entirely
await state.update('items', (list) => [...(list || []), newItem]);
await state.update('counter', (n) => (n || 0) + 1);

const keys = await state.keys();

// Subscribe to changes (fires on set/del from any source)
state.onChange('counter', (newVal) => { ... });
```

**Requires** a `state-manager` node in the workflow. The SDK auto-finds the nearest one.

### Auth — Credentials and OAuth

```jsx
import { auth } from '@noclick/sdk';

// List credentials
const creds = await auth.listCredentials();

// Check if a type exists
const has = await auth.hasCredential('google_gmail_oauth');

// Trigger OAuth popup (scopes auto-resolved from node schemas)
const cred = await auth.requestCredential('google_gmail_oauth');
// { id, type, name } or null if cancelled

// Create API key credential (component renders its own form)
const cred = await auth.createCredential('telegram_bot_token', {
  token: apiKey
}, 'My Bot');
```

### Resources — Blob/file storage (R2)

```jsx
import { resources } from '@noclick/sdk';

// Upload a file
const { resourceId, uploadUrl } = await resources.upload(
  'report.pdf', 'application/pdf', file.size
);
await fetch(uploadUrl, { method: 'PUT', body: file });

// Get download URL
const url = await resources.getUrl(resourceId);

// List resources
const files = await resources.list('file');

// Delete
await resources.remove(resourceId);
```

### Dataset — Tabular CRUD (PostgreSQL-backed)

```jsx
import { dataset } from '@noclick/sdk';

// List existing datasets in this workflow
const datasets = await dataset.list();
// [{ id, name, rowCount }, ...]

// Create a dataset
const resourceId = await dataset.create('User Submissions');

// Append rows (schemaless JSONB — any shape)
await dataset.appendRows(resourceId, [
  { name: 'Alice', score: 95 },
  { name: 'Bob', score: 87 },
]);

// Read rows (paginated)
const page = await dataset.getRows(resourceId, { limit: 100, offset: 0 });
// { rows: [{ id, data, created_at, updated_at }], totalCount }

// Update a row
await dataset.updateRow(resourceId, rowId, { score: 98 });

// Delete rows
await dataset.deleteRows(resourceId, [rowId1, rowId2]);
```

### Workflow — Context info

```jsx
import { workflow } from '@noclick/sdk';

const info = await workflow.getInfo(); // { id, name, nodeCount }
const myNodeId = workflow.nodeId;
```

### Inputs — Reactive data from upstream nodes

```jsx
import { useInputs } from '@noclick/sdk';

function MyComponent() {
  const inputs = useInputs(); // re-renders when upstream output changes
  return <div>{JSON.stringify(inputs)}</div>;
}
```

## Node Config Fields

| Field | Type | Description |
|-------|------|-------------|
| `jsx_source` | string (code editor, jsx) | The React/JSX source code |
| `fullscreen` | enum "true"/"false" | Show as fullscreen tab vs grid block |

The `fullscreen` field uses string enum with a `field_validator` to coerce boolean → string (handles MCP XML boolean coercion).

## Fullscreen Tabs

When `fullscreen="true"`, the component renders as a full-viewport tab in the Interface view:
- Sub-tab bar appears below the main tab bar (Canvas/Interface/Logs)
- Tabs are draggable (reorderable, persisted in `InterfaceGridState.tabOrder`)
- Active tab label is inline-editable (saves to node's `label` field)
- "Default" tab shows the grid layout with non-fullscreen blocks
- Both grid and fullscreen views stay mounted (display:none when inactive) to preserve state

## srcdoc Caching

Compiled srcdoc is cached in IndexedDB (`component-cache` store):
- One slot per node ID (LLM iterations don't bloat cache)
- Keyed by `FNV-1a(jsx_source)` hash — stale cache auto-invalidated on source change
- Copied/duplicated nodes get instant cache hits via hash scan
- Cache survives page reloads — components render instantly without re-transpilation

## iframe Interaction

- `sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"`
- During canvas drag/resize, `pointer-events: none` via CSS (`.perf-optimizing iframe`, `.nc-resizing iframe`)
- ResizeObserver warnings suppressed inside srcdoc (`window.onerror`) and on parent window
- Runtime errors displayed in-iframe via `.nc-error` class

## Real-time Subscriptions

Components can subscribe to live updates from cron jobs, webhook triggers, or other users:

```jsx
import { execution, state } from '@noclick/sdk';

// React to node output changes (cron, webhook, manual run — any source)
const unsub = execution.onNodeOutput('data-node', (output) => {
  setData(output);
});

// React to node state changes
execution.onNodeState('data-node', (state) => {
  setIsRunning(state === 'running');
});

// React to state changes (from any source — other components, node executions)
state.onChange('counter', (newVal) => {
  setCounter(newVal);
});

// Cleanup
unsub(); // call returned function to unsubscribe
```

## Request Timeout

All SDK requests timeout after 30 seconds. If the host doesn't respond (method not implemented, bridge error), the promise rejects with a descriptive error:
```
SDK request 'nodes.getOutput' timed out after 30000ms
```

## SDK Build

After modifying SDK source in `sdk/typescript/src/`:
```bash
cd sdk/typescript && node build.js
```
This produces `sdk/typescript/dist/sdk.esm.js`. The backend auto-loads it via `_load_sdk_bundle()` in `jsx_transpiler.py`. The pre-commit hook auto-builds and stages the SDK bundle. Restart the backend to clear the cached bundle in memory.

## Common Patterns

### Read node output on mount, refresh on button click

```jsx
const [data, setData] = useState(null);
const [loading, setLoading] = useState(false);

async function load() {
  const output = await nodes.getOutput(NODE_ID);
  setData(output?.result || null);
}

async function refresh() {
  setLoading(true);
  execution.runNodesInBackground([NODE_ID]);
  // Poll for new output
  const oldTimestamp = data?.timestamp;
  for (let i = 0; i < 15; i++) {
    await new Promise(r => setTimeout(r, 500));
    const output = await nodes.getOutput(NODE_ID);
    if (output?.result?.timestamp !== oldTimestamp) {
      setData(output.result);
      setLoading(false);
      return;
    }
  }
  setLoading(false);
}

useEffect(() => { load(); }, []);
```

### CRUD with dataset

```jsx
const [dsId, setDsId] = useState(null);
const [rows, setRows] = useState([]);

async function init() {
  const id = await dataset.create('My Data');
  setDsId(id);
}

async function addRow(data) {
  await dataset.appendRows(dsId, [data]);
  const page = await dataset.getRows(dsId);
  setRows(page.rows);
}

async function removeRow(rowId) {
  await dataset.deleteRows(dsId, [rowId]);
  const page = await dataset.getRows(dsId);
  setRows(page.rows);
}
```

### OAuth + API call

```jsx
async function connectGmail() {
  const has = await auth.hasCredential('google_gmail_oauth');
  if (!has) {
    await auth.requestCredential('google_gmail_oauth');
  }
  // Now run a Gmail node that uses the credential
  execution.runNodesInBackground([GMAIL_NODE_ID]);
}
```

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `&lt;` in stored JSX | MCP XML escaping | Use `field="jsx_source"` body syntax; `html.unescape()` in `workflow_xml.py` handles it |
| `{{ }}` in JSX stripped | Reference resolver treats as node reference | Fixed: unresolvable `{{ }}` preserved as-is |
| Gray iframe | esm.sh cold start (3-5s) or runtime error | Check `.nc-error` display in iframe; ensure `&bundle` on esm.sh URLs |
| Drag stuck on canvas | iframe captures mouse events | CSS `.perf-optimizing iframe { pointer-events: none }` |
| `nodes.getOutput` returns null | Not on canvas tab, ReactFlow instance empty | Fixed: `__workflowTest.getNodes()` used as primary accessor |
| `state.set` doesn't persist | `setNodes` not working off canvas | Fixed: `updateNodeData` via `__workflowTest` |
| SDK module not found | SDK bundle not rebuilt | `cd sdk && node build.js`, restart backend |
| Boolean `fullscreen` rejected by Pydantic | MCP sends boolean, field expects string | `field_validator` coerces boolean → string |
