"""Reversible by default: the trash (a delete's item, listing, restore, purge), an operation's undo, a dict's
write log, and the earlier versions of secrets and an app's settings, against the mocked transport."""

import pytest

import noclick as nc
from platform_helpers import body, listing, operation, trash_item, trashed

DICT = {"object": "dict", "id": "dct_1", "name": "rates-cache", "key_count": 3, "size_bytes": 120, "used_by": [],
        "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
SECRET = {"object": "secret", "id": "sec_1", "name": "stripe", "keys": ["KEY"], "user_id": None, "used_by": [],
          "created_at": "2026-09-25T10:00:00Z", "updated_at": "2026-09-26T10:00:00Z"}


def test_a_delete_returns_its_trash_item_which_restores_and_purges(api, client):
    api.get("/v1/dicts", params={"name": "rates-cache"}).respond(json=listing(DICT))
    api.delete("/v1/dicts/dct_1").respond(json=trashed("dict", "dct_1", "rates-cache"))
    restore = api.post("/v1/trash/tr_1/restore").respond(json={**DICT, "restored": True})
    purge = api.delete("/v1/trash/tr_1").respond(json={"object": "trash_item", "id": "tr_1", "purged": True})

    item = nc.Dict.from_name("rates-cache").delete()
    assert isinstance(item, nc.TrashItem)
    assert (item.id, item.kind, item.resource_id, item.name, item.operation_id) == (
        "tr_1", "dict", "dct_1", "rates-cache", "op_del")
    assert item.purge_after.day == 25
    back = item.restore()
    assert (back["id"], back["restored"]) == ("dct_1", True) and restore.call_count == 1
    item.purge()
    assert purge.call_count == 1


def test_unpublishing_an_app_noclick_publishes_answers_its_trash_item(api, client):
    """Unpublishing moves the app to the trash, so it comes back by its item, as a deleted app does."""
    unpublished = {**trashed("project", "prj_1", "bakery"), "unpublished": True, "url": "https://bakery.noclick.app"}
    del unpublished["deleted"]
    unpublish = api.post("/v1/projects/prj_1/unpublish").respond(json=unpublished)
    restore = api.post("/v1/trash/tr_1/restore").respond(json={"object": "project", "id": "prj_1", "restored": True})

    item = nc.Project.from_id("prj_1").unpublish()
    assert body(unpublish.calls.last.request) == {}
    assert isinstance(item, nc.TrashItem)
    assert (item.id, item.kind, item.resource_id, item.operation_id) == ("tr_1", "project", "prj_1", "op_del")
    assert item.restore()["restored"] is True and restore.call_count == 1


def test_the_trash_lists_by_kind_and_loads_an_item_by_id(api, client):
    listed = api.get("/v1/trash").respond(json=listing(trash_item("database", "db_1", "orders"),
                                                       trash_item("bucket", "bkt_1", "uploads", item_id="tr_2")))
    api.get("/v1/trash/tr_2").respond(json=trash_item("bucket", "bkt_1", "uploads", item_id="tr_2"))
    items = nc.TrashItem.list(kind="database")
    assert listed.calls.last.request.url.params["kind"] == "database"
    assert [(i.kind, i.name) for i in items] == [("database", "orders"), ("bucket", "uploads")]
    page = nc.TrashItem.list_page(limit=2)
    assert len(page.data) == 2 and page.next_cursor is None
    lazy = nc.TrashItem.from_id("tr_2")
    assert (lazy.kind, lazy.name) == ("bucket", "uploads")


def test_an_operation_is_undone_once(api, client):
    api.get("/v1/operations/op_del").respond(json=operation(
        "op_del", kind="trash.move", status="succeeded", undoable=True, undone_at=None))
    undo = api.post("/v1/operations/op_del/undo").respond(json={
        "object": "undo", "operation_id": "op_del", "result": {**DICT, "restored": True}})
    op = nc.Operation.from_id("op_del")
    assert op.undoable is True and op.undone_at is None
    assert op.undo()["restored"] is True and undo.call_count == 1
    api.post("/v1/operations/op_del/undo").respond(409, json={"error": {
        "type": "conflict", "message": "That was already undone."}})
    with pytest.raises(nc.Conflict, match="already undone"):
        op.undo()


def test_a_dicts_history_and_putting_a_key_back(api, client):
    history = api.get("/v1/dicts/dct_1/history").respond(json=listing(
        {"object": "dict_change", "id": "12", "key": "theme", "op": "changed", "previous": "dim",
         "previous_expires_at": None, "at": "2026-09-26T10:00:00Z"},
        {"object": "dict_change", "id": "11", "key": "theme", "op": "created", "previous": None,
         "previous_expires_at": None, "at": "2026-09-26T09:00:00Z"}))
    put_back = api.post("/v1/dicts/dct_1/history/12/restore").respond(json={
        "object": "dict_item", "key": "theme", "restored": True, "value": "dim"})
    prefs = nc.Dict.from_id("dct_1")
    changes = prefs.history("theme")
    assert history.calls.last.request.url.params["key"] == "theme"
    assert [(c.op, c.previous) for c in changes] == [("changed", "dim"), ("created", None)]
    assert isinstance(changes[0], nc.DictChange) and changes[0].at.hour == 10
    prefs.restore_change(changes[0])
    prefs.restore_change("12")
    assert put_back.call_count == 2


def test_a_secrets_versions_never_carry_values(api, client):
    versions = api.get("/v1/secrets/sec_1/versions").respond(json=listing(
        {"object": "version", "id": "ver_1", "name": "stripe", "op": "changed", "replaced_at": "2026-09-26T10:00:00Z",
         "keys": ["KEY"]}))
    restore = api.post("/v1/secrets/sec_1/versions/ver_1/restore").respond(json={**SECRET, "restored": True})
    stripe = nc.Secret.from_id("sec_1")
    [version] = stripe.versions()
    assert versions.call_count == 1 and isinstance(version, nc.Version)
    assert (version.op, version.keys, version.value) == ("changed", ["KEY"], None)
    assert stripe.restore_version(version) is stripe and restore.call_count == 1


def test_an_apps_secret_and_setting_versions(api, client):
    secret_versions = api.get("/v1/projects/prj_1/secrets/STRIPE_KEY/versions").respond(json=listing(
        {"object": "version", "id": "ver_2", "name": "STRIPE_KEY", "op": "deleted", "environment": "production",
         "replaced_at": "2026-09-26T10:00:00Z"}))
    secret_back = api.post("/v1/projects/prj_1/secrets/STRIPE_KEY/versions/ver_2/restore").respond(json={
        "object": "project_secret", "name": "STRIPE_KEY", "environments": ["production"], "restored": True})
    setting_versions = api.get("/v1/projects/prj_1/settings/THEME/versions").respond(json=listing(
        {"object": "version", "id": "ver_3", "name": "THEME", "op": "changed", "value": "dark",
         "replaced_at": "2026-09-26T10:00:00Z"}))
    setting_back = api.post("/v1/projects/prj_1/settings/THEME/versions/ver_3/restore").respond(json={
        "object": "project_setting", "name": "THEME", "value": "dark", "restored": True})
    app = nc.Project.from_id("prj_1")
    [deleted] = app.secrets.versions("STRIPE_KEY", environment="production")
    assert secret_versions.calls.last.request.url.params["environment"] == "production"
    assert (deleted.op, deleted.environment) == ("deleted", "production")
    app.secrets.restore("STRIPE_KEY", deleted)
    assert secret_back.call_count == 1
    [earlier] = app.settings.versions("THEME")
    assert earlier.value == "dark" and setting_versions.call_count == 1
    assert app.settings.restore("THEME", earlier.id) == "dark" and setting_back.call_count == 1
    assert body(setting_back.calls.last.request) is None


def test_a_files_earlier_versions_and_putting_one_back(api, client):
    versions = api.get("/v1/buckets/bkt_1/objects/versions").respond(json=listing(
        {"object": "object_version", "id": "20261016T101500000000Z-changed", "key": "menu.txt", "op": "changed",
         "size": 4, "replaced_at": "2026-10-16T10:15:00+00:00"}))
    restore = api.post("/v1/buckets/bkt_1/objects/versions/restore").respond(json={
        "object": "bucket_object", "key": "menu.txt", "size": 4, "content_type": "text/plain", "etag": "e",
        "metadata": {}, "updated_at": "2026-10-16T10:20:00Z", "restored": True})
    bucket = nc.Bucket.from_id("bkt_1")
    [version] = bucket.versions("menu.txt")
    assert versions.calls.last.request.url.params["key"] == "menu.txt"
    assert isinstance(version, nc.ObjectVersion) and (version.op, version.size) == ("changed", 4)
    assert bucket.restore_version("menu.txt", version).key == "menu.txt"
    assert body(restore.calls.last.request) == {"key": "menu.txt", "version_id": version.id}
