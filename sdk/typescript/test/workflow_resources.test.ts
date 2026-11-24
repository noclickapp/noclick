// What workflows keep (their files and tables, a table's rows) and the account's own files, against the mock API:
// the routes, query parameters and headers each call sends, and what it parses.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const FILE = {
  object: "workflow_file", id: "res_f1", name: "invoice.pdf", access: "editor",
  workflow: { id: "wf_1", name: "Intake", step_types: ["trigger-webhook", "agent:codex", "automation-gmail"] },
  step_id: "upload", type: "document", mime_type: "application/pdf", size_bytes: 1024,
  url: "https://api.noclick.com/f/sealed/invoice.pdf", url_expires_at: "2026-11-19T11:00:00+00:00",
  created_at: "2026-11-19T10:00:00+00:00", updated_at: "2026-11-19T10:00:00+00:00",
};
const TABLE = {
  object: "workflow_table", id: "res_t1", name: "Orders", workflow: { id: "wf_1", name: "Intake", step_types: [] }, access: "owner",
  step_id: "table", row_count: 3, database_id: "db_1",
  created_at: "2026-11-19T10:00:00+00:00", updated_at: "2026-11-19T10:00:00+00:00",
};
const WORKFLOW = { object: "workflow", id: "wf_1", name: "Intake", description: null, access: "owner", inputs: {} };

const row = (n: number) => ({ object: "table_row", id: `row_${n}`, index: n, data: { n }, created_at: "2026-11-19T10:00:00+00:00" });
const params = (query: URLSearchParams) => Object.fromEntries(query.entries());

test("a workflow's files list with their workflow and a link, and never act for a user", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/workflows/files", json(listing([FILE])));
  api.on("GET", "/v1/workflows", json(listing([WORKFLOW])));
  const [invoice] = await nc.WorkflowFile.list({ workflow: nc.Workflow.fromName("Intake"), organizationId: "none" });
  assert.deepEqual(params(listed.last.query), { workflow_id: "wf_1", organization_id: "none" });
  assert.equal(listed.last.headers.get("noclick-user"), null);
  assert.deepEqual([invoice.id, invoice.name, invoice.workflow, invoice.access, invoice.stepId],
    ["res_f1", "invoice.pdf", { id: "wf_1", name: "Intake", stepTypes: ["trigger-webhook", "agent:codex", "automation-gmail"] }, "editor", "upload"]);
  assert.deepEqual([invoice.type, invoice.sizeBytes, invoice.mimeType, invoice.url], ["document", 1024, "application/pdf", FILE.url]);
  assert.equal(invoice.urlExpiresAt?.toISOString(), "2026-11-19T11:00:00.000Z");
  const page = await nc.WorkflowFile.listPage({ workflow: "wf_2", cursor: "res_f0", limit: 10 });
  assert.deepEqual(params(listed.last.query), { workflow_id: "wf_2", cursor: "res_f0", limit: "10" });
  assert.deepEqual([page.data.map((f) => f.id), page.nextCursor], [["res_f1"], null]);
});

test("a file and a table are deleted by their own routes", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/files", json(listing([FILE])));
  api.on("GET", "/v1/workflows/tables", json(listing([TABLE])));
  const goneFile = api.on("DELETE", "/v1/workflows/files/res_f1", json({ object: "workflow_file", id: "res_f1", deleted: true }));
  const goneTable = api.on("DELETE", "/v1/workflows/tables/res_t1", json({ object: "workflow_table", id: "res_t1", deleted: true }));
  const [invoice] = await nc.WorkflowFile.list();
  const [orders] = await nc.WorkflowTable.list();
  await invoice.delete();
  await orders.delete();
  assert.deepEqual([goneFile.count, goneTable.count], [1, 1]);
  assert.equal(goneFile.last.headers.get("noclick-user"), null);
});

test("a view-only workflow's file refuses its deletion, and through MCP a deletion waits for the owner", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/files", json(listing([{ ...FILE, access: "viewer" }])));
  api.on("GET", "/v1/workflows/tables", json(listing([TABLE])));
  api.on("DELETE", "/v1/workflows/files/res_f1", apiError(403, "permission_denied", "'Intake' is shared with this account to view."));
  api.on("DELETE", "/v1/workflows/tables/res_t1", apiError(402, "approval_required", "This waits for the account's owner.",
    { approval_id: "apr_1", summary: "Delete workflow table 'Orders'", sent_to: ["email"] }));
  const [invoice] = await nc.WorkflowFile.list();
  await assert.rejects(invoice.delete(), nc.PermissionDenied);
  const [orders] = await nc.WorkflowTable.list();
  await assert.rejects(orders.delete(), nc.ApprovalRequired);
});

test("a table's rows read by page and whole", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/tables", json(listing([TABLE])));
  const rows = api.on("GET", "/v1/workflows/tables/res_t1/rows",
    json({ object: "list", data: [row(0), row(1)], total_count: 3, next_cursor: "2" }),
    json({ object: "list", data: [row(2)], total_count: 3, next_cursor: null }),
    json({ object: "list", data: [row(0)], total_count: 3, next_cursor: "1" }));
  const [orders] = await nc.WorkflowTable.list({ workflow: "wf_1" });
  assert.deepEqual([orders.rowCount, orders.databaseId, orders.access], [3, "db_1", "owner"]);
  const every = await orders.rows();
  assert.deepEqual(every.map((r) => [r.id, r.index, r.data]), [["row_0", 0, { n: 0 }], ["row_1", 1, { n: 1 }], ["row_2", 2, { n: 2 }]]);
  // Read whole, a page holds the most a page may: 10,000 rows.
  assert.deepEqual(rows.calls.map((c) => params(c.query)), [{ limit: "10000" }, { cursor: "2", limit: "10000" }]);
  const page = await orders.rowsPage({ limit: 1 });
  assert.deepEqual(params(rows.last.query), { limit: "1" });
  assert.deepEqual([page.data.map((r) => r.index), page.nextCursor, page.totalCount], [[0], "1", 3]);
});

test("rows stop at a limit", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflows/tables", json(listing([TABLE])));
  const rows = api.on("GET", "/v1/workflows/tables/res_t1/rows",
    json({ object: "list", data: [row(0), row(1)], total_count: 3, next_cursor: "2" }));
  const [orders] = await nc.WorkflowTable.list();
  assert.deepEqual((await orders.rows({ limit: 2 })).map((r) => r.index), [0, 1]);
  assert.deepEqual([params(rows.last.query), rows.count], [{ limit: "2" }, 1]);
});

test("the account's files page by cursor and are deleted as the account", async () => {
  const { api } = setup();
  const made = { object: "attachment", id: "res_1", name: "cake.png", mime_type: "image/png", size_bytes: 900, kind: "image",
    voice: false, url: "https://assets.example/u/account/res_1/cake.png", duration_ms: null, peaks: null,
    created_at: "2026-11-19T10:00:00+00:00", updated_at: "2026-11-19T10:30:00+00:00" };
  const listed = api.on("GET", "/v1/attachments", json(listing([made], "res_1")));
  const page = await nc.attachmentsPage({ query: "cake", cursor: "res_0", limit: 1 });
  assert.deepEqual(params(listed.last.query), { query: "cake", cursor: "res_0", limit: "1" });
  assert.deepEqual([page.data.map((f) => f.id), page.nextCursor], [["res_1"], "res_1"]);
  assert.deepEqual([page.data[0].createdAt?.toISOString(), page.data[0].updatedAt?.toISOString()],
    ["2026-11-19T10:00:00.000Z", "2026-11-19T10:30:00.000Z"]);
  const gone = api.on("DELETE", "/v1/attachments/res_1", json({ object: "attachment", id: "res_1", deleted: true }));
  await nc.deleteAttachment(page.data[0]);
  await nc.deleteAttachment("res_1");
  assert.equal(gone.count, 2);
  assert.equal(gone.last.headers.get("noclick-user"), null);
  await assert.rejects(nc.deleteAttachment({ ...page.data[0], id: null }), TypeError);
});

test("an agent step's workspaces list as Resources lists them, each reading its files", async () => {
  const { api } = setup();
  const PLACE = { object: "step_workspace", workflow: { id: "wf_1", name: "Intake", step_types: ["agent"] },
    step_id: "helper", step_name: "Helper", model: "claude-code", conversation: "orders", title: "Orders",
    last_activity: "2026-11-24T10:00:00+00:00" };
  const listed = api.on("GET", "/v1/workflows/workspaces", json(listing([PLACE])));
  const files = api.on("GET", "/v1/workflows/wf_1/steps/helper/workspace",
    json({ object: "list", data: [], workspace: "/workspace", exists: true, truncated: false, upload_url: null }));
  const [place] = await nc.AgentStepWorkspace.list({ organizationId: "none" });
  assert.deepEqual(params(listed.last.query), { organization_id: "none" });
  assert.deepEqual([place.stepId, place.stepName, place.conversation, place.workflow.id], ["helper", "Helper", "orders", "wf_1"]);
  assert.equal((await place.files()).workspace, "/workspace");
  assert.deepEqual(params(files.last.query), { conversation: "orders" });
});
