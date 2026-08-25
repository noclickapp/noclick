---
name: Workflow Runtime Debug
description: Debug workflow runtime behavior and test frontend features using the nc MCP bridge. Use when debugging workflow execution, testing UI components, inspecting DOM/state, writing frontend tests, or when user mentions nc_eval, nc_run_test, nc bridge, __workflowTest, test harness, or runtime debugging.
allowed-tools: Read, Bash, Glob, Grep
---

# Workflow Runtime Debug

Debug and test frontend behavior using the nc MCP bridge — a zero-polling system that executes JavaScript in the user's actual browser session via Vite's HMR WebSocket.

## Tools

| Tool | Purpose |
|------|---------|
| `mcp__nc__nc_eval` | Evaluate a JS expression in the browser |
| `mcp__nc__nc_run_test` | Run a `.ts` test file in the browser |

## Architecture

```
Claude Code tool call → MCP Server (scripts/nc-mcp-server.mjs)
  → HTTP POST /__nc → Vite Plugin (vite-plugin.ts)
  → HMR WebSocket → Browser bridge (bridge.ts)
  → dynamic import + execute → result flows back
```

**Key files**:
- `frontend/app/lib/nc/vite-plugin.ts` — Vite plugin: `/__nc` middleware + HMR relay
- `frontend/app/lib/nc/bridge.ts` — Browser HMR listener, runs tests via dynamic import
- `frontend/app/lib/nc/index.ts` — Reusable helper library (`nc.dom`, `nc.ui`, `nc.nodes`, etc.)
- `scripts/nc-mcp-server.mjs` — MCP server exposing `nc_eval` and `nc_run_test`
- `frontend/tests/nc/` — Test files

## Quick Examples

```
nc_eval({ expression: "document.title" })
nc_eval({ expression: "window.__workflowTest.getNodes().length" })
nc_run_test({ file: "tests/nc/example.test.ts" })
```

## Writing Test Files

Test files live in `frontend/tests/nc/`, export a default async function, and import helpers from `~/lib/nc`:

```ts
import { nc } from '~/lib/nc';

export default async function () {
  // Setup
  nc.ui.clickTab('Interface');
  await nc.wait.forElement('[data-block-type="config-form"]');

  // Act
  nc.dom.type('input[placeholder="Add item..."]', 'test');
  nc.dom.pressKey('input[placeholder="Add item..."]', 'Enter');
  await nc.wait.ms(200);

  // Assert
  const text = nc.dom.getText('.list-item');
  nc.assert.equal(text, 'test', 'Item should appear in list');
  return { success: true };
}
```

## Helper Library (`nc`)

| Namespace | Functions | Access Method |
|-----------|----------|---------------|
| `nc.dom` | `qs()`, `qsa()`, `click()`, `type()`, `getText()`, `pressKey()`, `focus()` | `document.querySelector` |
| `nc.ui` | `clickTab(name)`, `getActiveTab()` | DOM queries on tab buttons |
| `nc.nodes` | `list()`, `count()`, `get(id)`, `getOutput(id)`, `run(id)`, `workflowId()` | `window.__workflowTest` |
| `nc.state` | `local(path)`, `cached(path)`, `raw()`, `rawCached()` | Valtio imports |
| `nc.socket` | `send(event)` | `__workflowTest.sendEvent()` |
| `nc.assert` | `equal()`, `deepEqual()`, `truthy()`, `falsy()`, `includes()`, `gt()` | Throws on failure |
| `nc.wait` | `ms()`, `until(fn, timeout)`, `forElement(selector, timeout)` | In-browser waits |

## Adding Reusable Helpers

Add new helpers to `frontend/app/lib/nc/index.ts`. Factor common test patterns into the library so future tests are faster:

```ts
// Example: add a helper to get interface block values
const blocks = {
  getFormValues(blockSelector: string): Record<string, unknown> {
    // ... implementation using nc.dom
  },
};
```

## Debugging Common Issues

**Timeout (3s for eval, 10s for tests)**:
- Ensure `npm run dev` is running and a browser tab is open at localhost:5173
- Check that the nc MCP server is running (`/mcp` in Claude Code)

**Module import errors in tests**:
- Test files must use `~/` imports (resolved by Vite's tsconfigPaths plugin)
- Files outside `frontend/app/` can still use `~/` — Vite resolves it at serve time
