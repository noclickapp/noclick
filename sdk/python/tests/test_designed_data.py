"""Databases and buckets (designed, not built yet): the routes, bodies and parsed results
the clients send and read, against the mocked transport."""

import json
from datetime import datetime, timezone

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation, trashed

DB = {"object": "database", "id": "db_1", "name": "booking-db", "engine": "sqlite", "status": "ready",
      "size_bytes": 1_932_735_283, "table_count": 4, "parent_id": None, "user_id": None,
      "used_by": [{"kind": "project", "id": "prj_1", "name": "booking", "binding": "DB"}],
      "created_at": "2026-09-25T10:00:00Z"}
BUCKET = {"object": "bucket", "id": "bkt_1", "name": "uploads", "public": False, "size_bytes": 45_204_279_705,
          "object_count": 18204, "public_base_url": None, "used_by": [], "user_id": None,
          "created_at": "2026-09-25T10:00:00Z"}
PUBLIC = {**BUCKET, "id": "bkt_2", "name": "public-assets", "public": True,
          "public_base_url": "https://files.noclick.site/b/acme-public-assets"}


def _result(**extra):
    return {"object": "query_result", "columns": ["id", "item"], "rows": [{"id": "o1", "item": "bun"}],
            "rows_read": 1, "rows_written": 0, "last_row_id": None, "duration_ms": 1.4, **extra}


# --- databases: construction ------------------------------------------------------

def test_create_list_and_get(api, client):
    create = api.post("/v1/databases").respond(json={**DB, "id": "db_2", "name": "analytics", "engine": "postgres"})
    listed = api.get("/v1/databases").respond(json=listing(DB, next_cursor="c2"))
    api.get("/v1/databases/db_1").respond(json=DB)

    with nc.as_user("user_42"):
        analytics = nc.Database.create("analytics", engine="postgres")
    assert body(create.calls.last.request) == {"name": "analytics", "engine": "postgres"}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (analytics.engine, repr(analytics)) == ("postgres", "Database(id='db_2', name='analytics', engine='postgres')")
    nc.Database.create("orders")
    assert body(create.calls.last.request) == {"name": "orders", "engine": "sqlite"}

    page = nc.Database.list_page(engine="sqlite", user_filter=nc.ALL_USERS, limit=10)
    params = listed.calls.last.request.url.params
    assert (params["engine"], params["user_id"], params["limit"]) == ("sqlite", "all", "10")
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert page.next_cursor == "c2" and page.data[0] == nc.Database.get("db_1")
    [first] = nc.Database.list(limit=1)
    assert (first.size_bytes, first.table_count, first.used_by[0]["binding"]) == (1_932_735_283, 4, "DB")
    assert first.created_at.year == 2026
    assert nc.Database.get("db_1").name == "booking-db"


def test_from_name_finds_creates_or_says_how(api, client):
    lookup = api.get("/v1/databases").mock(side_effect=[
        httpx.Response(200, json=listing({**DB, "name": "booking-db-old"})),
        httpx.Response(200, json=listing()),
        httpx.Response(200, json=listing(DB)),
    ])
    create = api.post("/v1/databases").respond(json={**DB, "id": "db_9", "name": "orders", "engine": "postgres"})
    lazy = nc.Database.from_name("orders", create_if_missing=True, engine="postgres")
    assert lookup.call_count == 0 and lazy.name == "orders"
    assert lazy.id == "db_9"  # an exact name only: the near miss isn't it, so it's created
    assert lookup.calls[0].request.url.params["name"] == "orders"
    assert body(create.calls.last.request) == {"name": "orders", "engine": "postgres"}

    with pytest.raises(nc.NotFound, match="create_if_missing=True"):
        nc.Database.from_name("orders").hydrate()
    assert nc.Database.from_name("booking-db").engine == "sqlite" and create.call_count == 1


def test_from_name_adopts_one_created_concurrently(api, client):
    api.get("/v1/databases").respond(json=listing())
    api.post("/v1/databases").respond(409, json={"error": {
        "type": "conflict", "message": "taken", "existing_id": "db_1"}})
    api.get("/v1/databases/db_1").respond(json=DB)
    assert nc.Database.from_name("booking-db", create_if_missing=True).id == "db_1"


def test_from_name_inside_an_app_resolves_in_the_apps_own_namespace(api, client, monkeypatch):
    """A deployed app's code holds no key: from_name asks for the app's own resource of that name (a preview
    branch's own, made on first use), never the account's list."""
    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    monkeypatch.setenv("NOCLICK_DEPLOYMENT_TOKEN", "nk_dep_123")
    in_app = nc.Client(base_url="https://api.test")
    assert in_app.in_app and not client.in_app
    listed = api.get("/v1/databases").respond(json=listing())
    resolve = api.post("/v1/projects/current/resources").mock(side_effect=[
        httpx.Response(200, json={**DB, "id": "db_9", "name": "orders"}),
        httpx.Response(200, json={**BUCKET, "id": "bkt_9", "name": "uploads"}),
    ])
    assert nc.Database.from_name("orders", create_if_missing=True, engine="postgres", client=in_app).id == "db_9"
    assert nc.Bucket.from_name("uploads", client=in_app).id == "bkt_9"
    made, found = (body(call.request) for call in resolve.calls)
    assert made == {"kind": "database", "name": "orders", "create_if_missing": True, "engine": "postgres"}
    assert found == {"kind": "bucket", "name": "uploads", "create_if_missing": False}
    assert resolve.calls.last.request.headers["Authorization"] == "Bearer nk_dep_123" and listed.call_count == 0


def test_from_name_inside_an_app_asks_for_productions_rows_in_a_previews_copy(api, client, monkeypatch):
    monkeypatch.delenv("NOCLICK_API_KEY", raising=False)
    monkeypatch.setenv("NOCLICK_DEPLOYMENT_TOKEN", "nk_dep_123")
    resolve = api.post("/v1/projects/current/resources").respond(json={**DB, "id": "db_9", "name": "orders"})
    in_app = nc.Client(base_url="https://api.test")
    assert nc.Database.from_name("orders", branch_data="copy", client=in_app).id == "db_9"
    assert body(resolve.calls.last.request) == {"kind": "database", "name": "orders", "create_if_missing": False,
                                                "branch_data": "copy"}


def test_a_lazy_name_is_looked_up_once_before_it_is_used(api, client):
    lookup = api.get("/v1/databases").respond(json=listing(DB))
    run = api.post("/v1/databases/db_1/query").respond(json=_result())
    db = nc.Database.from_name("booking-db")
    db.query("select 1")
    db.query("select 2")
    assert (lookup.call_count, run.call_count) == (1, 2)


def test_console_url_opens_its_drawer(api, client, monkeypatch):
    db = nc.Database.from_id("db_1")
    assert db.console_url is None  # not the hosted API
    hosted = nc.Client(api_key="nk_live_test")
    assert nc.Database.from_id("db 1", client=hosted).console_url == (
        f"{nc.CONSOLE_BASE_URL}/resources/databases?database=db%201")
    assert nc.Bucket.from_id("bkt_1", client=hosted).console_url == f"{nc.CONSOLE_BASE_URL}/resources/storage?bucket=bkt_1"


def test_an_agent_or_toolkit_takes_a_database_as_tools(api, client):
    api.get("/v1/databases").respond(json=listing())
    created = api.post("/v1/databases").respond(json={**DB, "id": "db_9", "name": "notes"})
    agent = api.post("/v1/agents").respond(json=agent_row(id="ag_2", name="concierge"))
    bookings = nc.Database.from_id("db_1")
    notes = nc.Database.from_name("notes", create_if_missing=True)
    nc.Agent.create("concierge", instructions="hi", tools=[bookings.only("query", "schema"), notes, "search"])
    # A lazy create_if_missing database is created first, then named by id.
    assert created.call_count == 1
    assert body(agent.calls.last.request)["tools"] == [
        "database:db_1.query", "database:db_1.schema", "database:db_9", "search",
    ]

    toolkit = nc.Toolkit([bookings.only("execute"), nc.Database.from_id("db_2")])
    assert toolkit.tools == ["db_1.execute", "db_2"]
    with pytest.raises(ValueError, match="query, execute, schema, not drop"):
        bookings.only("drop")
    with pytest.raises(ValueError, match="not nothing"):
        bookings.only()


# --- databases: SQL ---------------------------------------------------------------

def test_query_runs_read_only_and_reads_rows(api, client):
    run = api.post("/v1/databases/db_1/query").respond(json=_result())
    db = nc.Database.from_id("db_1", user=USER_ID)
    result = db.query("select id, item from orders where qty > ?", [2])
    assert body(run.calls.last.request) == {
        "sql": "select id, item from orders where qty > ?", "params": [2], "read_only": True}
    assert run.calls.last.request.headers["NoClick-User"] == USER_ID
    assert isinstance(result, nc.QueryResult)
    assert [row["item"] for row in result] == ["bun"] and len(result) == 1
    assert (result.columns, result.rows_read, result.duration_ms) == (["id", "item"], 1, 1.4)
    assert "rows=" not in repr(result)  # a big result doesn't flood a REPL

    day = datetime(2026, 10, 1, 18, 30, tzinfo=timezone.utc)
    db.query("select * from bookings where starts_at >= :day", {"day": day})
    assert body(run.calls.last.request)["params"] == {"day": "2026-10-01T18:30:00+00:00"}
    db.query("select 1")
    assert body(run.calls.last.request) == {"sql": "select 1", "read_only": True}
    with pytest.raises(TypeError, match="list"):
        db.query("select ?", "oops")


def test_execute_and_batch_write(api, client):
    run = api.post("/v1/databases/db_1/query").mock(side_effect=[
        httpx.Response(200, json=_result(columns=[], rows=[], rows_written=1, last_row_id=7)),
        httpx.Response(200, json={"object": "batch_result", "results": [
            _result(rows=[], rows_written=1), _result(rows=[], rows_written=2)]}),
    ])
    db = nc.Database.from_id("db_1")
    done = db.execute("insert into orders (id, item, qty) values (?, ?, ?)", ["o1", "bun", 3])
    assert body(run.calls.last.request) == {
        "sql": "insert into orders (id, item, qty) values (?, ?, ?)", "params": ["o1", "bun", 3]}
    assert (done.rows_written, done.last_row_id, list(done)) == (1, 7, [])

    moved, freed = db.batch([("update bookings set slot = ? where id = ?", ["18:30", "b_41"]), "delete from holds"])
    assert body(run.calls.last.request) == {"statements": [
        {"sql": "update bookings set slot = ? where id = ?", "params": ["18:30", "b_41"]},
        {"sql": "delete from holds"},
    ]}
    assert (moved.rows_written, freed.rows_written) == (1, 2)


def test_quota_exceeded_says_to_branch(api, client):
    api.post("/v1/databases/db_1/query").respond(429, json={"error": {
        "type": "quota_exceeded", "message": "booking-db is at SQLite's 10 GB.",
        "next_step": "Branch it into Postgres: db.branch(name, engine='postgres')."}})
    with pytest.raises(nc.QuotaExceeded, match="engine='postgres'"):
        nc.Database.from_id("db_1").execute("insert into big values (1)")


# --- databases: schema --------------------------------------------------------------

def test_migrate_reads_a_directory_in_name_order(api, client, tmp_path):
    (tmp_path / "0002_add_slots.sql").write_text("create table slots (time text);")
    (tmp_path / "0001_init.sql").write_text("create table bookings (id text primary key);")
    (tmp_path / "README.md").write_text("not a migration")
    route = api.post("/v1/databases/db_1/migrations").respond(json={
        "object": "migration_result", "applied": ["0002_add_slots.sql"], "pending": []})
    result = nc.Database.from_id("db_1").migrate(tmp_path)
    assert body(route.calls.last.request) == {"migrations": [
        {"name": "0001_init.sql", "sql": "create table bookings (id text primary key);"},
        {"name": "0002_add_slots.sql", "sql": "create table slots (time text);"},
    ]}
    assert isinstance(result, nc.MigrationResult) and (result.applied, result.pending) == (["0002_add_slots.sql"], [])

    nc.Database.from_id("db_1").migrate(str(tmp_path), dry_run=True)
    assert body(route.calls.last.request)["dry_run"] is True


def test_migrate_takes_a_dict_and_refuses_nothing_to_run(api, client, tmp_path):
    route = api.post("/v1/databases/db_1/migrations").respond(json={"applied": [], "pending": ["0001_a.sql", "0002_b.sql"]})
    db = nc.Database.from_id("db_1")
    plan = db.migrate({"0002_b.sql": "b", "0001_a.sql": "a"}, dry_run=True)
    assert body(route.calls.last.request) == {
        "migrations": [{"name": "0001_a.sql", "sql": "a"}, {"name": "0002_b.sql", "sql": "b"}], "dry_run": True}
    assert plan.pending == ["0001_a.sql", "0002_b.sql"]
    with pytest.raises(ValueError, match="no migrations"):
        db.migrate(tmp_path)
    with pytest.raises(NotADirectoryError):
        db.migrate(tmp_path / "missing")
    assert route.call_count == 1


def test_migrate_sends_the_seed_beside_its_migrations_or_the_one_named(api, client, tmp_path):
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_init.sql").write_text("create table bookings (id text primary key);")
    route = api.post("/v1/databases/db_1/migrations").respond(json={"applied": ["(seed)"], "pending": []})
    db = nc.Database.from_id("db_1")
    db.migrate(folder)
    assert "seed" not in body(route.calls.last.request)
    (tmp_path / "seed.sql").write_text("insert into bookings values ('sample');")
    assert db.migrate(folder).applied == ["(seed)"]
    assert body(route.calls.last.request)["seed"] == "insert into bookings values ('sample');"
    (tmp_path / "demo.sql").write_text("insert into bookings values ('demo');")
    db.migrate({"0001_init.sql": "create table bookings (id text primary key);"}, seed=tmp_path / "demo.sql")
    assert body(route.calls.last.request)["seed"] == "insert into bookings values ('demo');"
    # A dry run changes nothing, so it carries no seed.
    db.migrate(folder, dry_run=True)
    assert "seed" not in body(route.calls.last.request)


def test_migrations_and_schema(api, client):
    api.get("/v1/databases/db_1/migrations").respond(json=listing(
        {"object": "migration", "name": "0001_init.sql", "applied_at": "2026-09-20T09:00:00Z", "checksum": "sha256:ab"}))
    api.get("/v1/databases/db_1/schema").respond(json=listing({
        "object": "table", "name": "bookings", "row_count": 48210, "columns": [
            {"name": "id", "type": "TEXT", "nullable": False, "primary_key": True, "default": None},
            {"name": "party_size", "type": "INTEGER", "nullable": True, "primary_key": False, "default": "2"},
        ]}))
    db = nc.Database.from_id("db_1")
    [migration] = db.migrations()
    assert (migration.name, migration.applied_at.day, migration.checksum) == ("0001_init.sql", 20, "sha256:ab")
    [table] = db.schema()
    assert isinstance(table, nc.Table) and (table.name, table.row_count) == ("bookings", 48210)
    first, second = table.columns
    assert isinstance(first, nc.Column) and (first.name, first.type, first.nullable, first.primary_key) == (
        "id", "TEXT", False, True)
    assert (second.nullable, second.default) == (True, "2")


# --- databases: time, copies, access ---------------------------------------------

def test_restore_and_branch_are_operations_that_give_a_database(api, client):
    restore = api.post("/v1/databases/db_1/restore").respond(json=operation(
        op_id="op_r", kind="database.restore", status="running"))
    api.get("/v1/operations/op_r/wait").respond(json=operation(
        op_id="op_r", kind="database.restore", status="succeeded", result=DB))
    branch = api.post("/v1/databases/db_1/branches").respond(json=operation(
        op_id="op_b", kind="database.branch", status="running"))
    api.get("/v1/operations/op_b/wait").respond(json=operation(
        op_id="op_b", kind="database.branch", status="succeeded",
        result={**DB, "id": "db_3", "name": "booking-pg", "engine": "postgres", "parent_id": "db_1"}))
    db = nc.Database.from_id("db_1")

    at = datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    op = db.restore(at=at)
    assert body(restore.calls.last.request) == {"at": "2026-09-25T08:00:00+00:00"}
    assert isinstance(op, nc.Operation) and op.wait().status == "ready"
    with pytest.raises(ValueError, match="timezone-aware"):
        db.restore(at=datetime(2026, 9, 25))

    bigger = db.branch("booking-pg", engine="postgres").wait()
    assert body(branch.calls.last.request) == {"name": "booking-pg", "engine": "postgres"}
    assert isinstance(bigger, nc.Database) and (bigger.engine, bigger.parent_id) == ("postgres", "db_1")
    db.branch("before", at="2026-09-24T00:00:00Z")
    assert body(branch.calls.last.request) == {"name": "before", "at": "2026-09-24T00:00:00Z"}


def test_an_operation_resumed_by_id_decodes_by_kind(api, client):
    api.get("/v1/operations/op_b/wait").respond(json=operation(
        op_id="op_b", kind="database.branch", status="succeeded", result={**DB, "id": "db_3"}))
    api.get("/v1/operations/op_e/wait").respond(json=operation(
        op_id="op_e", kind="bucket.export", status="succeeded",
        result={"url": "https://x/e.zip", "expires_at": "2026-10-02T10:00:00Z",
                "contents": [{"kind": "files", "name": "uploads", "detail": "An rclone config."}]}))
    assert nc.Operation.from_id("op_b").wait().id == "db_3"
    bundle = nc.Operation.from_id("op_e").wait()
    assert isinstance(bundle, nc.ExportBundle) and bundle.contents[0].kind == "files"


def test_branches_connection_url_export_and_delete(api, client):
    api.get("/v1/databases/db_1/branches").respond(json=listing(
        {**DB, "id": "db_3", "name": "booking-db-preview", "parent_id": "db_1"}))
    url = api.post("/v1/databases/db_1/connection_url").respond(json={
        "url": "postgresql://ro_7:pw@db.example.com:5432/analytics", "expires_at": "2026-09-25T11:00:00Z"})
    export = api.post("/v1/databases/db_1/export").respond(json=operation(
        op_id="op_x", kind="database.export", status="succeeded",
        result={"url": "https://x/booking-db.zip", "expires_at": "2026-10-02T10:00:00Z",
                "contents": [{"kind": "database", "name": "booking-db", "detail": "SQL dump."}],
                "remaining_dependencies": []}))
    delete = api.delete("/v1/databases/db_1").respond(json=trashed("database", "db_1", "booking-db"))
    db = nc.Database.from_id("db_1")

    [preview] = db.branches()
    assert (preview.name, preview.parent_id) == ("booking-db-preview", "db_1")
    assert db.connection_url(ttl_s=600, read_only=True).startswith("postgresql://")
    assert body(url.calls.last.request) == {"ttl_s": 600, "read_only": True}
    db.connection_url()
    assert body(url.calls.last.request) == {"ttl_s": 3600}
    bundle = db.export().wait()
    assert export.call_count == 1 and bundle.url == "https://x/booking-db.zip" and bundle.contents[0].name == "booking-db"
    assert db.delete().kind == "database"
    assert delete.call_count == 1


def test_sqlite_has_no_connection_url(api, client):
    api.post("/v1/databases/db_1/connection_url").respond(409, json={"error": {
        "type": "not_available", "message": "A SQLite database has no connection URL.",
        "next_step": "Use db.query, or branch it into Postgres."}})
    with pytest.raises(nc.NotAvailable, match="branch it into Postgres"):
        nc.Database.from_id("db_1").connection_url()


# --- buckets ----------------------------------------------------------------------

def test_bucket_create_list_and_lazy_name(api, client):
    create = api.post("/v1/buckets").respond(json=PUBLIC)
    lookup = api.get("/v1/buckets").respond(json=listing(BUCKET, PUBLIC))
    assets = nc.Bucket.create("public-assets", public=True)
    assert body(create.calls.last.request) == {"name": "public-assets", "public": True}
    assert assets.public_base_url.endswith("acme-public-assets")

    buckets = nc.Bucket.list(user_filter=nc.ALL_USERS)
    assert [b.name for b in buckets] == ["uploads", "public-assets"]
    assert lookup.calls.last.request.url.params["user_id"] == "all"
    uploads = nc.Bucket.from_name("uploads", create_if_missing=True)
    assert (uploads.object_count, uploads.public) == (18204, False) and create.call_count == 1
    assert lookup.calls.last.request.url.params["name"] == "uploads"


def test_put_get_head_remove(api, client, tmp_path):
    put = api.put("/v1/buckets/bkt_1/objects").respond(json={
        "object": "bucket_object", "key": "invoices/0042.pdf", "size": 11, "content_type": "application/pdf",
        "etag": "e1", "metadata": {"user": "acme"}, "updated_at": "2026-09-25T10:00:00Z"})
    get = api.get("/v1/buckets/bkt_1/objects").mock(side_effect=lambda request: (
        httpx.Response(200, json={"key": request.url.params["key"], "size": 11, "content_type": "application/pdf",
                                  "etag": "e1", "metadata": {}, "updated_at": "2026-09-25T10:00:00Z"})
        if request.url.params.get("view") == "metadata" else httpx.Response(200, content=b"%PDF-1.7 ..")))
    remove = api.delete("/v1/buckets/bkt_1/objects").respond(204)
    bucket = nc.Bucket.from_id("bkt_1", user=USER_ID)

    stored = bucket.put("invoices/0042.pdf", b"%PDF-1.7 ..", content_type="application/pdf", metadata={"user": "acme"})
    request = put.calls.last.request
    assert request.content == b"%PDF-1.7 .."
    assert (request.url.params["key"], request.url.params["content_type"]) == ("invoices/0042.pdf", "application/pdf")
    assert json.loads(request.url.params["metadata"]) == {"user": "acme"}
    assert request.headers["NoClick-User"] == USER_ID
    assert isinstance(stored, nc.BucketObject) and (stored.size, stored.etag, stored.metadata) == (11, "e1", {"user": "acme"})

    bucket.put("notes/hi.txt", "héllo")
    assert put.calls.last.request.content == "héllo".encode() and "content_type" not in put.calls.last.request.url.params
    (tmp_path / "r.csv").write_bytes(b"a,b\n1,2\n")
    with open(tmp_path / "r.csv", "rb") as f:
        bucket.put("reports/r.csv", f)
    assert put.calls.last.request.content == b"a,b\n1,2\n"

    assert bucket.read("invoices/0042.pdf") == b"%PDF-1.7 .."
    assert get.calls.last.request.url.params["key"] == "invoices/0042.pdf"
    info = bucket.head("invoices/0042.pdf")
    assert (info.key, info.size, info.is_folder) == ("invoices/0042.pdf", 11, False)
    bucket.remove("invoices/0042.pdf")
    assert remove.calls.last.request.url.params["key"] == "invoices/0042.pdf"


def test_objects_lists_folders_and_pages(api, client):
    route = api.get("/v1/buckets/bkt_1/objects").mock(side_effect=[
        httpx.Response(200, json=listing({"key": "invoices/2026/", "folder": True},
                                         {"key": "invoices/0042.pdf", "size": 11}, next_cursor="c2")),
        httpx.Response(200, json=listing({"key": "invoices/0043.pdf", "size": 12})),
        httpx.Response(200, json=listing({"key": "a"}, next_cursor="c9")),
    ])
    bucket = nc.Bucket.from_id("bkt_1")
    folder, first, second = bucket.objects(prefix="invoices/", delimiter="/")
    assert (folder.key, folder.is_folder, folder.size) == ("invoices/2026/", True, None)
    assert [first.key, second.key] == ["invoices/0042.pdf", "invoices/0043.pdf"]
    assert [(c.request.url.params["prefix"], c.request.url.params["delimiter"], c.request.url.params.get("cursor"))
            for c in route.calls] == [("invoices/", "/", None), ("invoices/", "/", "c2")]
    page = bucket.objects_page(limit=1)
    assert page.next_cursor == "c9" and page.data[0].key == "a"
    assert route.calls.last.request.url.params["limit"] == "1"


def test_signed_urls_and_public_urls(api, client):
    sign = api.post("/v1/buckets/bkt_1/signed_urls").respond(json={
        "url": "https://files.noclick.site/s/abc", "expires_at": "2026-09-25T11:00:00Z"})
    api.get("/v1/buckets/bkt_1").respond(json=BUCKET)
    api.get("/v1/buckets/bkt_2").respond(json=PUBLIC)
    uploads = nc.Bucket.from_id("bkt_1")
    assert uploads.signed_url("invoices/0042.pdf") == "https://files.noclick.site/s/abc"
    assert body(sign.calls.last.request) == {"key": "invoices/0042.pdf", "method": "GET", "expires_in": 3600}
    uploads.signed_url("avatars/u42.png", method="PUT", expires_in=600, content_type="image/png")
    assert body(sign.calls.last.request) == {
        "key": "avatars/u42.png", "method": "PUT", "expires_in": 600, "content_type": "image/png"}

    assert nc.Bucket.get("bkt_1").name == "uploads"  # the classmethod, next to bucket.read(key)
    assets = nc.Bucket.from_id("bkt_2")
    assert assets.url("img/logo 2.png") == "https://files.noclick.site/b/acme-public-assets/img/logo%202.png"
    with pytest.raises(nc.NotAvailable, match="private"):
        uploads.url("invoices/0042.pdf")


def test_a_file_goes_up_in_parts(api, client):
    start = api.post("/v1/buckets/bkt_1/uploads").respond(json={
        "object": "bucket_upload", "bucket_id": "bkt_1", "key": "b737/fcom.pdf", "upload_id": "up_1",
        "content_type": "application/pdf", "min_part_bytes": 5_242_880, "max_part_bytes": 5_368_709_120,
        "max_parts": 10_000})
    sign = api.post("/v1/buckets/bkt_1/uploads/part_urls").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "list", "data": [{"object": "upload_part_url", "part_number": n, "method": "PUT",
                                    "url": f"https://r2.example/p{n}"} for n in json.loads(request.content)["part_numbers"]]}))
    complete = api.post("/v1/buckets/bkt_1/uploads/complete").respond(json={
        "object": "bucket_object", "key": "b737/fcom.pdf", "size": 1_200_000_000, "content_type": "application/pdf",
        "etag": "c3-2", "metadata": {"tail": "n123"}, "updated_at": "2026-10-26T10:00:00Z", "folder": False})
    abort = api.post("/v1/buckets/bkt_1/uploads/abort").respond(json={"object": "bucket_upload", "aborted": True})
    bucket = nc.Bucket.from_id("bkt_1")

    upload = bucket.start_upload("b737/fcom.pdf", metadata={"tail": "n123"})
    assert body(start.calls.last.request) == {"key": "b737/fcom.pdf", "metadata": {"tail": "n123"}}
    assert (upload.upload_id, upload.content_type, upload.min_part_bytes, upload.max_parts) == (
        "up_1", "application/pdf", 5_242_880, 10_000)
    # More parts than one request signs go in as many requests as it takes.
    links = bucket.upload_part_urls("b737/fcom.pdf", "up_1", range(1, 2501), expires_in=900)
    assert len(links) == 2500 and links[2500] == "https://r2.example/p2500"
    assert [len(body(c.request)["part_numbers"]) for c in sign.calls] == [1000, 1000, 500]
    assert {k: v for k, v in body(sign.calls[0].request).items() if k != "part_numbers"} == {
        "key": "b737/fcom.pdf", "upload_id": "up_1", "expires_in": 900}
    # ETags as a page sends them back: part numbers as text.
    stored = bucket.complete_upload("b737/fcom.pdf", "up_1", {"2": '"e2"', "1": '"e1"'})
    assert body(complete.calls.last.request) == {"key": "b737/fcom.pdf", "upload_id": "up_1", "parts": [
        {"part_number": 2, "etag": '"e2"'}, {"part_number": 1, "etag": '"e1"'}]}
    assert (stored.size, stored.metadata) == (1_200_000_000, {"tail": "n123"})
    assert bucket.abort_upload("b737/fcom.pdf", "up_1") is None
    assert body(abort.calls.last.request) == {"key": "b737/fcom.pdf", "upload_id": "up_1"}


def test_update_credentials_export_and_delete(api, client):
    patch = api.patch("/v1/buckets/bkt_1").respond(json={**PUBLIC, "id": "bkt_1"})
    creds = api.post("/v1/buckets/bkt_1/s3_credentials").respond(json={
        "endpoint": "https://s3.example.com", "bucket": "nc-acme-uploads-7f3a", "access_key_id": "AKID",
        "secret_access_key": "SECRET", "session_token": "TOKEN", "region": "auto", "read_only": True,
        "expires_at": "2026-09-25T11:00:00Z"})
    export = api.post("/v1/buckets/bkt_1/export").respond(json=operation(op_id="op_e", kind="bucket.export",
                                                                          status="running"))
    api.get("/v1/operations/op_e/wait").respond(json=operation(
        op_id="op_e", kind="bucket.export", status="succeeded", result={"url": "https://x/uploads.zip"}))
    delete = api.delete("/v1/buckets/bkt_1").respond(json=trashed("bucket", "bkt_1", "uploads"))
    bucket = nc.Bucket.from_id("bkt_1")

    assert bucket.update(public=True) is bucket and bucket.public and body(patch.calls.last.request) == {"public": True}
    s3 = bucket.s3_credentials(read_only=True, ttl_s=900)
    assert body(creds.calls.last.request) == {"ttl_s": 900, "read_only": True}
    assert (s3.endpoint, s3.bucket, s3.secret_access_key, s3.session_token, s3.read_only) == (
        "https://s3.example.com", "nc-acme-uploads-7f3a", "SECRET", "TOKEN", True)
    assert "SECRET" not in repr(s3) and "TOKEN" not in repr(s3)
    assert bucket.export().wait().url == "https://x/uploads.zip" and export.call_count == 1

    bucket.delete()
    assert "force" not in delete.calls.last.request.url.params
    bucket.delete(force=True)
    assert delete.calls.last.request.url.params["force"] == "true"


def test_a_non_empty_bucket_needs_force(api, client):
    api.delete("/v1/buckets/bkt_1").respond(409, json={"error": {
        "type": "conflict", "message": "uploads holds 18,204 files.", "next_step": "Pass force=True to delete them too."}})
    with pytest.raises(nc.Conflict, match="force=True"):
        nc.Bucket.from_id("bkt_1").delete()


async def test_async_forms(api, client):
    api.post("/v1/databases/db_1/query").respond(json=_result())
    api.get("/v1/buckets/bkt_1/objects").respond(content=b"hi")
    result = await nc.Database.from_id("db_1").query.aio("select 1")
    assert result.rows[0]["item"] == "bun"
    assert await nc.Bucket.from_id("bkt_1").read.aio("a.txt") == b"hi"
