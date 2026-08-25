# @noclick/sdk documentation resources.
# Auto-discovered by the resources package.

PROMPTS = [
    {
        "name": "build_custom_interface",
        "description": (
            "Complete guide for building custom React/JSX interface components with @noclick/sdk. "
            "Use this when asked to create a custom UI, dashboard, interactive component, "
            "or any interface that goes beyond the built-in blocks."
        ),
        "resource": "sdk",
    },
]

RESOURCES = [
    {
        "name": "sdk",
        "title": "Custom Component SDK Reference",
        "content": """\
# @noclick/sdk — Custom Component SDK

## Overview

Build custom interface components that interact with NoClick workflows.
Two modes available via the `interface-html-react` node:
- **operation='render_html_interface'**: Raw HTML/JS — write vanilla JS with SDK access. npm packages auto-resolve via import maps.
- **operation='render_jsx_react_interface'**: React/JSX — Sucrase transpilation, Tailwind CSS, auto npm resolution. Set `jsx_source`.

Both modes run in sandboxed iframes with `@noclick/sdk` for workflow data, execution,
state, credentials, file storage, and datasets. Any npm package can be imported
directly (auto-resolved via esm.sh — no install step needed).

## Creating a Component

1. Add node: `interface-html-react` type
2. Set `operation="render_jsx_react_interface"` for React or `operation="render_html_interface"` for vanilla HTML/JS
3. Set `fullscreen="true"` for full-viewport tab rendering
4. For JSX: set `jsx_source` — must import React + ReactDOM, render to `document.getElementById('root')`
5. For HTML: set `content` — use `<script type="module">` for imports

## SDK API

All imports from `@noclick/sdk`:

### nodes — Read/write any node
```js
const output = await nodes.getOutput('node-id');     // last output (any previous run)
const config = await nodes.getConfig('node-id');      // config fields
await nodes.setConfig('node-id', { field: 'value' }); // merge config
const all = await nodes.list();                        // [{ id, type, label, hasOutput }]
```

### execution — Run nodes and track results
```js
// Fire and forget
execution.runNodesInBackground(['node-id']);
// With temporary config overrides (doesn't save to node)
execution.runNodesInBackground([{ id: 'node-id', config: { url: input } }]);

// Run and stream output as targets complete
const stream = execution.runNodesAndGetOutput(['run-id'], ['target-id']);
stream.on('output', (nodeId, data) => { /* render incrementally */ });
stream.on('error', (nodeId, error) => { /* handle error */ });
stream.on('done', () => { /* all targets done */ });
const results = await stream.all(); // { 'target-id': output }

// Real-time subscriptions (fires on cron, webhook, manual — any execution source)
const unsub = execution.onNodeOutput('node-id', (output) => { });
execution.onNodeState('node-id', (state) => { }); // 'running'|'completed'|'error'

execution.stop(); // stop current execution
```

### state — Persistent key-value (requires state-manager node in workflow)
```js
const val = await state.get('key');
await state.set('key', 42);
await state.del('key');
await state.update('items', (list) => [...(list || []), newItem]); // read-modify-write
const keys = await state.keys();
state.onChange('key', (newVal) => { }); // subscribe to changes
```

### auth — Credentials & OAuth
```js
const creds = await auth.listCredentials();   // [{ id, type, name }]
const has = await auth.hasCredential('google_gmail_oauth');
// OAuth popup (scopes auto-resolved from node schemas)
const cred = await auth.requestCredential('google_gmail_oauth');
// Non-OAuth (API keys) — component renders its own form
const cred = await auth.createCredential('telegram_bot_token', { token: '...' }, 'My Bot');
```

### resources — Blob/file storage (R2)
```js
// Upload: create resource → PUT to presigned URL
const { resourceId, uploadUrl } = await resources.upload('file.pdf', 'application/pdf', size);
await fetch(uploadUrl, { method: 'PUT', body: fileBlob });

const url = await resources.getUrl(resourceId); // presigned download URL
const files = await resources.list('file');       // list by type
await resources.remove(resourceId);               // delete
```

### dataset — Tabular CRUD (PostgreSQL-backed, schemaless JSONB rows)
```js
const datasets = await dataset.list();              // [{ id, name, rowCount }]
const id = await dataset.create('My Table');
await dataset.appendRows(id, [{ name: 'Alice', score: 95 }]);
const page = await dataset.getRows(id, { limit: 100, offset: 0 });
// page = { rows: [{ id, data, created_at, updated_at }], totalCount }
await dataset.updateRow(id, rowId, { score: 98 });
await dataset.deleteRows(id, [rowId1, rowId2]);
```

### workflow — Context
```js
const info = await workflow.getInfo(); // { id, name, nodeCount }
const myId = workflow.nodeId;          // this component's node ID
```

### inputs — Reactive upstream data
```js
import { useInputs } from '@noclick/sdk';     // React hook
const inputs = useInputs();                     // re-renders on upstream change

import { onInputsChanged } from '@noclick/sdk'; // callback alternative
onInputsChanged((inputs) => { });
```

## npm Packages

Import any npm package — auto-resolved via esm.sh with bundled dependencies:
```js
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { format } from 'date-fns';
import { motion } from 'framer-motion';
```

## Styling

Tailwind CSS available by default. Use dark theme classes with zinc/neutral palette — NO blue or indigo:
```jsx
<div className="min-h-screen bg-zinc-950 text-white p-8">
  <button className="px-4 py-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-sm text-white">
    Click me
  </button>
</div>
```

## Common Patterns

### Load cached data, refresh on demand
```js
async function load() {
  const output = await nodes.getOutput(NODE_ID);
  setData(output?.result);
}
async function refresh() {
  execution.runNodesInBackground([NODE_ID]);
  // Poll for new output by comparing timestamps
  for (let i = 0; i < 15; i++) {
    await new Promise(r => setTimeout(r, 500));
    const output = await nodes.getOutput(NODE_ID);
    if (output?.result?.timestamp !== oldTs) { setData(output.result); break; }
  }
}
```

### Real-time updates (cron/webhook)
```js
useEffect(() => {
  const unsub = execution.onNodeOutput('data-node', setData);
  return unsub;
}, []);
```

### CRUD with dataset
```js
const id = await dataset.create('Submissions');
await dataset.appendRows(id, [{ name, email }]);
const page = await dataset.getRows(id);
setRows(page.rows);
```

## Important Notes

- Use FULL node IDs (e.g., `automation-gmail-1773835867399-a6ed56`), not aliases
- All SDK requests timeout after 30 seconds
- `state` requires a `state-manager` node in the workflow
- `resources` and `dataset` are scoped to the current workflow
- OAuth scopes are auto-resolved from node JSON schemas — no need to specify manually

""",
    },
    {
        "name": "sdk-nodes",
        "title": "SDK: nodes namespace",
        "content": """\
# nodes — Read/write any workflow node

```js
import { nodes } from '@noclick/sdk';
```

## nodes.getOutput(nodeId: string): Promise<any>
Read a node's last execution output. Returns whatever exists — may be from a manual run,
cron trigger, webhook, or any previous execution. Returns null if never executed.

## nodes.getConfig(nodeId: string): Promise<Record<string, any>>
Read a node's configuration fields (excludes internal fields like output, executionState).

## nodes.setConfig(nodeId: string, config: Record<string, any>): Promise<void>
Merge config fields into a node. Does not overwrite unspecified fields.

## nodes.list(): Promise<NodeInfo[]>
List all nodes in the workflow.
Returns: `[{ id: string, type: string, label: string, hasOutput: boolean }]`

""",
    },
    {
        "name": "sdk-execution",
        "title": "SDK: execution namespace",
        "content": """\
# execution — Run nodes and track results

```js
import { execution } from '@noclick/sdk';
```

## execution.runNodesInBackground(nodes: NodeRef[]): void
Fire and forget. Accepts string IDs or `{ id, config }` objects with temporary overrides.
Config overrides are applied only for that execution — the node's saved config is unchanged.

## execution.runNodesAndGetOutput(runNodes: NodeRef[], targetNodes: string[]): ExecutionStream
Run nodes and stream output as each target node completes.
- `stream.on('output', (nodeId, data) => {})` — fires per target
- `stream.on('error', (nodeId, error) => {})` — fires on target error
- `stream.on('done', () => {})` — all targets completed
- `await stream.all()` — returns `{ [nodeId]: output }` when all done

## execution.onNodeOutput(nodeId: string, handler: (output) => void): () => void
Subscribe to a node's output in real-time. Fires whenever the node produces output from
ANY source — manual run, cron, webhook, another component. Returns unsubscribe function.

## execution.onNodeState(nodeId: string, handler: (state) => void): () => void
Subscribe to node state changes: 'idle' | 'running' | 'completed' | 'error'.

## execution.stop(): Promise<void>
Stop the currently running workflow execution.

## NodeRef type
`string | { id: string, config: Record<string, any> }`

""",
    },
    {
        "name": "sdk-state",
        "title": "SDK: state namespace",
        "content": """\
# state — Persistent key-value storage

Requires a `state-manager` node in the workflow. The SDK auto-finds the nearest one.

```js
import { state } from '@noclick/sdk';
```

## state.get<T>(key: string, options?): Promise<T | undefined>
Read a value. Returns undefined if key doesn't exist.

## state.set(key: string, value: any, options?): Promise<void>
Set a value (overwrites). Triggers onChange subscribers.

## state.del(key: string, options?): Promise<void>
Delete a key entirely. Triggers onChange subscribers with undefined.

## state.update<T>(key: string, updater: (current: T) => T, options?): Promise<void>
Read-modify-write. The updater function runs locally in the iframe, not on the server.
Example: `await state.update('count', n => (n || 0) + 1)`

## state.keys(options?): Promise<string[]>
List all available state keys across state-manager nodes.

## state.onChange<T>(key: string, handler: (newValue: T) => void): () => void
Subscribe to changes for a key. Returns unsubscribe function.

## StateOptions
`{ node?: string }` — target a specific state-manager node by ID.

""",
    },
    {
        "name": "sdk-auth",
        "title": "SDK: auth namespace",
        "content": """\
# auth — Credentials & OAuth

```js
import { auth } from '@noclick/sdk';
```

## auth.listCredentials(): Promise<CredentialInfo[]>
List all available credentials. Returns `[{ id, type, name }]`.

## auth.hasCredential(credentialType: string): Promise<boolean>
Check if a credential of the given type exists.

## auth.requestCredential(credentialType: string): Promise<CredentialInfo | null>
Trigger an OAuth flow. The host opens the OAuth popup — the SDK handles the flow.
Scopes are auto-resolved from node JSON schemas (e.g., `google_gmail_oauth` gets Gmail scopes).
Resolves with `{ id, type, name }` on success, null if cancelled.

## auth.createCredential(type: string, data: Record<string, any>, name?: string): Promise<CredentialInfo | null>
Create a non-OAuth credential (API key, token, etc.).
The component renders its own input form, then calls this to save.

""",
    },
    {
        "name": "sdk-resources",
        "title": "SDK: resources namespace (file/blob storage)",
        "content": """\
# resources — Blob/file storage (R2)

```js
import { resources } from '@noclick/sdk';
```

## resources.upload(name: string, mimeType: string, sizeBytes: number, resourceType?: string): Promise<UploadResult>
Create a resource and get a presigned upload URL.
Returns `{ resourceId: string, uploadUrl: string }`.
After calling, PUT the file body to the uploadUrl:
`await fetch(uploadUrl, { method: 'PUT', body: fileBlob })`

## resources.getUrl(resourceId: string): Promise<string>
Get a fresh presigned download URL for a resource. Persist the resource ID, not
the returned URL; self-hosted URLs expire after 15 minutes by default.

## resources.list(resourceType?: string): Promise<ResourceInfo[]>
List resources in the workflow. Optional type filter: 'file', 'image', 'dataset', etc.
Returns `[{ id, name, resourceType, mimeType, sizeBytes }]`.

## resources.remove(resourceId: string): Promise<void>
Delete a resource and its storage.

""",
    },
    {
        "name": "sdk-dataset",
        "title": "SDK: dataset namespace (tabular CRUD)",
        "content": """\
# dataset — Tabular CRUD (PostgreSQL-backed)

Rows are stored as schemaless JSONB — each row can have different fields.

```js
import { dataset } from '@noclick/sdk';
```

## dataset.list(): Promise<DatasetInfo[]>
List all datasets in the workflow. Returns `[{ id, name, rowCount }]`.

## dataset.create(name: string): Promise<string>
Create a new empty dataset. Returns the resource ID.

## dataset.getRows(resourceId: string, options?): Promise<DatasetPage>
Read paginated rows. Options: `{ limit?: number, offset?: number }`.
Returns `{ rows: DatasetRow[], totalCount: number }`.
Each row: `{ id: string, data: Record<string, any>, created_at: string, updated_at: string }`.

## dataset.appendRows(resourceId: string, rows: Record<string, any>[]): Promise<{ insertedCount: number }>
Append rows to a dataset. Each row is an arbitrary JSON object.

## dataset.updateRow(resourceId: string, rowId: string, data: Record<string, any>): Promise<void>
Update a single row's data by row UUID.

## dataset.deleteRows(resourceId: string, rowIds: string[]): Promise<{ deletedCount: number }>
Delete rows by UUIDs.

""",
    },
]
