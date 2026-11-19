import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { apiError, json, listing, operation, setup, trashItem, trashed } from "./helpers.ts";

const DICT = {
  object: "dict", id: "dct_1", name: "rates-cache", key_count: 3, size_bytes: 120, used_by: [], user_id: null,
  created_at: "2026-09-25T10:00:00Z",
};
const SECRET = {
  object: "secret", id: "sec_1", name: "stripe", keys: ["KEY"], user_id: null, used_by: [],
  created_at: "2026-09-25T10:00:00Z", updated_at: "2026-09-26T10:00:00Z",
};

test("a delete returns its trash item, which restores and purges", async () => {
  const { api } = setup();
  api.on("DELETE", "/v1/dicts/dct_1", json(trashed("dict", "dct_1", "rates-cache")));
  const restore = api.on("POST", "/v1/trash/tr_1/restore", json({ ...DICT, restored: true }));
  const purge = api.on("DELETE", "/v1/trash/tr_1", json({ object: "trash_item", id: "tr_1", purged: true }));
  const item = await nc.Dict.fromId("dct_1").delete();
  assert.ok(item instanceof nc.TrashItem);
  assert.deepEqual([item.id, item.kind, item.resourceId, item.name, item.operationId], ["tr_1", "dict", "dct_1", "rates-cache", "op_del"]);
  assert.equal(item.purgeAfter?.getUTCDate(), 25);
  const back = await item.restore();
  assert.deepEqual([back.id, back.restored, restore.count], ["dct_1", true, 1]);
  await item.purge();
  assert.equal(purge.count, 1);
});

test("unpublishing an app NoClick publishes answers its trash item", async () => {
  const { api } = setup();
  const { deleted: _, ...moved } = trashed("project", "prj_1", "bakery");
  const unpublish = api.on("POST", "/v1/projects/prj_1/unpublish",
    json({ ...moved, unpublished: true, url: "https://bakery.noclick.app" }));
  const restore = api.on("POST", "/v1/trash/tr_1/restore", json({ object: "project", id: "prj_1", restored: true }));
  const item = await nc.Project.fromId("prj_1").unpublish();
  assert.deepEqual(unpublish.last.body, {});
  assert.ok(item instanceof nc.TrashItem);
  assert.deepEqual([item.id, item.kind, item.resourceId, item.operationId], ["tr_1", "project", "prj_1", "op_del"]);
  assert.equal((await item.restore()).restored, true);
  assert.equal(restore.count, 1);
});

test("the trash lists by kind and loads an item by id", async () => {
  const { api } = setup();
  const listed = api.on("GET", "/v1/trash", json(listing([trashItem("database", "db_1", "orders")])));
  api.on("GET", "/v1/trash/tr_2", json(trashItem("bucket", "bkt_1", "uploads", "tr_2")));
  const [item] = await nc.TrashItem.list({ kind: "database" });
  assert.equal(listed.last.query.get("kind"), "database");
  assert.deepEqual([item.kind, item.name], ["database", "orders"]);
  const lazy = await nc.TrashItem.fromId("tr_2").hydrate();
  assert.deepEqual([lazy.kind, lazy.name], ["bucket", "uploads"]);
});

test("an operation is undone once", async () => {
  const { api } = setup();
  api.on("GET", "/v1/operations/op_del", json(operation({ id: "op_del", kind: "trash.move", status: "succeeded", undoable: true, undone_at: null })));
  const undo = api.on("POST", "/v1/operations/op_del/undo",
    json({ object: "undo", operation_id: "op_del", result: { ...DICT, restored: true } }),
    apiError(409, "conflict", "That was already undone."));
  const op = await nc.Operation.fromId("op_del").hydrate();
  assert.deepEqual([op.undoable, op.undoneAt], [true, null]);
  assert.equal((await op.undo()).restored, true);
  await assert.rejects(op.undo(), (err: unknown) => err instanceof nc.Conflict);
  assert.equal(undo.count, 2);
});

test("a dict's history, and putting a key back", async () => {
  const { api } = setup();
  const history = api.on("GET", "/v1/dicts/dct_1/history", json(listing([
    { object: "dict_change", id: "12", key: "theme", op: "changed", previous: "dim", previous_expires_at: null, at: "2026-09-26T10:00:00Z" },
    { object: "dict_change", id: "11", key: "theme", op: "created", previous: null, previous_expires_at: null, at: "2026-09-26T09:00:00Z" },
  ])));
  const putBack = api.on("POST", "/v1/dicts/dct_1/history/12/restore", json({ object: "dict_item", key: "theme", restored: true, value: "dim" }));
  const prefs = nc.Dict.fromId("dct_1");
  const changes = await prefs.history("theme");
  assert.equal(history.last.query.get("key"), "theme");
  assert.deepEqual(changes.map((c) => [c.op, c.previous]), [["changed", "dim"], ["created", null]]);
  await prefs.restoreChange(changes[0]);
  await prefs.restoreChange("12");
  assert.equal(putBack.count, 2);
});

test("a secret's versions never carry values", async () => {
  const { api } = setup();
  api.on("GET", "/v1/secrets/sec_1/versions", json(listing([
    { object: "version", id: "ver_1", name: "stripe", op: "changed", replaced_at: "2026-09-26T10:00:00Z", keys: ["KEY"] },
  ])));
  const restore = api.on("POST", "/v1/secrets/sec_1/versions/ver_1/restore", json({ ...SECRET, restored: true }));
  const stripe = nc.Secret.fromId("sec_1");
  const [version] = await stripe.versions();
  assert.deepEqual([version.op, version.keys, version.value], ["changed", ["KEY"], null]);
  assert.equal(await stripe.restoreVersion(version), stripe);
  assert.equal(restore.count, 1);
});

test("an app's secret and setting versions", async () => {
  const { api } = setup();
  const secretVersions = api.on("GET", "/v1/projects/prj_1/secrets/STRIPE_KEY/versions", json(listing([
    { object: "version", id: "ver_2", name: "STRIPE_KEY", op: "deleted", environment: "production", replaced_at: "2026-09-26T10:00:00Z" },
  ])));
  const secretBack = api.on("POST", "/v1/projects/prj_1/secrets/STRIPE_KEY/versions/ver_2/restore",
    json({ object: "project_secret", name: "STRIPE_KEY", environments: ["production"], restored: true }));
  api.on("GET", "/v1/projects/prj_1/settings/THEME/versions", json(listing([
    { object: "version", id: "ver_3", name: "THEME", op: "changed", value: "dark", replaced_at: "2026-09-26T10:00:00Z" },
  ])));
  const settingBack = api.on("POST", "/v1/projects/prj_1/settings/THEME/versions/ver_3/restore",
    json({ object: "project_setting", name: "THEME", value: "dark", restored: true }));
  const app = nc.Project.fromId("prj_1");
  const [deleted] = await app.secrets.versions("STRIPE_KEY", { environment: "production" });
  assert.equal(secretVersions.last.query.get("environment"), "production");
  assert.deepEqual([deleted.op, deleted.environment], ["deleted", "production"]);
  await app.secrets.restore("STRIPE_KEY", deleted);
  assert.equal(secretBack.count, 1);
  const [earlier] = await app.settings.versions("THEME");
  assert.equal(await app.settings.restore("THEME", earlier.id), "dark");
  assert.equal(settingBack.count, 1);
});

test("a file's earlier versions, and putting one back", async () => {
  const { api } = setup();
  const versions = api.on("GET", "/v1/buckets/bkt_1/objects/versions", json(listing([
    { object: "object_version", id: "20261016T101500000000Z-changed", key: "menu.txt", op: "changed", size: 4, replaced_at: "2026-10-16T10:15:00+00:00" },
  ])));
  const restore = api.on("POST", "/v1/buckets/bkt_1/objects/versions/restore", json({
    object: "bucket_object", key: "menu.txt", size: 4, content_type: "text/plain", etag: "e", metadata: {}, updated_at: "2026-10-16T10:20:00Z", restored: true,
  }));
  const bucket = nc.Bucket.fromId("bkt_1");
  const [version] = await bucket.versions("menu.txt");
  assert.equal(versions.last.query.get("key"), "menu.txt");
  assert.deepEqual([version.op, version.size], ["changed", 4]);
  assert.equal((await bucket.restoreVersion("menu.txt", version)).key, "menu.txt");
  assert.deepEqual(restore.last.body, { key: "menu.txt", version_id: version.id });
});
