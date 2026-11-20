// What a step's form shows beside its settings (`POST /v1/workflows/{id}/steps/{step}/options` and `.../values`):
// what the client sends and how it reads the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, setup } from "./helpers.ts";

const WF = "wf_1";

test("a step's choices page through with its unsaved settings, for no user", async () => {
  const { api } = setup();
  const route = api.on("POST", `/v1/workflows/${WF}/steps/read_sheet/options`,
    json({ object: "step_options", workflow_id: WF, step_id: "read_sheet", field: "spreadsheet_id", next_page_token: "2",
           withheld: [], options: [{ value: "sp_1", label: "Budget", metadata: { icon: "s" } }] }),
    json({ object: "step_options", workflow_id: WF, step_id: "read_sheet", field: "sheet_name", next_page_token: null,
           withheld: ["options[1]"], options: [{ value: "Q3", label: "Q3", metadata: null }] }));
  const sheet = nc.Workflow.fromId(WF).step("read_sheet");
  const first = await nc.asUser("user_42", () => sheet.options("spreadsheet_id", { search: "budget" }));
  assert.deepEqual(route.calls[0].body, { field: "spreadsheet_id", search: "budget" });
  assert.equal(route.calls[0].headers.get("NoClick-User"), null);
  assert.deepEqual([first.field, first.nextPageToken, first.withheld], ["spreadsheet_id", "2", []]);
  assert.deepEqual(first.options, [{ value: "sp_1", label: "Budget", metadata: { icon: "s" } }]);

  const tabs = await sheet.options("sheet_name", { settings: { spreadsheet_id: "sp_1" }, pageToken: "2" });
  assert.deepEqual(route.calls[1].body, { field: "sheet_name", settings: { spreadsheet_id: "sp_1" }, page_token: "2" });
  assert.deepEqual([tabs.nextPageToken, tabs.withheld, tabs.options[0].metadata], [null, ["options[1]"], null]);
});

test("a widget's value reads one value or several, and what was withheld", async () => {
  const { api } = setup();
  const hook = api.on("POST", `/v1/workflows/${WF}/steps/hook/values`, json({
    object: "step_value", workflow_id: WF, step_id: "hook", field: "webhook_url", value: null,
    values: { webhook_url: "https://wf-1.noclick.run", trigger_registered: true }, withheld: ["signing_secret"] }));
  const found = await nc.Workflow.fromId(WF).step("hook").value("webhook_url", { settings: { operation: "on_order" } });
  assert.deepEqual(hook.last.body, { field: "webhook_url", settings: { operation: "on_order" } });
  assert.deepEqual(found.values, { webhook_url: "https://wf-1.noclick.run", trigger_registered: true });
  assert.deepEqual([found.field, found.value, found.withheld], ["webhook_url", null, ["signing_secret"]]);

  api.on("POST", `/v1/workflows/${WF}/steps/disk/values`, json({
    object: "step_value", workflow_id: WF, step_id: "disk", field: "file_browser",
    value: { files: [{ path: "notes.md" }], count: 1 }, values: null, withheld: [] }));
  const disk = await nc.Workflow.fromId(WF).step("disk").value("file_browser");
  assert.deepEqual([disk.value, disk.values], [{ files: [{ path: "notes.md" }], count: 1 }, null]);
});

test("a step id is one path segment, and a refusal is typed", async () => {
  const { api } = setup();
  api.on("POST", `/v1/workflows/${WF}/steps/a%2Fb/values`, apiError(404, "not_found", "No step 'a/b' in 'Orders'."));
  await assert.rejects(nc.Workflow.fromId(WF).step("a/b").value("webhook_url"), nc.NotFound);
  api.on("POST", `/v1/workflows/${WF}/steps/mcp/values`,
    apiError(403, "permission_denied", "Loading a hosted MCP link is out of reach over MCP."));
  await assert.rejects(nc.Workflow.fromId(WF).step("mcp").value("hosted_url"), nc.PermissionDenied);
});
