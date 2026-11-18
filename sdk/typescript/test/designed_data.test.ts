// Databases and buckets (designed, not built yet): the routes, bodies and parsed results the
// TypeScript client sends and reads, against the fetch double.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { USER_ID, apiError, json, listing, operation, setup, trashed } from "./helpers.ts";
import type { Call } from "./helpers.ts";

const DB = {
  object: "database", id: "db_1", name: "booking-db", engine: "sqlite", status: "ready", size_bytes: 1932735283,
  table_count: 4, parent_id: null, user_id: null, used_by: [{ kind: "project", id: "prj_1", name: "booking", binding: "DB" }],
  created_at: "2026-09-25T10:00:00Z",
};
const BUCKET = {
  object: "bucket", id: "bkt_1", name: "uploads", public: false, size_bytes: 45204279705, object_count: 18204,
  public_base_url: null, used_by: [], user_id: null, created_at: "2026-09-25T10:00:00Z",
};
const PUBLIC = { ...BUCKET, id: "bkt_2", name: "public-assets", public: true, public_base_url: "https://files.noclick.site/b/acme-public-assets" };
const RESULT = {
  object: "query_result", columns: ["id", "item"], rows: [{ id: "o1", item: "bun" }], rows_read: 1, rows_written: 0,
  last_row_id: null, duration_ms: 1.4,
};

// --- databases -----------------------------------------------------------------

test("Database.create, list and get", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/databases", json({ ...DB, id: "db_2", name: "analytics", engine: "postgres" }));
  const listed = api.on("GET", "/v1/databases", json(listing([DB], "c2")));
  api.on("GET", "/v1/databases/db_1", json(DB));

  const analytics = await nc.asUser("user_42", () => nc.Database.create("analytics", { engine: "postgres" }));
  assert.deepEqual(create.last.body, { name: "analytics", engine: "postgres" });
  assert.equal(create.last.headers.get("NoClick-User"), "user_42");
  assert.equal(analytics.engine, "postgres");
  await nc.Database.create("orders");
  assert.deepEqual(create.last.body, { name: "orders", engine: "sqlite" });

  const page = await nc.Database.listPage({ engine: "sqlite", userFilter: nc.ALL_USERS, limit: 10 });
  assert.deepEqual([listed.last.query.get("engine"), listed.last.query.get("user_id"), listed.last.query.get("limit")], ["sqlite", "all", "10"]);
  assert.equal(page.nextCursor, "c2");
  const [first] = page.data;
  assert.deepEqual([first.sizeBytes, first.tableCount, first.usedBy[0].binding, first.createdAt?.getUTCFullYear()], [1932735283, 4, "DB", 2026]);
  assert.equal((await nc.Database.get("db_1")).name, "booking-db");
  assert.equal(first.consoleUrl, null); // not the hosted API
});

test("an agent or a toolkit takes a database, or some of its operations, as tools", async () => {
  const { api } = setup();
  api.on("GET", "/v1/databases", json(listing([])));
  const created = api.on("POST", "/v1/databases", json({ ...DB, id: "db_9", name: "notes" }));
  const agent = api.on("POST", "/v1/agents", json({ object: "agent", id: "ag_2", name: "concierge", instructions: "hi", tools: [] }));
  const bookings = nc.Database.fromId("db_1");
  const notes = nc.Database.fromName("notes", { createIfMissing: true });
  await nc.Agent.create("concierge", { instructions: "hi", tools: [bookings.only("query", "schema"), notes, "search"] });
  // A lazy createIfMissing database is created first, then named by id.
  assert.equal(created.calls.length, 1);
  assert.deepEqual((agent.last.body as { tools: string[] }).tools, ["database:db_1.query", "database:db_1.schema", "database:db_9", "search"]);

  const toolkit = new nc.Toolkit([bookings.only("execute"), nc.Database.fromId("db_2")]);
  assert.deepEqual(toolkit.tools, ["db_1.execute", "db_2"]);
  assert.throws(() => bookings.only("drop" as nc.DatabaseTool), /query, execute, schema, not drop/);
  assert.throws(() => bookings.only(), /not nothing/);
});

test("Database.fromName finds by exact name, creates when asked, adopts a concurrent create", async () => {
  const { api } = setup();
  const lookup = api.on("GET", "/v1/databases", json(listing([{ ...DB, name: "booking-db-old" }])), json(listing([])), json(listing([])));
  const create = api.on(
    "POST", "/v1/databases",
    json({ ...DB, id: "db_9", name: "orders", engine: "postgres" }),
    apiError(409, "conflict", "taken", { existing_id: "db_1" }),
  );
  api.on("GET", "/v1/databases/db_1", json(DB));

  const lazy = nc.Database.fromName("orders", { createIfMissing: true, engine: "postgres" });
  assert.equal(lookup.count, 0);
  assert.equal(lazy.name, "orders");
  await lazy.hydrate();
  assert.equal(lazy.id, "db_9");
  assert.equal(lookup.calls[0].query.get("name"), "orders");
  assert.deepEqual(create.last.body, { name: "orders", engine: "postgres" });

  await assert.rejects(nc.Database.fromName("orders").hydrate(), (err: unknown) => err instanceof nc.NotFound && /createIfMissing/.test(String(err)));
  assert.equal((await nc.Database.fromName("booking-db", { createIfMissing: true }).hydrate()).id, "db_1");
});

test("fromName inside an app resolves in the app's own namespace", async () => {
  // A deployed app's code holds no key: it asks for the app's own resource of that name (a preview
  // branch's own, made on first use), never the account's list.
  const { api, client } = setup();
  const listed = api.on("GET", "/v1/databases", json(listing([])));
  let made = 0;
  const resolve = api.on("POST", "/v1/projects/current/resources", () =>
    json(made++ === 0 ? { ...DB, id: "db_9", name: "orders" } : { ...BUCKET, id: "bkt_9", name: "uploads" }));
  process.env.NOCLICK_DEPLOYMENT_TOKEN = "nk_dep_123";
  try {
    const inApp = new nc.NoClick({ baseUrl: "https://api.test", fetch: api.fetch });
    assert.ok(inApp.inApp && !client.inApp);
    const db = await nc.Database.fromName("orders", { createIfMissing: true, engine: "postgres", client: inApp }).hydrate();
    const bucket = await nc.Bucket.fromName("uploads", { client: inApp }).hydrate();
    assert.deepEqual([db.id, bucket.id], ["db_9", "bkt_9"]);
    await nc.Database.fromName("orders", { branchData: "copy", client: inApp }).hydrate();
  } finally {
    delete process.env.NOCLICK_DEPLOYMENT_TOKEN;
  }
  assert.deepEqual(resolve.calls.map((c) => c.body), [
    { kind: "database", name: "orders", create_if_missing: true, engine: "postgres" },
    { kind: "bucket", name: "uploads", create_if_missing: false },
    { kind: "database", name: "orders", create_if_missing: false, branch_data: "copy" },
  ]);
  assert.equal(resolve.last.headers.get("Authorization"), "Bearer nk_dep_123");
  assert.equal(listed.count, 0);
});

test("query runs read-only; execute and batch write", async () => {
  const { api } = setup();
  const run = api.on("POST", "/v1/databases/db_1/query", (call: Call) => {
    const body = call.body as { statements?: unknown[] };
    if (body.statements) return json({ object: "batch_result", results: [{ ...RESULT, rows_written: 1 }, { ...RESULT, rows_written: 2 }] });
    return json(RESULT);
  });
  const db = nc.Database.fromId("db_1", { user: USER_ID });

  const result = await db.query("select id, item from orders where qty > ?", [2]);
  assert.deepEqual(run.last.body, { sql: "select id, item from orders where qty > ?", params: [2], read_only: true });
  assert.equal(run.last.headers.get("NoClick-User"), USER_ID);
  assert.ok(result instanceof nc.QueryResult);
  assert.deepEqual([...result].map((row) => row.item), ["bun"]);
  assert.deepEqual([result.length, result.columns, result.rowsRead, result.durationMs, result.lastRowId], [1, ["id", "item"], 1, 1.4, null]);

  await db.query("select * from bookings where starts_at >= :day", { day: new Date("2026-10-01T18:30:00Z") });
  assert.deepEqual((run.last.body as { params: unknown }).params, { day: "2026-10-01T18:30:00.000Z" });

  await db.execute("delete from holds");
  assert.deepEqual(run.last.body, { sql: "delete from holds" });

  const [moved, freed] = await db.batch([["update bookings set slot = ? where id = ?", ["18:30", "b_41"]], "delete from holds"]);
  assert.deepEqual(run.last.body, {
    statements: [{ sql: "update bookings set slot = ? where id = ?", params: ["18:30", "b_41"] }, { sql: "delete from holds" }],
  });
  assert.deepEqual([moved.rowsWritten, freed.rowsWritten], [1, 2]);
});

test("migrate sends migrations in name order; migrations and schema read back", async () => {
  const { api } = setup();
  const migrate = api.on("POST", "/v1/databases/db_1/migrations", json({ applied: ["0002_b.sql"], pending: [] }));
  api.on("GET", "/v1/databases/db_1/migrations", json(listing([{ name: "0001_a.sql", applied_at: "2026-09-20T09:00:00Z", checksum: "sha256:ab" }])));
  api.on("GET", "/v1/databases/db_1/schema", json(listing([{
    name: "bookings", row_count: 48210,
    columns: [{ name: "id", type: "TEXT", nullable: false, primary_key: true, default: null }, { name: "party_size", type: "INTEGER", default: "2" }],
  }])));
  const db = nc.Database.fromId("db_1");

  const result = await db.migrate({ "0002_b.sql": "create table b (x int)", "0001_a.sql": "create table a (x int)" });
  assert.deepEqual(migrate.last.body, {
    migrations: [{ name: "0001_a.sql", sql: "create table a (x int)" }, { name: "0002_b.sql", sql: "create table b (x int)" }],
  });
  assert.deepEqual([result.applied, result.pending], [["0002_b.sql"], []]);
  await db.migrate([{ name: "0003_c.sql", sql: "select 1" }], { dryRun: true, seed: "insert into a values (1)" });
  assert.deepEqual(migrate.last.body, { migrations: [{ name: "0003_c.sql", sql: "select 1" }], dry_run: true });
  await db.migrate({ "0001_a.sql": "create table a (x int)" }, { seed: "insert into a values (1)" });
  assert.equal((migrate.last.body as Record<string, unknown>).seed, "insert into a values (1)");
  await assert.rejects(db.migrate({}), TypeError);

  const [migration] = await db.migrations();
  assert.deepEqual([migration.name, migration.appliedAt?.getUTCDate(), migration.checksum], ["0001_a.sql", 20, "sha256:ab"]);
  const [table] = await db.schema();
  assert.deepEqual([table.name, table.rowCount], ["bookings", 48210]);
  assert.deepEqual(table.columns, [
    { name: "id", type: "TEXT", nullable: false, primaryKey: true, default: null },
    { name: "party_size", type: "INTEGER", nullable: true, primaryKey: false, default: "2" },
  ]);
});

test("restore and branch are operations that resolve to a Database", async () => {
  const { api } = setup();
  const restore = api.on("POST", "/v1/databases/db_1/restore", json(operation({ id: "op_r", kind: "database.restore", status: "running" })));
  api.on("GET", "/v1/operations/op_r/wait", json(operation({ id: "op_r", kind: "database.restore", status: "succeeded", result: DB })));
  const branch = api.on("POST", "/v1/databases/db_1/branches", json(operation({ id: "op_b", kind: "database.branch", status: "running" })));
  api.on("GET", "/v1/operations/op_b/wait", json(operation({
    id: "op_b", kind: "database.branch", status: "succeeded", result: { ...DB, id: "db_3", name: "booking-pg", engine: "postgres", parent_id: "db_1" },
  })));
  const db = nc.Database.fromId("db_1");

  const restored = await (await db.restore({ at: new Date("2026-09-25T08:00:00Z") })).wait();
  assert.deepEqual(restore.last.body, { at: "2026-09-25T08:00:00.000Z" });
  assert.equal(restored.status, "ready");

  const bigger = await (await db.branch("booking-pg", { engine: "postgres" })).wait();
  assert.deepEqual(branch.last.body, { name: "booking-pg", engine: "postgres" });
  assert.ok(bigger instanceof nc.Database);
  assert.deepEqual([bigger.engine, bigger.parentId], ["postgres", "db_1"]);
  assert.equal((await nc.Operation.fromId("op_b").wait() as nc.Database).id, "db_3"); // resumed by id, typed by kind
});

test("branches, connectionUrl, export and delete", async () => {
  const { api } = setup();
  api.on("GET", "/v1/databases/db_1/branches", json(listing([{ ...DB, id: "db_3", name: "booking-db-preview", parent_id: "db_1" }])));
  const url = api.on("POST", "/v1/databases/db_1/connection_url", json({ url: "postgresql://ro:pw@db.example.com/analytics", expires_at: "2026-09-25T11:00:00Z" }));
  api.on("POST", "/v1/databases/db_1/export", json(operation({
    id: "op_x", kind: "database.export", status: "succeeded",
    result: { url: "https://x/booking-db.zip", expires_at: "2026-10-02T10:00:00Z", contents: [{ kind: "database", name: "booking-db", detail: "SQL dump." }] },
  })));
  const del = api.on("DELETE", "/v1/databases/db_1", json(trashed("database", "db_1", "booking-db")));
  const db = nc.Database.fromId("db_1");

  const [preview] = await db.branches();
  assert.deepEqual([preview.name, preview.parentId], ["booking-db-preview", "db_1"]);
  assert.match(await db.connectionUrl({ ttlS: 600, readOnly: true }), /^postgresql:/);
  assert.deepEqual(url.last.body, { ttl_s: 600, read_only: true });
  await db.connectionUrl();
  assert.deepEqual(url.last.body, { ttl_s: 3600 });
  const bundle = await (await db.export()).wait();
  assert.deepEqual([bundle.url, bundle.contents[0].kind], ["https://x/booking-db.zip", "database"]);
  assert.equal((await db.delete()).kind, "database");
  assert.equal(del.count, 1);
});

// --- buckets -------------------------------------------------------------------

test("Bucket.create, list and a lazy name", async () => {
  const { api } = setup();
  const create = api.on("POST", "/v1/buckets", json(PUBLIC));
  const lookup = api.on("GET", "/v1/buckets", json(listing([BUCKET, PUBLIC])));
  const assets = await nc.Bucket.create("public-assets", { public: true });
  assert.deepEqual(create.last.body, { name: "public-assets", public: true });
  assert.equal(assets.publicBaseUrl, PUBLIC.public_base_url);

  assert.deepEqual((await nc.Bucket.list({ userFilter: nc.ALL_USERS })).map((b) => b.name), ["uploads", "public-assets"]);
  const uploads = await nc.Bucket.fromName("uploads", { createIfMissing: true }).hydrate();
  assert.deepEqual([uploads.objectCount, uploads.public, create.count], [18204, false, 1]);
  assert.equal(lookup.last.query.get("name"), "uploads");
});

test("put, get, head and remove a file", async () => {
  const { api } = setup();
  const put = api.on("PUT", "/v1/buckets/bkt_1/objects", json({
    key: "invoices/0042.pdf", size: 11, content_type: "application/pdf", etag: "e1", metadata: { user: "acme" }, updated_at: "2026-09-25T10:00:00Z",
  }));
  const read = api.on("GET", "/v1/buckets/bkt_1/objects", (call: Call) =>
    call.query.get("view") === "metadata"
      ? json({ key: call.query.get("key"), size: 11, content_type: "application/pdf", etag: "e1", metadata: {} })
      : new Response(new TextEncoder().encode("%PDF-1.7"), { status: 200 }));
  const remove = api.on("DELETE", "/v1/buckets/bkt_1/objects", json(undefined, { status: 204 }));
  const bucket = nc.Bucket.fromId("bkt_1", { user: USER_ID });

  const bytes = new TextEncoder().encode("%PDF-1.7");
  const stored = await bucket.put("invoices/0042.pdf", bytes, { contentType: "application/pdf", metadata: { user: "acme" } });
  assert.deepEqual([put.last.query.get("key"), put.last.query.get("content_type")], ["invoices/0042.pdf", "application/pdf"]);
  assert.deepEqual(JSON.parse(put.last.query.get("metadata")!), { user: "acme" });
  assert.equal(put.last.body, bytes);
  assert.equal(put.last.headers.get("NoClick-User"), USER_ID);
  assert.deepEqual([stored.size, stored.etag, stored.metadata, stored.isFolder], [11, "e1", { user: "acme" }, false]);
  await bucket.put("notes/hi.txt", "hi");
  assert.equal(put.last.query.get("content_type"), null);

  assert.equal(new TextDecoder().decode(await bucket.read("invoices/0042.pdf")), "%PDF-1.7");
  assert.deepEqual([read.last.query.get("key"), read.last.query.get("view")], ["invoices/0042.pdf", null]);
  const info = await bucket.head("invoices/0042.pdf");
  assert.deepEqual([info.key, info.size, info.contentType], ["invoices/0042.pdf", 11, "application/pdf"]);
  await bucket.remove("invoices/0042.pdf");
  assert.equal(remove.last.query.get("key"), "invoices/0042.pdf");
});

test("objects rolls folders up and follows cursors", async () => {
  const { api } = setup();
  const route = api.on(
    "GET", "/v1/buckets/bkt_1/objects",
    json(listing([{ key: "invoices/2026/", folder: true }, { key: "invoices/0042.pdf", size: 11 }], "c2")),
    json(listing([{ key: "invoices/0043.pdf", size: 12 }])),
    json(listing([{ key: "a" }], "c9")),
  );
  const bucket = nc.Bucket.fromId("bkt_1");
  const [folder, first, second] = await bucket.objects({ prefix: "invoices/", delimiter: "/" });
  assert.deepEqual([folder.key, folder.isFolder, folder.size], ["invoices/2026/", true, null]);
  assert.deepEqual([first.key, second.key], ["invoices/0042.pdf", "invoices/0043.pdf"]);
  assert.deepEqual(route.calls.map((c) => [c.query.get("prefix"), c.query.get("delimiter"), c.query.get("cursor")]), [
    ["invoices/", "/", null], ["invoices/", "/", "c2"],
  ]);
  const page = await bucket.objectsPage({ limit: 1 });
  assert.deepEqual([page.nextCursor, page.data[0].key, route.last.query.get("limit")], ["c9", "a", "1"]);
});

test("signed and public URLs", async () => {
  const { api } = setup();
  const sign = api.on("POST", "/v1/buckets/bkt_1/signed_urls", json({ url: "https://files.noclick.site/s/abc", expires_at: "2026-09-25T11:00:00Z" }));
  api.on("GET", "/v1/buckets/bkt_1", json(BUCKET));
  api.on("GET", "/v1/buckets/bkt_2", json(PUBLIC));
  const uploads = nc.Bucket.fromId("bkt_1");
  assert.equal((await nc.Bucket.get("bkt_1")).name, "uploads");

  assert.equal(await uploads.signedUrl("invoices/0042.pdf"), "https://files.noclick.site/s/abc");
  assert.deepEqual(sign.last.body, { key: "invoices/0042.pdf", method: "GET", expires_in: 3600 });
  await uploads.signedUrl("avatars/u42.png", { method: "PUT", expiresIn: 600, contentType: "image/png" });
  assert.deepEqual(sign.last.body, { key: "avatars/u42.png", method: "PUT", expires_in: 600, content_type: "image/png" });

  assert.equal(await nc.Bucket.fromId("bkt_2").url("img/logo 2.png"), "https://files.noclick.site/b/acme-public-assets/img/logo%202.png");
  await assert.rejects(uploads.url("a.pdf"), (err: unknown) => err instanceof nc.NotAvailable && /private/.test(String(err)));
});

test("a file goes up in parts", async () => {
  const { api } = setup();
  const start = api.on("POST", "/v1/buckets/bkt_1/uploads", json({
    object: "bucket_upload", bucket_id: "bkt_1", key: "b737/fcom.pdf", upload_id: "up_1", content_type: "application/pdf",
    min_part_bytes: 5242880, max_part_bytes: 5368709120, max_parts: 10000,
  }));
  const sign = api.on("POST", "/v1/buckets/bkt_1/uploads/part_urls", (call: Call) => json({
    object: "list",
    data: (call.body as { part_numbers: number[] }).part_numbers.map((n) => ({ object: "upload_part_url", part_number: n, method: "PUT", url: `https://r2.example/p${n}` })),
  }));
  const complete = api.on("POST", "/v1/buckets/bkt_1/uploads/complete", json({
    object: "bucket_object", key: "b737/fcom.pdf", size: 1200000000, content_type: "application/pdf", etag: "c3-2",
    metadata: { tail: "n123" }, updated_at: "2026-10-26T10:00:00Z", folder: false,
  }));
  const abort = api.on("POST", "/v1/buckets/bkt_1/uploads/abort", json({ object: "bucket_upload", aborted: true }));
  const bucket = nc.Bucket.fromId("bkt_1");

  const upload = await bucket.startUpload("b737/fcom.pdf", { metadata: { tail: "n123" } });
  assert.deepEqual(start.last.body, { key: "b737/fcom.pdf", metadata: { tail: "n123" } });
  assert.deepEqual([upload.uploadId, upload.contentType, upload.minPartBytes, upload.maxParts], ["up_1", "application/pdf", 5242880, 10000]);
  // More parts than one request signs go in as many requests as it takes.
  const links = await bucket.uploadPartUrls("b737/fcom.pdf", "up_1", Array.from({ length: 2500 }, (_, i) => i + 1), { expiresIn: 900 });
  assert.equal(Object.keys(links).length, 2500);
  assert.equal(links[2500], "https://r2.example/p2500");
  assert.deepEqual(sign.calls.map((c) => (c.body as { part_numbers: number[] }).part_numbers.length), [1000, 1000, 500]);
  assert.deepEqual({ ...(sign.calls[0].body as object), part_numbers: undefined }, { key: "b737/fcom.pdf", upload_id: "up_1", expires_in: 900, part_numbers: undefined });

  const stored = await bucket.completeUpload("b737/fcom.pdf", "up_1", { 2: '"e2"', 1: '"e1"' });
  assert.deepEqual(complete.last.body, { key: "b737/fcom.pdf", upload_id: "up_1", parts: [{ part_number: 1, etag: '"e1"' }, { part_number: 2, etag: '"e2"' }] });
  assert.deepEqual([stored.size, stored.metadata], [1200000000, { tail: "n123" }]);
  assert.equal(await bucket.abortUpload("b737/fcom.pdf", "up_1"), undefined);
  assert.deepEqual(abort.last.body, { key: "b737/fcom.pdf", upload_id: "up_1" });
});

test("update, S3 credentials, export and delete", async () => {
  const { api } = setup();
  const patch = api.on("PATCH", "/v1/buckets/bkt_1", json({ ...PUBLIC, id: "bkt_1" }));
  const creds = api.on("POST", "/v1/buckets/bkt_1/s3_credentials", json({
    endpoint: "https://s3.example.com", bucket: "nc-acme-uploads-7f3a", access_key_id: "AKID", secret_access_key: "SECRET",
    session_token: "TOKEN", region: "auto", read_only: true, expires_at: "2026-09-25T11:00:00Z",
  }));
  api.on("POST", "/v1/buckets/bkt_1/export", json(operation({ id: "op_e", kind: "bucket.export", status: "running" })));
  api.on("GET", "/v1/operations/op_e/wait", json(operation({ id: "op_e", kind: "bucket.export", status: "succeeded", result: { url: "https://x/uploads.zip" } })));
  const del = api.on("DELETE", "/v1/buckets/bkt_1", json(trashed("bucket", "bkt_1", "uploads")), apiError(409, "conflict", "uploads holds 18,204 files.", { next_step: "Pass force." }));
  const bucket = nc.Bucket.fromId("bkt_1");

  assert.equal(await bucket.update({ public: true }), bucket);
  assert.equal(bucket.public, true);
  assert.deepEqual(patch.last.body, { public: true });
  const s3 = await bucket.s3Credentials({ readOnly: true, ttlS: 900 });
  assert.deepEqual(creds.last.body, { ttl_s: 900, read_only: true });
  assert.deepEqual([s3.bucket, s3.accessKeyId, s3.secretAccessKey, s3.sessionToken, s3.readOnly], ["nc-acme-uploads-7f3a", "AKID", "SECRET", "TOKEN", true]);
  assert.equal((await (await bucket.export()).wait()).url, "https://x/uploads.zip");

  await bucket.delete({ force: true });
  assert.equal(del.last.query.get("force"), "true");
  await assert.rejects(bucket.delete(), (err: unknown) => err instanceof nc.Conflict);
  assert.equal(del.last.query.get("force"), null);
});
