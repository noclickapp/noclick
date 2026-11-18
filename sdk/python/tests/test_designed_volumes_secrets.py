"""Volumes and secrets, and mounting them into sandboxes and
agents: the routes, bodies and parsed results the client sends and reads, against the
mocked transport."""

import httpx
import pytest

import noclick as nc
from platform_helpers import USER_ID, agent_row, body, listing, operation

VOL_ID = "4c8e1f0a-6b3d-4a92-9e57-1d2f8b0c7a36"
SECRET_ID = "2a7f0c3e-9d1b-4e6a-8c5f-3b0e7d2a9c14"
VOLUME = {"object": "volume", "id": VOL_ID, "name": "datasets", "size_bytes": 13_314_398_618, "file_count": 1840,
          "mounted_by": [{"kind": "agent", "id": "ag_1", "name": "assistant", "path": "/data"}],
          "user_id": None, "created_at": "2026-09-25T10:00:00Z"}
SECRET = {"object": "secret", "id": SECRET_ID, "name": "openai", "keys": ["OPENAI_API_KEY"], "user_id": None,
          "used_by": [{"kind": "agent", "id": "ag_1", "name": "assistant", "binding": None}],
          "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-20T10:00:00Z"}
SANDBOX = {"object": "sandbox", "id": "sb_1", "status": "running", "image": "python", "user_id": None,
           "volumes": {"/data": VOL_ID}, "secret_ids": [SECRET_ID], "created_at": "2026-09-25T10:00:00Z"}


def _entry(path, kind="file", size=12):
    return {"object": "volume_entry", "path": path, "type": kind, "size": size if kind == "file" else None,
            "updated_at": "2026-09-25T10:00:00Z"}


# --- volumes: construction -----------------------------------------------------------

def test_volume_create_list_and_get(api, client):
    create = api.post("/v1/volumes").respond(json={**VOLUME, "id": "vol_2", "name": "workbench", "user_id": USER_ID})
    listed = api.get("/v1/volumes").respond(json=listing(VOLUME, next_cursor="c2"))
    api.get(f"/v1/volumes/{VOL_ID}").respond(json=VOLUME)

    with nc.as_user("user_42"):
        work = nc.Volume.create("workbench")
    assert body(create.calls.last.request) == {"name": "workbench"}
    assert create.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (work.user_id, repr(work)) == (USER_ID, "Volume(id='vol_2', name='workbench')")

    page = nc.Volume.list_page(user_filter=nc.ALL_USERS, limit=10)
    params = listed.calls.last.request.url.params
    assert (params["user_id"], params["limit"]) == ("all", "10")
    assert "NoClick-User" not in listed.calls.last.request.headers
    assert page.next_cursor == "c2" and page.data[0] == nc.Volume.get(VOL_ID)
    [first] = nc.Volume.list(limit=1)
    assert (first.size_bytes, first.file_count, first.created_at.year) == (13_314_398_618, 1840, 2026)
    assert first.mounted_by == [{"kind": "agent", "id": "ag_1", "name": "assistant", "path": "/data"}]


def test_volume_from_name_prefers_the_users_own_and_creates_only_its_own(api, client):
    theirs = {**VOLUME, "id": "vol_t", "user_id": USER_ID}
    lookup = api.get("/v1/volumes").mock(side_effect=[
        httpx.Response(200, json=listing(VOLUME, theirs)),   # the account's and the user's, same name
        httpx.Response(200, json=listing(VOLUME)),           # only the account's
        httpx.Response(200, json=listing(VOLUME)),
        httpx.Response(200, json=listing()),
    ])
    create = api.post("/v1/volumes").respond(json={**theirs, "id": "vol_new"})

    with nc.as_user(USER_ID):
        assert nc.Volume.from_name("datasets").id == "vol_t"
        assert nc.Volume.from_name("datasets").id == VOL_ID          # a user mounts the account's
        assert nc.Volume.from_name("datasets", create_if_missing=True).id == "vol_new"   # a definition is its own
    assert lookup.calls[0].request.url.params["name"] == "datasets"
    assert body(create.calls.last.request) == {"name": "datasets"}
    with pytest.raises(nc.NotFound, match="create_if_missing=True"):
        nc.Volume.from_name("datasets").hydrate()


def test_volume_from_name_adopts_one_created_concurrently(api, client):
    api.get("/v1/volumes").respond(json=listing())
    api.post("/v1/volumes").respond(409, json={"error": {"type": "conflict", "message": "taken", "existing_id": VOL_ID}})
    api.get(f"/v1/volumes/{VOL_ID}").respond(json=VOLUME)
    assert nc.Volume.from_name("datasets", create_if_missing=True).id == VOL_ID


def test_volume_console_url(api, client):
    assert nc.Volume.from_id(VOL_ID).console_url is None  # not the hosted API
    hosted = nc.Client(api_key="nk_live_test")
    assert nc.Volume.from_id("vol 1", client=hosted).console_url == f"{nc.CONSOLE_BASE_URL}/resources/volumes?volume=vol%201"
    assert nc.Secret.from_id("sec_1", client=hosted).console_url == f"{nc.CONSOLE_BASE_URL}/resources/secrets?secret=sec_1"


# --- volumes: files --------------------------------------------------------------------

def test_volume_write_read_listdir_remove_and_copy(api, client):
    lookup = api.get("/v1/volumes").respond(json=listing(VOLUME))
    files = f"/v1/volumes/{VOL_ID}/files"
    put = api.put(files).respond(json=_entry("/raw/orders.csv", size=17))
    get = api.get(files).mock(side_effect=lambda request: (
        httpx.Response(200, json=listing(_entry("/raw", "directory"), _entry("/raw/orders.csv"), next_cursor="c2"))
        if request.url.params.get("view") == "list" and "cursor" not in request.url.params
        else httpx.Response(200, json=listing(_entry("/raw/items.csv")))
        if request.url.params.get("view") == "list"
        else httpx.Response(200, content=b"id,total\no_1,42\n")))
    delete = api.delete(files).respond(204)
    copy = api.post(f"/v1/volumes/{VOL_ID}/copy").respond(json=_entry("/archive/orders.csv"))

    vol = nc.Volume.from_name("datasets")
    entry = vol.write("/raw/orders.csv", "id,total\no_1,42\n")
    assert isinstance(entry, nc.VolumeEntry) and (entry.path, entry.type, entry.size) == ("/raw/orders.csv", "file", 17)
    assert put.calls.last.request.url.params["path"] == "/raw/orders.csv"
    assert put.calls.last.request.content == b"id,total\no_1,42\n"
    assert lookup.call_count == 1  # the name is looked up once, then the id is used

    assert vol.read("/raw/orders.csv") == b"id,total\no_1,42\n"
    assert dict(get.calls.last.request.url.params) == {"path": "/raw/orders.csv"}

    entries = vol.listdir("/raw", recursive=True)
    assert [(e.path, e.type, e.size) for e in entries] == [
        ("/raw", "directory", None), ("/raw/orders.csv", "file", 12), ("/raw/items.csv", "file", 12)]
    params = get.calls[-2].request.url.params
    assert (params["path"], params["view"], params["recursive"]) == ("/raw", "list", "true")
    assert get.calls.last.request.url.params["cursor"] == "c2"

    page = vol.listdir_page(limit=2)
    params = get.calls.last.request.url.params
    assert (params["path"], params["view"], params["limit"], "recursive" in params) == ("/", "list", "2", False)
    assert page.next_cursor == "c2" and page.data[1].path == "/raw/orders.csv"

    vol.remove("/raw/orders.csv")
    assert dict(delete.calls.last.request.url.params) == {"path": "/raw/orders.csv"}
    vol.remove("/tmp", recursive=True)
    assert dict(delete.calls.last.request.url.params) == {"path": "/tmp", "recursive": "true"}

    copied = vol.copy("/raw/orders.csv", "/archive/orders.csv")
    assert body(copy.calls.last.request) == {"src": "/raw/orders.csv", "dst": "/archive/orders.csv"}
    assert copied.path == "/archive/orders.csv"
    with pytest.raises(TypeError, match="bytes, text or a binary file"):
        vol.write("/x", 42)


def test_volume_export_and_delete(api, client):
    export = api.post(f"/v1/volumes/{VOL_ID}/export").respond(json=operation(
        op_id="op_v", kind="volume.export", status="running"))
    api.get("/v1/operations/op_v/wait").respond(json=operation(
        op_id="op_v", kind="volume.export", status="succeeded",
        result={"url": "https://x/datasets.tar.gz", "contents": [{"kind": "files", "name": "datasets", "detail": "An archive"}]}))
    delete = api.delete(f"/v1/volumes/{VOL_ID}").respond(409, json={"error": {
        "type": "conflict", "message": "The assistant agent mounts datasets at /data."}})
    vol = nc.Volume.from_id(VOL_ID)

    bundle = vol.export().wait()
    assert isinstance(bundle, nc.ExportBundle) and bundle.url == "https://x/datasets.tar.gz"
    assert export.call_count == 1 and bundle.contents[0].kind == "files"
    assert nc.Operation.from_id("op_v").wait().url == "https://x/datasets.tar.gz"   # resumed anywhere, still typed
    with pytest.raises(nc.Conflict, match="mounts datasets"):
        vol.delete()
    assert delete.call_count == 1


# --- secrets ---------------------------------------------------------------------------

def test_secret_create_list_and_get_never_carry_values_back(api, client):
    create = api.post("/v1/secrets").respond(json={**SECRET, "id": "sec_2", "name": "shipping", "keys": ["SHIPPING_API_KEY"]})
    listed = api.get("/v1/secrets").respond(json=listing(SECRET))
    api.get(f"/v1/secrets/{SECRET_ID}").respond(json=SECRET)

    shipping = nc.Secret.create("shipping", {"SHIPPING_API_KEY": "shp_live_1"})
    assert body(create.calls.last.request) == {"name": "shipping", "values": {"SHIPPING_API_KEY": "shp_live_1"}}
    assert repr(shipping) == "Secret(id='sec_2', name='shipping', keys=['SHIPPING_API_KEY'])"
    with nc.as_user("acme"):
        nc.Secret.create("acme-erp")
    assert body(create.calls.last.request) == {"name": "acme-erp"}
    assert create.calls.last.request.headers["NoClick-User"] == "acme"

    page = nc.Secret.list_page(user_filter=nc.ALL_USERS, limit=20)
    assert listed.calls.last.request.url.params["user_id"] == "all" and page.data[0].name == "openai"
    openai = nc.Secret.get(SECRET_ID)
    assert (openai.keys, openai.updated_at.day, openai.used_by[0]["name"]) == (["OPENAI_API_KEY"], 20, "assistant")
    assert [s.id for s in nc.Secret.list()] == [SECRET_ID]
    with pytest.raises(TypeError, match="must be a string"):
        nc.Secret.create("bad", {"PORT": 8080})


def test_secret_from_name_creates_with_values_and_converges_them(api, client):
    lookup = api.get("/v1/secrets").mock(side_effect=[
        httpx.Response(200, json=listing()), httpx.Response(200, json=listing(SECRET)),
        httpx.Response(200, json=listing(SECRET))])
    create = api.post("/v1/secrets").respond(json=SECRET)
    patch = api.patch(f"/v1/secrets/{SECRET_ID}").respond(json=SECRET)

    made = nc.Secret.from_name("openai", values={"OPENAI_API_KEY": "sk-1"}, create_if_missing=True)
    assert lookup.call_count == 0 and made.id == SECRET_ID
    assert body(create.calls.last.request) == {"name": "openai", "values": {"OPENAI_API_KEY": "sk-1"}}
    # A rotated value in the code reaches the existing secret, merged (keys it doesn't name are kept).
    again = nc.Secret.from_name("openai", values={"OPENAI_API_KEY": "sk-2"}, create_if_missing=True)
    assert again.keys == ["OPENAI_API_KEY"] and create.call_count == 1
    assert body(patch.calls.last.request) == {"values": {"OPENAI_API_KEY": "sk-2"}}
    # Declared without values, it's used as it is.
    nc.Secret.from_name("openai", create_if_missing=True).hydrate()
    assert patch.call_count == 1


def test_secret_update_merges_or_replaces(api, client):
    patch = api.patch(f"/v1/secrets/{SECRET_ID}").respond(json={**SECRET, "keys": ["ERP_PASSWORD", "ERP_USER"]})
    erp = nc.Secret.from_id(SECRET_ID, user="acme")

    assert erp.update({"ERP_USER": "svc", "ERP_TOKEN": None}) is erp
    assert body(patch.calls.last.request) == {"values": {"ERP_USER": "svc", "ERP_TOKEN": None}}
    assert patch.calls.last.request.headers["NoClick-User"] == "acme"
    erp.update({"ERP_USER": "svc", "ERP_PASSWORD": "pw"}, replace=True)
    assert body(patch.calls.last.request) == {"values": {"ERP_USER": "svc", "ERP_PASSWORD": "pw"}, "replace": True}
    assert erp.keys == ["ERP_PASSWORD", "ERP_USER"]
    with pytest.raises(TypeError, match="must be a string"):
        erp.update({"ERP_TOKEN": None}, replace=True)   # replacing states every value


def test_secret_delete_refused_while_used(api, client):
    api.get("/v1/secrets").respond(json=listing({**SECRET, "name": "shipping", "id": "sec_2"}))
    delete = api.delete("/v1/secrets/sec_2").respond(409, json={"error": {
        "type": "conflict", "message": "The booking app binds shipping as SHIPPING.", "next_step": 'app.unbind("SHIPPING")'}})
    with pytest.raises(nc.Conflict, match="binds shipping"):
        nc.Secret.from_name("shipping").delete()
    assert delete.call_count == 1


# --- mounting into sandboxes and agents ------------------------------------------------

def test_sandbox_create_mounts_volumes_and_passes_secrets(api, client):
    vol_lookup = api.get("/v1/volumes").respond(json=listing(VOLUME))
    secret_lookup = api.get("/v1/secrets").respond(json=listing({**SECRET, "id": "sec_2", "name": "shipping"}))
    create = api.post("/v1/sandboxes").respond(json=SANDBOX)

    with nc.as_user("user_42"):
        sb = nc.Sandbox.create(
            volumes={"/work": nc.Volume.from_id("vol_9"), "/data": "datasets"},
            secrets=[nc.Secret.from_id(SECRET_ID), "shipping", "0b6e2d4f-8a1c-4f3e-9d7b-5c2a1e0f8b94"],
        )
    assert body(create.calls.last.request) == {
        "volumes": {"/data": VOL_ID, "/work": "vol_9"},
        "secret_ids": [SECRET_ID, "sec_2", "0b6e2d4f-8a1c-4f3e-9d7b-5c2a1e0f8b94"],
    }
    # Names are looked up where the sandbox runs; ids go as they are.
    assert vol_lookup.calls.last.request.headers["NoClick-User"] == "user_42"
    assert secret_lookup.calls.last.request.url.params["name"] == "shipping"
    assert (sb.volumes, sb.secret_ids) == ({"/data": VOL_ID}, [SECRET_ID])

    nc.Sandbox.create(secrets=nc.Secret.from_id(SECRET_ID), volumes={"/data": VOL_ID})
    assert body(create.calls.last.request) == {"volumes": {"/data": VOL_ID}, "secret_ids": [SECRET_ID]}
    nc.Sandbox.create(image="python")
    assert body(create.calls.last.request) == {"image": "python"}
    with pytest.raises(TypeError, match="maps a mount path"):
        nc.Sandbox.create(volumes=[VOL_ID])
    with pytest.raises(TypeError, match="Mount a noclick.Volume"):
        nc.Sandbox.create(volumes={"/data": 42})
    with pytest.raises(TypeError, match="noclick.Secret"):
        nc.Sandbox.create(secrets=[42])


def test_agent_create_and_from_name_converge_volumes_and_secrets(api, client):
    api.get("/v1/volumes").respond(json=listing(VOLUME))
    api.get("/v1/secrets").respond(json=listing(SECRET))
    create = api.post("/v1/agents").respond(json=agent_row(id="ag_2", name="analyst", volumes={"/data": VOL_ID},
                                                           secret_ids=[SECRET_ID]))
    analyst = nc.Agent.create("analyst", instructions="hi", volumes={"/data": "datasets"}, secrets=["openai"])
    sent = body(create.calls.last.request)
    assert (sent["volumes"], sent["secret_ids"]) == ({"/data": VOL_ID}, [SECRET_ID])
    assert (analyst.volumes, analyst.secret_ids) == ({"/data": VOL_ID}, [SECRET_ID])

    existing = agent_row(id="ag_1", name="assistant", instructions="hi", volumes={"/data": VOL_ID}, secret_ids=[])
    api.get("/v1/agents").respond(json=listing(existing))
    patch = api.patch("/v1/agents/ag_1").respond(json={**existing, "secret_ids": [SECRET_ID]})
    assistant = nc.Agent.from_name(
        "assistant", create_if_missing=True, instructions="hi",
        volumes={"/data": nc.Volume.from_name("datasets")}, secrets=[nc.Secret.from_name("openai")],
    )
    assert assistant.secret_ids == [SECRET_ID]
    assert body(patch.calls.last.request) == {"secret_ids": [SECRET_ID]}   # the mount already matched

    same = nc.Agent.from_name("assistant", create_if_missing=True, instructions="hi", volumes={"/data": VOL_ID})
    assert same.volumes == {"/data": VOL_ID} and patch.call_count == 1
