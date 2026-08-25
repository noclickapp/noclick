# CLAUDE.md

Guidance for coding agents (and humans) working in this repository.
`AGENTS.md` is a symlink to this file.

## What this is

NoClick is a workflow automation platform: a visual canvas of nodes, executed on
triggers (webhooks, schedules, inbound email, chat messages), with an AI agent
node that can drive real coding CLIs and call your connected integrations as
tools.

## Layout

| Path | What lives there |
|---|---|
| `backend/nodes/` | Every integration node. One module per service; config is a Pydantic model |
| `backend/nodes/core/` | Node base class, registry, credential resolution, operation dispatch |
| `backend/wss/` | Socket.IO layer — `handlers/` (business logic), `sender/` (typed events), `receiver/` (routing) |
| `backend/coder/workflow/` | The XML workflow DSL, `GraphState`, and the AI builder |
| `backend/utils/` | Shared services: webhooks, credentials, storage, relay, cron, email |
| `backend/repositories/` | SQL lives here, one module per domain — not inline in handlers |
| `frontend/app/` | Remix + Vite: ReactFlow canvas, generated config panels, interface builder |
| `frontend/app/schemas/nodes/` | **Generated** JSON Schema per node — never edit by hand |
| `infra/supabase/` | Database migrations |
| `sdk/` | TypeScript + Python SDKs for embedding workflows |

## Commands

```bash
make local                              # whole stack: Supabase + backend + frontend

cd backend && python server.py          # backend alone
cd backend && pytest                    # backend tests

cd frontend && npm run dev              # frontend alone
cd frontend && npx vitest run tests/    # frontend tests
cd frontend && npm run lint

cd infra && supabase migration up --local          # apply migrations
cd infra && supabase db diff -f <name>             # create one
```

## The one thing to understand first: schemas are generated

Node config UIs are rendered from JSON Schema derived from the backend's
Pydantic models. `frontend/app/schemas/nodes/*.json` is **build output** —
editing it by hand is always wrong. Regenerate with:

```bash
cd backend && python scripts/generate_socket_types.py
```

It reads `NODE_REGISTRY` (`backend/nodes/core/registry.py`) and calls
`get_config_schema()` on each node class. Register a node there and its editor
UI appears; you do not write React for it.

### Schema extensions

The renderer (`frontend/app/components/workflow/NodeConfig.tsx`) understands
these keys in a field's `json_schema_extra`:

| Key | Effect |
|---|---|
| `enum` + `enumNames` | Renders a `<select>` |
| `x-enum-searchable` | Renders a searchable combobox instead |
| `x-dynamic-options` | Options loaded from the backend at runtime (e.g. "list my Slack channels") |
| `x-keywords` | Search synonyms so intent queries find the operation |
| `x-credential-type` / `x-oauth-provider` / `x-oauth-scopes` | Credential + OAuth metadata |
| `ui:widget` | Override the renderer (`code_editor`, `schedule`, `password`, …) |
| `ui:hidden`, `ui:category`, `ui:help`, `ui:placeholder`, `ui:rows` | Layout and copy |

**Not every JSON Schema type has a good renderer.** `"type": "boolean"` falls
through to a plain text input with no drag-and-drop. Use a string enum instead:

```python
my_flag: str = Field("false", json_schema_extra={
    "enum": ["true", "false"],
    "enumNames": ["Yes", "No"],
    "x-enum-searchable": True,
})
# compare with: if config.my_flag == "true"
```

`Optional[Literal[...]]` needs no extras — the enum is hoisted to the top level
automatically and renders as a searchable dropdown.

## Config parsing and validation share one lens

`runtime_config_view` (`backend/nodes/core/base.py`) normalizes a raw config
before anything reads it: `""` → `None`, string coercions, and unset markers
dropped so Pydantic applies defaults. **Both** `parse_config` and every
validator judge that same view, so a build-time verdict can't disagree with
run-time behaviour. Never validate a node config against the raw dict.

## Socket events are typed end to end

Events are Pydantic models in `backend/wss/sender/events.py`, routed in
`backend/wss/receiver/event_routing.py`, handled in `backend/wss/handlers/`.
The generator emits matching TypeScript.

```python
# Good — typed model through the sender
await send_event(self.sio, sid, ResponseEvent(request_id=req.request_id, data=payload))

# Never do this
await self.sio.emit('response', data, to=sid)
```

## Frontend conventions

- **Node data model**: config fields live at `node.data.config.fieldName`
  (authoritative). Top-level `node.data` holds metadata (`label`, `operation`,
  `credentialIds`, …) and runtime state (`output`, `executionState`). Read
  `node.data.config.x`, never a flat `node.data.x`.
- **All node mutations go through `frontend/app/lib/applyNodeUpdate.ts`** —
  `createWorkflowNode`, `applyNodeUpdate`, `updateNodeInList`. Don't hand-roll
  `setNodes(ns => ns.map(...))`; the shape is enforced in one place.
- **State**: `useCachedValtioState` for data that should persist, `useValtioState`
  for session-only state.
- **Theming**: semantic tokens in `frontend/app/tailwind.css` are the only source
  of truth. Use `bg-background` / `bg-card` / `text-muted-foreground` /
  `border-border`, never raw zinc or hex. Dark is the default; only `/dashboard`
  is theme-switchable.
- Absolute imports with the `~/` prefix.

## Editions

This repository runs in two shapes, keyed on `NOCLICK_LOCAL=1`
(`backend/utils/edition.py`, mirrored for the UI in `frontend/app/lib/edition.ts`).
Self-hosted replaces the hosted infrastructure in-process, through registries
rather than branches:

| Seam | Self-hosted implementation |
|---|---|
| `utils/execution_relay.py` | In-process relay + WebSocket routes, instead of an external service |
| `utils/local_cron.py` | Asyncio ticker serving the same scheduler REST API |
| `nodes/core/code_runtime.py` | Serverless-function nodes run in a cached local venv |
| `utils/volume_backend.py` | Named volumes are directories under `~/.noclick/volumes/` |
| `nodes/agent/harness_registry.py` | Agent turns run your installed CLI as a subprocess |

### Agent workspace files

`backend/utils/agent_workspace.py` is the shared file-listing and capability
layer. `agent_workspace:list` resolves the workspace from the stored graph: a
`FilesystemNode` wired into the agent supplies the volume; otherwise the
conversation uses its per-conversation local volume. It returns signed,
per-file read URLs and, for users with `EDIT` or `OWNER` permission, a separate
short-lived upload URL. Reads use `GET /agent/workspace/file?token=…`; uploads
use `POST /agent/workspace/upload?token=…&path=…`. Read tokens never authorize
writes, paths are constrained to the volume root, and uploads are limited to
50 MB. Both routes go through `utils.volume_backend`, so the self-hosted
implementation reads and writes named directories under `~/.noclick/volumes/`.

Frontend uploads go through
`frontend/app/hooks/useAgentWorkspaceFiles.ts` (`uploadWorkspaceFiles`), shared
by `WorkspaceFilesPanel` and `FileBrowserWidget`. Keep coverage in
`backend/tests/test_agent_workspace.py`,
`frontend/tests/hooks/useAgentWorkspaceFiles.test.ts`, and
`frontend/tests/nc/agent-workspace-files.test.ts`.

When adding something that needs infrastructure, add it as a registry with a
local implementation — not an `if is_local_edition()` branch at the call site.

**Endpoints belong in one module per side**: `backend/utils/hosted_defaults.py`
and `frontend/app/lib/hostedDefaults.ts`. A hardcoded hostname elsewhere fails
`backend/tests/test_no_hosted_endpoints.py`.

## Testing

- `pytest` for the backend, `vitest` for the frontend.
- **Never edit a test to work around not understanding the code.** Investigate
  first, then fix the code or update the test deliberately.
- **Replace assertions, don't delete them.** If an assertion no longer fits,
  verify the same behaviour a different way.
- Tests must exercise real behaviour, not mock behaviour. A test that only
  proves a mock was called is worth deleting.

## Code style

- **No fallbacks.** If something can't work, fail loudly. Silent degradation
  hides bugs — a default that "happens to work" is how a broken config reaches
  production looking healthy.
- **Reuse before adding.** Read the existing helper and generalize it rather
  than writing a near-duplicate. Check for an existing function before adding one.
- **Comment the why**, not the what. One line beating a paragraph. Don't narrate
  the diff or leave changelog notes in comments.
- Write code that matches its neighbours in naming, density, and idiom.
- TypeScript strictly — no implicit `any`.
- Reusable frontend logic goes in `frontend/app/hooks/`, not inline in a component.
- Use `pnpm` for frontend dependencies.

## What isn't here

Some things that run on NoClick Cloud aren't part of this repository: the warm
agent-sandbox runtime, additional hosted builder capabilities, billing, published-app
hosting, and the managed email/edge infrastructure. Where those are absent the
code says so rather than failing obscurely — see `docs/self-hosting.md` for what
that changes in practice. Agent turns still run, the builder still builds, and
every integration still works.
