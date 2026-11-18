// Volumes and secrets, and mounting them into sandboxes and agents:
// the routes, bodies and parsed results the TypeScript client sends and reads.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const VOL_ID = "4c8e1f0a-6b3d-4a92-9e57-1d2f8b0c7a36";
const SECRET_ID = "2a7f0c3e-9d1b-4e6a-8c5f-3b0e7d2a9c14";
const VOLUME = {
  object: "volume", id: VOL_ID, name: "datasets", size_bytes: 13314398618, file_count: 1840,
  mounted_by: [{ kind: "agent", id: "ag_1", name: "assistant", path: "/data" }, { kind: "sandbox", id: "sb_1", name: null, path: "/data" }],
  user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const SECRET = {
  object: "secret", id: SECRET_ID, name: "openai", keys: ["OPENAI_API_KEY"], user_id: null,
  used_by: [{ kind: "agent", id: "ag_1", name: "assistant", binding: null }],
  created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-20T10:00:00Z",
};
const AGENT = {
  object: "agent", id: "ag_1", name: "assistant", model: "openrouter/x", harness: "sdk", instructions: "hi", tools: [],
  user_id: null, workflow_id: "wf_1", parent_id: null, ttl_s: null, expires_at: null, budget_usd_per_month: null,
  created_at: "2026-09-25T10:00:00Z",
};
const entry = (path: string, type = "file", size: number | null = 12) => ({ object: "volume_entry", path, type, size: type === "file" ? size : null, updated_at: "2026-09-25T10:00:00Z" });

// --- volumes ----------------------------------------------------------------------

test("Volume.create, list and get", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/volumes", json({ ...VOLUME, id: "vol_2", name: "workbench", user_id: USER_ID }));
  const listed = api.on("GET", "/v1/volumes", json(listing([VOLUME], "c2")));
  api.on("GET", `/v1/volumes/${VOL_ID}`, json(VOLUME));

  const work = await nc.asUser("user_42", () => nc.Volume.create("workbench"));
  assert.deepEqual(create.last.body, { name: "workbench" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.equal(work.userId, USER_ID);

  const page = await nc.Volume.listPage({ userFilter: nc.ALL_USERS, limit: 10 });
  assert.deepEqual([listed.last.query.get("user_id"), listed.last.query.get("limit")], ["all", "10"]);
  assert.equal(listed.last.headers.get("NoClick-User"), null);
  const [first] = page.data;
  assert.deepEqual([page.nextCursor, first.sizeBytes, first.fileCount, first.createdAt?.getUTCFullYear()], ["c2", 13314398618, 1840, 2026]);
  assert.deepEqual(first.mountedBy, [
    { kind: "agent", id: "ag_1", name: "assistant", path: "/data" },
    { kind: "sandbox", id: "sb_1", name: null, path: "/data" },
  ]);
  assert.equal((await nc.Volume.get(VOL_ID)).name, "datasets");
  assert.equal(first.consoleUrl, null); // not the hosted API
});

test("Volume.fromName prefers the user's own, mounts the account's, and creates only its own", async () => {
  const { api } = setup();
  const theirs = { ...VOLUME, id: "vol_t", user_id: USER_ID };
  const lookup = api.on("GET", "/v1/volumes", json(listing([VOLUME, theirs])), json(listing([VOLUME])), json(listing([VOLUME])), json(listing([])));
  const create = api.on("POST", "/v1/volumes", json({ ...theirs, id: "vol_new" }), apiError(409, "conflict", "taken", { existing_id: VOL_ID }));
  api.on("GET", `/v1/volumes/${VOL_ID}`, json(VOLUME));

  await nc.asUser(USER_ID, async () => {
    assert.equal((await nc.Volume.fromName("datasets").hydrate()).id, "vol_t");
    assert.equal((await nc.Volume.fromName("datasets").hydrate()).id, VOL_ID);
    assert.equal((await nc.Volume.fromName("datasets", { createIfMissing: true }).hydrate()).id, "vol_new");
  });
  assert.equal(lookup.calls[0].query.get("name"), "datasets");
  assert.deepEqual(create.last.body, { name: "datasets" });
  // Created concurrently: the conflict's existing volume is adopted.
  assert.equal((await nc.Volume.fromName("datasets", { createIfMissing: true }).hydrate()).id, VOL_ID);
  await assert.rejects(nc.Volume.fromName("nope").hydrate(), (err: unknown) => err instanceof nc.NotFound && /createIfMissing/.test(String(err)));
});

test("write, read, listdir, remove and copy by path", async () => {
  const { api } = setup();
  const files = `/v1/volumes/${VOL_ID}/files`;
  const put = api.on("PUT", files, json(entry("/raw/orders.csv", "file", 17)));
  const get = api.on("GET", files, (call: Call) => {
    if (call.query.get("view") !== "list") return new Response(new TextEncoder().encode("id,total\n"), { status: 200 });
    return call.query.get("cursor") === "c2"
      ? json(listing([entry("/raw/items.csv")]))
      : json(listing([entry("/raw", "directory"), entry("/raw/orders.csv")], "c2"));
  });
  const remove = api.on("DELETE", files, json(undefined, { status: 204 }));
  const copy = api.on("POST", `/v1/volumes/${VOL_ID}/copy`, json(entry("/archive/orders.csv")));
  const vol = nc.Volume.fromId(VOL_ID, { user: USER_ID });

  const written = await vol.write("/raw/orders.csv", "id,total\n");
  assert.deepEqual([written.path, written.type, written.size], ["/raw/orders.csv", "file", 17]);
  assert.equal(put.last.query.get("path"), "/raw/orders.csv");
  assert.equal(put.last.body, "id,total\n");
  assert.equal(put.last.headers.get("NoClick-User"), USER_ID);

  assert.equal(new TextDecoder().decode(await vol.read("/raw/orders.csv")), "id,total\n");
  assert.deepEqual([...get.last.query.keys()], ["path"]);

  const all = await vol.listdir("/raw", { recursive: true });
  assert.deepEqual(all.map((e) => [e.path, e.type, e.size]), [["/raw", "directory", null], ["/raw/orders.csv", "file", 12], ["/raw/items.csv", "file", 12]]);
  const firstPage = get.calls.at(-2)!;
  assert.deepEqual([firstPage.query.get("path"), firstPage.query.get("view"), firstPage.query.get("recursive")], ["/raw", "list", "true"]);

  const page = await vol.listdirPage(undefined, { limit: 2 });
  assert.deepEqual([get.last.query.get("path"), get.last.query.get("limit"), get.last.query.get("recursive")], ["/", "2", null]);
  assert.deepEqual([page.nextCursor, page.data[1].path], ["c2", "/raw/orders.csv"]);

  await vol.remove("/tmp", { recursive: true });
  assert.deepEqual([remove.last.query.get("path"), remove.last.query.get("recursive")], ["/tmp", "true"]);
  await vol.remove("/raw/orders.csv");
  assert.equal(remove.last.query.get("recursive"), null);

  const copied = await vol.copy("/raw/orders.csv", "/archive/orders.csv");
  assert.deepEqual(copy.last.body, { src: "/raw/orders.csv", dst: "/archive/orders.csv" });
  assert.equal(copied.path, "/archive/orders.csv");
});

test("export resolves to an ExportBundle; a mounted volume refuses to delete", async () => {
  const { api } = setup();
  api.on("POST", `/v1/volumes/${VOL_ID}/export`, json(operation({ id: "op_v", kind: "volume.export", status: "running" })));
  api.on("GET", "/v1/operations/op_v/wait", json(operation({ id: "op_v", kind: "volume.export", status: "succeeded", result: { url: "https://x/datasets.tar.gz", contents: [] } })));
  const del = api.on("DELETE", `/v1/volumes/${VOL_ID}`, apiError(409, "conflict", "The assistant agent mounts datasets at /data."));
  const vol = nc.Volume.fromId(VOL_ID);

  const bundle = await (await vol.export()).wait();
  assert.equal(bundle.url, "https://x/datasets.tar.gz");
  await assert.rejects(vol.delete(), (err: unknown) => err instanceof nc.Conflict && /mounts datasets/.test(String(err)));
  assert.equal(del.count, 1);
});

// --- secrets ----------------------------------------------------------------------

test("Secret.create, list and get carry names, never values back", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/secrets", json({ ...SECRET, id: "sec_2", name: "shipping", keys: ["SHIPPING_API_KEY"] }));
  const listed = api.on("GET", "/v1/secrets", json(listing([SECRET])));
  api.on("GET", `/v1/secrets/${SECRET_ID}`, json(SECRET));

  const shipping = await nc.Secret.create("shipping", { values: { SHIPPING_API_KEY: "shp_live_1" } });
  assert.deepEqual(create.last.body, { name: "shipping", values: { SHIPPING_API_KEY: "shp_live_1" } });
  assert.deepEqual(shipping.keys, ["SHIPPING_API_KEY"]);
  await nc.Secret.create("acme-erp", { user: "acme" });
  assert.deepEqual(create.last.body, { name: "acme-erp" });
  assert.equal(create.last.headers.get("NoClick-User"), "acme");

  const [first] = await nc.Secret.list({ userFilter: nc.ALL_USERS });
  assert.equal(listed.last.query.get("user_id"), "all");
  assert.deepEqual([first.name, first.keys, first.updatedAt?.getUTCDate(), first.usedBy[0]], ["openai", ["OPENAI_API_KEY"], 20, { kind: "agent", id: "ag_1", name: "assistant", binding: null }]);
  assert.equal((await nc.Secret.get(SECRET_ID)).name, "openai");
  await assert.rejects(nc.Secret.create("bad", { values: { PORT: 8080 as unknown as string } }), TypeError);
});

test("Secret.fromName creates with values, then converges them; update merges or replaces", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/secrets", json(listing([])), json(listing([SECRET])), json(listing([SECRET])));
  const create = api.on("POST", "/v1/secrets", json(SECRET));
  const patch = api.on("PATCH", `/v1/secrets/${SECRET_ID}`, json({ ...SECRET, keys: ["ERP_PASSWORD", "ERP_USER"] }));

  const made = await nc.Secret.fromName("openai", { values: { OPENAI_API_KEY: "sk-1" }, createIfMissing: true }).hydrate();
  assert.deepEqual([made.id, create.last.body], [SECRET_ID, { name: "openai", values: { OPENAI_API_KEY: "sk-1" } }]);
  await nc.Secret.fromName("openai", { values: { OPENAI_API_KEY: "sk-2" }, createIfMissing: true }).hydrate();
  // A rotated value in the code reaches the existing secret, merged.
  assert.deepEqual([lookup.count, create.count, patch.count], [2, 1, 1]);
  assert.deepEqual(patch.last.body, { values: { OPENAI_API_KEY: "sk-2" } });
  await nc.Secret.fromName("openai", { createIfMissing: true }).hydrate();
  assert.equal(patch.count, 1); // declared without values: used as it is

  const erp = nc.Secret.fromId(SECRET_ID, { user: "acme" });
  await erp.update({ ERP_USER: "svc", ERP_TOKEN: null });
  assert.deepEqual(patch.last.body, { values: { ERP_USER: "svc", ERP_TOKEN: null } });
  assert.equal(patch.last.headers.get("NoClick-User"), "acme");
  await erp.update({ ERP_USER: "svc", ERP_PASSWORD: "pw" }, { replace: true });
  assert.deepEqual(patch.last.body, { values: { ERP_USER: "svc", ERP_PASSWORD: "pw" }, replace: true });
  assert.deepEqual(erp.keys, ["ERP_PASSWORD", "ERP_USER"]);
  await assert.rejects(erp.update({ ERP_TOKEN: null }, { replace: true }), TypeError);
});

// --- mounting into sandboxes and agents -------------------------------------------

test("Sandbox.create mounts volumes and passes secrets, looking names up where it runs", async () => {
  const { api } = setup();
  const volLookup = api.on("GET", "/v1/volumes", json(listing([VOLUME])));
  const secretLookup = api.on("GET", "/v1/secrets", json(listing([{ ...SECRET, id: "sec_2", name: "shipping" }])));
  const create = api.on("POST", "/v1/sandboxes", json({ object: "sandbox", id: "sb_1", status: "running", volumes: { "/data": VOL_ID }, secret_ids: [SECRET_ID] }));
  const other = "0b6e2d4f-8a1c-4f3e-9d7b-5c2a1e0f8b94";

  const sb = await nc.asUser("user_42", () =>
    nc.Sandbox.create({
      volumes: { "/work": nc.Volume.fromId("vol_9"), "/data": "datasets" },
      secrets: [nc.Secret.fromId(SECRET_ID), "shipping", other],
    }),
  );
  assert.deepEqual(create.last.body, { volumes: { "/data": VOL_ID, "/work": "vol_9" }, secret_ids: [SECRET_ID, "sec_2", other] });
  assert.equal(volLookup.last.headers.get("NoClick-User"), "user_42");
  assert.equal(secretLookup.last.query.get("name"), "shipping");
  assert.deepEqual([sb.volumes, sb.secretIds], [{ "/data": VOL_ID }, [SECRET_ID]]);

  await nc.Sandbox.create({ image: "python" });
  assert.deepEqual(create.last.body, { image: "python" });
});

test("an agent's volumes and secrets are created with it and converge by id", async () => {
  const { api } = setup();
  api.on("GET", "/v1/volumes", json(listing([VOLUME])));
  api.on("GET", "/v1/secrets", json(listing([SECRET])));
  const create = api.on("POST", "/v1/agents", json({ ...AGENT, id: "ag_2", name: "analyst", volumes: { "/data": VOL_ID }, secret_ids: [SECRET_ID] }));
  const analyst = await nc.Agent.create("analyst", { instructions: "hi", volumes: { "/data": "datasets" }, secrets: ["openai"] });
  const sent = create.last.body as Record<string, unknown>;
  assert.deepEqual([sent.volumes, sent.secret_ids], [{ "/data": VOL_ID }, [SECRET_ID]]);
  assert.deepEqual([analyst.volumes, analyst.secretIds], [{ "/data": VOL_ID }, [SECRET_ID]]);

  const existing = { ...AGENT, volumes: { "/data": VOL_ID }, secret_ids: [] };
  api.on("GET", "/v1/agents", json(listing([existing])));
  const patch = api.on("PATCH", "/v1/agents/ag_1", json({ ...existing, secret_ids: [SECRET_ID] }));
  const assistant = await nc.Agent.fromName("assistant", {
    createIfMissing: true, instructions: "hi", volumes: { "/data": nc.Volume.fromName("datasets") }, secrets: [nc.Secret.fromName("openai")],
  }).hydrate();
  assert.deepEqual(assistant.secretIds, [SECRET_ID]);
  assert.deepEqual(patch.last.body, { secret_ids: [SECRET_ID] }); // the mount already matched

  await nc.Agent.fromName("assistant", { createIfMissing: true, instructions: "hi", volumes: { "/data": VOL_ID } }).hydrate();
  assert.equal(patch.count, 1);
});
