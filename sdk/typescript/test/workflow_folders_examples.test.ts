// Workflow folders (`GET`/`POST /v1/workflows/folders`, `POST /v1/workflows/{id}/move`) and NoClick's example
// workflows (`GET /v1/workflow_examples` and `/v1/workflow_examples/{id}`): what the client sends and how it reads
// the answer.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, setup } from "./helpers.ts";

const WF = "2e3a9296-1bf5-4088-a20d-7c31937380c4";
const REPORTS = {
  object: "workflow_folder", id: "f1", name: "Reports", description: null, parent_id: null, depth: 0,
  workflow_count: 2, created_at: "2026-11-21T10:00:00Z", updated_at: "2026-11-21T10:00:00Z",
};
const WEEKLY = { ...REPORTS, id: "f2", name: "Weekly", parent_id: "f1", depth: 1, workflow_count: 0 };

function workflow(folderId: string | null) {
  return {
    object: "workflow", id: WF, name: "Morning brief", description: null, version: 3, access: "owner", inputs: {},
    apps: [], step_types: ["trigger-cron"], starts: "Every day at 8", app_url: "https://app.noclick.com/w",
    folder_id: folderId, created_at: "2026-11-20T10:00:00Z", updated_at: "2026-11-21T10:00:00Z",
  };
}

test("folders list for the account, never a user", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows/folders", json(listing([REPORTS, WEEKLY])));
  const [reports, weekly] = await nc.asUser("user_42", () => nc.Workflow.folders());
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([reports.id, reports.name, reports.parentId, reports.depth, reports.workflowCount],
    ["f1", "Reports", null, 0, 2]);
  assert.deepEqual([weekly.parentId, weekly.depth], ["f1", 1]);
  assert.equal(reports.createdAt?.getUTCFullYear(), 2026);
});

test("a folder is made at the top or in its parent", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows/folders", json(REPORTS, { status: 201 }), json(WEEKLY, { status: 201 }),
    json({ ...WEEKLY, id: "f3" }, { status: 201 }));
  const reports = await nc.Workflow.createFolder("Reports");
  const weekly = await nc.Workflow.createFolder("Weekly", { description: "Each week's", parent: reports });
  assert.deepEqual(route.calls[0].body, { name: "Reports" });
  assert.deepEqual(route.calls[1].body, { name: "Weekly", description: "Each week's", parent_id: "f1" });
  assert.deepEqual([weekly.id, weekly.parentId], ["f2", "f1"]);
  await nc.Workflow.createFolder("Daily", { parent: "f2" });
  assert.equal((route.last.body as { parent_id: string }).parent_id, "f2");
});

test("a taken name throws Conflict naming the folder", async () => {
  const { api } = setup();
  api.on("POST", "/v1/workflows/folders", apiError(409, "conflict", "The account already has a folder named 'Reports' there.", { folder_id: "f1" }));
  await assert.rejects(nc.Workflow.createFolder("Reports"), (err: unknown) => {
    assert.ok(err instanceof nc.Conflict);
    assert.equal(err.details.folder_id, "f1");
    return true;
  });
});

test("moveTo files a workflow in a folder and out to the top", async () => {
  const { api } = setup();
  const route = api.on("POST", `/v1/workflows/${WF}/move`, json(workflow("f2")), json(workflow(null)), json(workflow("f1")));
  const brief = nc.Workflow.fromId(WF);
  const weekly: nc.WorkflowFolder = {
    id: "f2", name: "Weekly", description: null, parentId: "f1", depth: 1, workflowCount: 0, access: "owner",
    owner: null, sharedAt: null, createdAt: null, updatedAt: null, raw: WEEKLY,
  };
  assert.equal((await brief.moveTo(weekly)).folderId, "f2");
  assert.equal((await brief.moveTo(null)).folderId, null);
  await brief.moveTo("f1");
  assert.deepEqual(route.calls.map((call) => call.body), [{ folder_id: "f2" }, { folder_id: null }, { folder_id: "f1" }]);
  assert.deepEqual([brief.folderId, brief.version], ["f1", 3]);
});

const EXAMPLE = {
  object: "workflow_example", id: "e1", name: "Triage support email",
  description: "When a support email arrives, an agent labels it and drafts a reply.", has_text: true,
  has_workflow: true, step_types: ["trigger-email", "agent"], updated_at: "2026-11-20T09:00:00Z",
};
const WHOLE = {
  ...EXAMPLE, text: "Wire the trigger into the agent.",
  graph: {
    nodes: [{ id: "mail", type: "trigger-email", config: { label: "Mail" } }, { id: "agent", type: "agent", config: { label: "Triage" } }],
    edges: [{ id: "mail-agent", source: "mail", target: "agent" }], withheld: {},
  },
};

test("workflowExamples() reads every page and sends the query", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflow_examples", json(listing([EXAMPLE], "e1")),
    json(listing([{ ...EXAMPLE, id: "e2", has_workflow: false, step_types: [] }])));
  const [triage, guidance] = await nc.asUser("user_42", () => nc.workflowExamples("support email"));
  assert.equal(route.calls[0].headers.get("NoClick-User"), null);
  assert.equal(route.calls[0].query.get("q"), "support email");
  assert.equal(route.calls[1].query.get("cursor"), "e1");
  assert.deepEqual([triage.name, triage.stepTypes, triage.hasText, triage.text, triage.graph],
    ["Triage support email", ["trigger-email", "agent"], true, null, null]);
  assert.equal(guidance.hasWorkflow, false);
});

test("workflowExample() reads one whole, and an unknown one throws NotFound", async () => {
  const { api } = setup();
  api.on("GET", "/v1/workflow_examples/e1", json(WHOLE));
  api.on("GET", "/v1/workflow_examples/nope", apiError(404, "not_found", "No workflow example 'nope'."));
  const example = await nc.workflowExample("e1");
  assert.equal(example.text, "Wire the trigger into the agent.");
  assert.deepEqual((example.graph?.nodes as { type: string }[]).map((node) => node.type), ["trigger-email", "agent"]);
  assert.equal(example.updatedAt?.getUTCDate(), 20);
  await assert.rejects(nc.workflowExample("nope"), nc.NotFound);
});


test("deleteFolder deletes one and answers it as it was", async () => {
  const { api } = setup();
  const route = api.on("DELETE", "/v1/workflows/folders/f2", json({ ...WEEKLY, deleted: true }));
  api.on("DELETE", "/v1/workflows/folders/f1", json({ ...REPORTS, deleted: true }));
  const weekly: nc.WorkflowFolder = {
    id: "f2", name: "Weekly", description: null, parentId: "f1", depth: 1, workflowCount: 0, access: "owner",
    owner: null, sharedAt: null, createdAt: null, updatedAt: null, raw: WEEKLY,
  };
  const deleted = await nc.asUser("user_42", () => nc.Workflow.deleteFolder(weekly));
  assert.equal(route.last.headers.get("NoClick-User"), null);
  assert.deepEqual([deleted.id, deleted.name, deleted.raw.deleted], ["f2", "Weekly", true]);
  assert.equal((await nc.Workflow.deleteFolder("f1")).id, "f1");
});

test("list sends the text to search names and descriptions for", async () => {
  const { api } = setup();
  const route = api.on("GET", "/v1/workflows", json(listing([workflow(null)])), json(listing([workflow(null)])));
  const found = await nc.Workflow.list({ search: "digest" });
  assert.equal(route.last.query.get("search"), "digest");
  assert.equal(found[0].id, WF);
  await nc.Workflow.listPage({ search: "brief", limit: 5 });
  assert.equal(route.last.query.get("search"), "brief");
});

test("a folder's workflows list as the Automations page lists them, with a picture of each graph", async () => {
  const { api } = setup();
  const preview = { nodes: [{ id: "a", type: "agent", position: { x: 0, y: 0 }, config: { model: "claude-code" } }], edges: [] };
  const route = api.on("GET", "/v1/workflows",
    json({ ...listing([{ ...workflow(null), owner: null, preview }]), hidden_shared_count: 2 }),
    json({ ...listing([{ ...workflow("f2"), access: "viewer", owner: { name: "Ada" } }]), hidden_shared_count: 0 }));
  const top = await nc.Workflow.inFolder(null, { preview: true });
  assert.deepEqual([route.last.query.get("folder_id"), route.last.query.get("include")], ["top", "preview"]);
  assert.equal(route.last.query.get("organization_id"), null);
  assert.equal(top.hiddenSharedCount, 2);
  assert.deepEqual([top.workflows[0].id, top.workflows[0].owner, top.workflows[0].preview?.nodes[0].type], [WF, null, "agent"]);
  const inside = await nc.Workflow.inFolder("f2", { organizationId: "team" });
  assert.deepEqual([route.last.query.get("folder_id"), route.last.query.get("organization_id"), route.last.query.get("include")],
    ["f2", "team", null]);
  assert.deepEqual([inside.workflows[0].owner, inside.workflows[0].preview], [{ name: "Ada" }, null]);
});

test("what others shared lists with who shared it, workflows and folders", async () => {
  const { api } = setup();
  const shared = { object: "workflow", id: WF, name: "Their brief", description: null, access: "editor",
    owner: { name: "Ada" }, shared_at: "2026-11-22T10:00:00Z", organization: null };
  const workflows = api.on("GET", "/v1/workflows", json(listing([shared])));
  const folders = api.on("GET", "/v1/workflows/folders", json(listing([
    { ...REPORTS, access: "viewer", owner: { name: "Ada" }, shared_at: "2026-11-22T10:00:00Z" }])));
  const [brief] = await nc.Workflow.sharedWithMe();
  assert.equal(workflows.last.query.get("shared_with_me"), "true");
  assert.deepEqual([brief.owner, brief.sharedAt?.getUTCDate()], [{ name: "Ada" }, 22]);
  const [folder] = await nc.Workflow.folders({ sharedWithMe: true, organizationId: "team" });
  assert.deepEqual([folders.last.query.get("shared_with_me"), folders.last.query.get("organization_id")], ["true", "team"]);
  assert.deepEqual([folder.access, folder.owner, folder.sharedAt?.getUTCDate()], ["viewer", { name: "Ada" }, 22]);
});

test("updateFolder renames and moves, null taking it to the top", async () => {
  const { api } = setup();
  const route = api.on("PATCH", "/v1/workflows/folders/f2", json({ ...WEEKLY, name: "Each week" }),
    json({ ...WEEKLY, parent_id: null, depth: 0 }));
  assert.equal((await nc.Workflow.updateFolder("f2", { name: "Each week" })).name, "Each week");
  assert.equal((await nc.Workflow.updateFolder("f2", { parent: null, organizationId: "team" })).parentId, null);
  assert.deepEqual(route.calls.map((call) => call.body), [{ name: "Each week" }, { organization_id: "team", parent_id: null }]);
});

test("fork copies a workflow, and moveTo and deleteFolder name a team workspace", async () => {
  const { api } = setup();
  const fork = api.on("POST", `/v1/workflows/${WF}/fork`, json({ ...workflow(null), id: "copy", name: "Copy of Morning brief" }, { status: 201 }));
  const move = api.on("POST", `/v1/workflows/${WF}/move`, json(workflow("f2")));
  const del = api.on("DELETE", "/v1/workflows/folders/f2", json({ ...WEEKLY, deleted: true }));
  const copy = await nc.Workflow.fromId(WF).fork({ name: "Mine", organizationId: "team" });
  assert.deepEqual(fork.last.body, { name: "Mine", organization_id: "team" });
  assert.deepEqual([copy.id, copy.name], ["copy", "Copy of Morning brief"]);
  await nc.Workflow.fromId(WF).moveTo("f2", { organizationId: "team" });
  assert.deepEqual(move.last.body, { folder_id: "f2", organization_id: "team" });
  await nc.Workflow.deleteFolder("f2", { organizationId: "team" });
  assert.equal(del.last.query.get("organization_id"), "team");
});

test("trashed lists the trash and deleteForGood deletes one for good", async () => {
  const { api } = setup();
  const trash = api.on("GET", "/v1/workflows/trash", json(listing([{ object: "workflow", id: WF, name: "Old digest",
    description: null, deleted_at: "2026-11-20T10:00:00Z", purge_after: "2026-12-20T10:00:00Z" }])));
  const purge = api.on("DELETE", `/v1/workflows/${WF}/trash`, json({ object: "workflow", id: WF, name: "Old digest", deleted: true }));
  const [old] = await nc.asUser("user_42", () => nc.Workflow.trashed());
  assert.equal(trash.last.headers.get("NoClick-User"), null);
  assert.deepEqual([old.id, old.name, old.raw.purge_after], [WF, "Old digest", "2026-12-20T10:00:00Z"]);
  await old.deleteForGood();
  assert.equal(purge.calls.length, 1);
  await assert.rejects(nc.Workflow.fromName("Old digest").deleteForGood(), nc.NotFound);
});

test("create sends no name for the next free Untitled, and files it in a folder of a workspace", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/workflows", json({ ...workflow(null), name: "Untitled 2" }, { status: 201 }),
    json(workflow("f1"), { status: 201 }));
  assert.equal((await nc.Workflow.create()).name, "Untitled 2");
  await nc.Workflow.create(null, { folder: "f1", organizationId: "org_1" });
  assert.deepEqual(route.calls.map((call) => call.body), [{}, { folder_id: "f1", organization_id: "org_1" }]);
});
