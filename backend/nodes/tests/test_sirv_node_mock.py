"""Exact Sirv read contracts through actual native factory and transport."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import sirv_node as R

USER = "00000000-0000-4000-8000-000000000001"
TOKEN = "synthetic-sirv-token-42"
ROOT, FOLDER, FILE = "/catalog", "/catalog/sub", "/catalog/sub/photo.jpg"
AUTH = {"credential_type": R.FAMILY, "access_token": TOKEN, "root_folder": ROOT,
    "scope": ["files:read"], "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
STAMP = "2026-10-07T00:00:00+00:00"


def args(op):
    out = {"operation": op, "root_folder": ROOT, "folder_path": FOLDER}
    if op.startswith("get_file_"):
        out["file_path"] = FILE
    return out


class World:
    def __init__(self):
        self.calls, self.after_request = [], None
        self.status, self.override = 200, None
        self.override_route = None
        self.file = {"isDirectory": False, "mtime": STAMP, "ctime": STAMP,
            "contentType": "image/jpeg", "size": 123, "meta": {"width": 10, "private": "private-provider"}}
        self.folder = {"isDirectory": True, "mtime": STAMP, "ctime": STAMP, "size": 0}
        self.catalogs = {ROOT: [{"filename": "sub", **self.folder}],
            FOLDER: [{"filename": "photo.jpg", **self.file}, {"filename": "another", **self.folder}]}
        self.following, self.next_catalogs = {}, {}
        self.metadata = {"title": "private-provider", "description": "private-provider",
            "tags": ["private-provider"], "product": {"id": "private-provider", "name": "private-provider"},
            "approval": {"approved": False, "datetime": STAMP, "comment": "private-provider"},
            "url": "https://private.invalid/capability", "secret": TOKEN}

    def handle(self, req):
        self.calls.append(req)
        assert req.method == "GET" and req.url.host == "api.sirv.com"
        assert req.headers["authorization"] == "Bearer " + TOKEN and req.headers["accept"] == "application/json"
        assert TOKEN not in str(req.url) and req.content == b""
        route = req.url.path.removeprefix("/v2/files/")
        assert route in R.ROUTES
        param = req.url.params
        if route == "readdir":
            assert set(param) <= {"dirname", "continuation"} and param["dirname"] in self.catalogs
            folder = param["dirname"]
            payload = {"contents": deepcopy(self.next_catalogs.get(folder, []) if "continuation" in param else self.catalogs[folder])}
            if folder in self.following and "continuation" not in param:
                payload["continuation"] = self.following[folder]
        else:
            assert set(param) <= {"filename", "withInherited"}
            selected = param["filename"]
            assert selected in {ROOT, FOLDER, FILE}
            if route == "stat": payload = deepcopy(self.file if selected == FILE else self.folder)
            elif route == "meta": payload = deepcopy(self.metadata)
            elif route == "meta/approval": payload = deepcopy(self.metadata["approval"])
            else:
                assert param["withInherited"] in {"true", "false"}
                payload = {"scanSpins": False, "nameSpinsAfterFolder": True, "allowListing": False, "locked": False}
        if self.after_request:
            self.after_request(req)
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "private-provider", "token": TOKEN})
        if self.override is not None and self.override_route in (None, route):
            return httpx.Response(200, content=self.override, headers={"content-type": "application/json"})
        return httpx.Response(200, json=payload, headers={"content-type": "application/json; charset=utf-8"})


@pytest.fixture
def world(monkeypatch):
    value = World()
    def client(**kw):
        assert kw == {"timeout": 25.0, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(value.handle), follow_redirects=False, trust_env=False)
    monkeypatch.setattr(R, "guarded_async_client", client)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("op", R.OPS)
async def test_each_discriminated_schema_actual_factory_execute_and_projection(world, op):
    from nodes.core.registry import NodeFactory
    adapter = TypeAdapter(R.SirvOperation)
    assert adapter.validate_python(args(op)).operation == op
    assert adapter.json_schema()["discriminator"]["propertyName"] == "operation"
    node = NodeFactory.create_node(node_id="fixture", node_type=R.NODE_TYPE,
        node_data={"config": args(op), "credentials": deepcopy(AUTH)}, sio=None, sid=None, user_id=USER)
    out = await node.execute({})
    assert out["read_completed"] is True and out["reachability_verified"] is True and out["identity_verified"] is False
    assert not any(v in json.dumps(out) for v in (TOKEN, "private-provider", "private.invalid", ROOT, FILE, "photo.jpg"))
    if op == "get_file_info": assert out["record"]["size_bytes"] == 123
    if op == "get_file_metadata": assert out["record"]["tag_count"] == 1 and out["record"]["product_fields_present"] == ["id", "name"]
    if op == "get_file_approval": assert out["record"]["approved"] is False
    if op == "get_folder_options": assert out["record"]["allowListing"] is False


@pytest.mark.asyncio
async def test_exact_continuation_is_sealed_bound_and_local_truncation_cannot_skip(world):
    world.following[FOLDER] = "provider-opaque-42"
    world.next_catalogs[FOLDER] = [{"filename": "second.jpg", **world.file}]
    first = await R.records(AUTH, args("list_folder"))
    page = first["next_page_token"]
    assert first["has_more"] is True and first["total_count"] is None
    assert "provider-opaque-42" not in page and FOLDER not in page
    second = await R.records(AUTH, {**args("list_folder"), "page_token": page, "include_paths": True})
    assert second["records"][0]["path"] == FOLDER + "/second.jpg" and second["completion_known"] is True
    assert any(req.url.params.get("continuation") == "provider-opaque-42" for req in world.calls)
    for changed, folder in [({**AUTH, "access_token": "synthetic-other-token"}, FOLDER),
        ({**AUTH, "root_folder": "/"}, FOLDER), ({**AUTH, "scope": ["files:read", "files:write"]}, FOLDER),
        ({**AUTH, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}, FOLDER),
        (AUTH, ROOT)]:
        with pytest.raises(ValueError): R.unseal_page(changed, folder, page)
    with pytest.raises(ValueError): R.unseal_page(AUTH, FOLDER, "provider-opaque-42")
    truncated = await R.records(AUTH, {**args("list_folder"), "limit": 1})
    assert truncated["local_truncated"] is True and truncated["next_page_token"] is None and truncated["completion_known"] is False


@pytest.mark.asyncio
async def test_empty_root_is_reachability_not_identity_and_paths_are_opt_in(world):
    world.catalogs[ROOT] = []
    out = await R.records(AUTH, {"operation": "list_folder", "root_folder": ROOT, "folder_path": ROOT})
    assert out["records"] == [] and out["identity_verified"] is False and out["total_count"] is None
    assert out["completion_known"] is True and ROOT not in json.dumps(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["/catalogue/sub", "/catalog/../other", "/catalog//sub", "/catalog/%2e%2e", "https://private.invalid/path", "/catalog/sub/", "/catalog/a#x"])
async def test_foreign_or_noncanonical_paths_refuse_before_provider_io(world, bad):
    with pytest.raises(ValueError): await R.records(AUTH, {**args("list_folder"), "folder_path": bad})
    assert world.calls == []


@pytest.mark.asyncio
async def test_absent_child_nested_ancestry_type_and_changed_catalog_fail(world):
    with pytest.raises(ValueError): await R.records(AUTH, {**args("get_file_info"), "file_path": "/catalog/sub/missing.jpg"})
    world.catalogs[ROOT][0]["isDirectory"] = False
    with pytest.raises(ValueError): await R.records(AUTH, args("list_folder"))
    world.catalogs[ROOT][0]["isDirectory"] = True
    def changed(req):
        if req.url.path.endswith("/meta"):
            world.catalogs[FOLDER][0]["mtime"] = "2026-10-07T00:01:00Z"
            world.after_request = None
    world.after_request = changed
    with pytest.raises(ValueError): await R.records(AUTH, args("get_file_metadata"))


@pytest.mark.asyncio
async def test_unknown_bounded_ancestry_is_not_claimed_absent(world):
    world.catalogs[FOLDER] = []
    world.following[FOLDER] = "same"
    world.next_catalogs[FOLDER] = []
    # A continuing response reaching the bound is inconclusive; not an absent-child verdict.
    original = world.handle
    def continued(req):
        result = original(req)
        if req.url.path.endswith("/readdir") and req.url.params["dirname"] == FOLDER:
            return httpx.Response(200, json={"contents": [], "continuation": "cursor-" + str(len(world.calls))})
        return result
    world.handle = continued
    with pytest.raises(RuntimeError): await R.find_child(AUTH, FOLDER, FILE, directory=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [(400, ValueError), (401, ValueError), (403, ValueError),
    (404, ValueError), (429, RuntimeError), (500, RuntimeError), (302, RuntimeError)])
async def test_static_status_taxonomy_never_reflects_wire(world, status, error):
    world.status = status
    with pytest.raises(error) as caught: await R.records(AUTH, args("list_folder"))
    assert TOKEN not in str(caught.value) and "private-provider" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,route", [(b'{}', "stat"), (b'{"contents":[],"contents":[]}', "readdir"),
    (b'{"contents":[{"filename":"../x","mtime":"2026-10-07T00:00:00Z","isDirectory":false}]}', "readdir"),
    (b'{"contents":[],"continuation":""}', "readdir"), (b'{"isDirectory":true,"mtime":1770000000}', "stat"),
    (b'{"error":"private-provider"}', "stat")])
async def test_malformed_or_unknown_metadata_is_inconclusive(world, raw, route):
    world.override = raw
    world.override_route = route
    with pytest.raises(RuntimeError):
        await R.records(AUTH, args("get_file_info" if route == "stat" else "list_folder"))


@pytest.mark.asyncio
@pytest.mark.parametrize("update", [{"credential_type": "slack_oauth"}, {"access_token": "Bearer synthetic-token"},
    {"expires_at": "2020-01-01T00:00:00Z"}, {"scope": []}, {"scope": ["files:write"]},
    {"scope": '["files:read","files:read"]'}, {"client_secret": "private-provider"}, {"base_url": "https://private.invalid"}])
async def test_raw_family_expiry_scope_and_other_auth_cannot_be_coerced(world, update):
    from nodes.core.registry import NodeFactory
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="fixture", node_type=R.NODE_TYPE,
            node_data={"config": args("list_folder"), "credentials": {**AUTH, **update}}, sio=None, sid=None, user_id=USER)
    assert world.calls == []


@pytest.mark.asyncio
async def test_actual_picker_parent_pagination_and_generic_labels(world):
    out = await R.SirvNode.load_field_options("file_path", AUTH, {"root_folder": ROOT, "folder_path": FOLDER})
    assert out["options"][0]["value"] == FILE and out["options"][0]["label"] == "File 1"
    assert out["options"][0]["metadata"] == {"root_folder": ROOT, "folder_path": FOLDER}
    with pytest.raises(ValueError):
        await R.SirvNode.load_field_options("file_path", AUTH, {"root_folder": "/other", "folder_path": FOLDER})
    with pytest.raises(ValueError):
        await R.SirvNode.load_field_options("file_path", AUTH, {"root_folder": ROOT, "folder_path": ROOT}, page_token=R.seal_page(AUTH, FOLDER, "opaque"))


@pytest.mark.asyncio
async def test_folder_witness_uses_documented_directory_reads_not_file_stat(world):
    await R.folder_witness(AUTH, FOLDER)
    assert world.calls
    assert all(req.url.path == "/v2/files/readdir" for req in world.calls)
    world.override_route = "readdir"
    world.override = b'{"isDirectory":true,"mtime":"2026-10-07T00:00:00Z"}'
    with pytest.raises(RuntimeError):
        await R.folder_witness(AUTH, ROOT)
