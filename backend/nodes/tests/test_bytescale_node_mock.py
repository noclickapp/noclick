"""UNRUN native factory/connect contracts with only a synthetic HTTP boundary."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import httpx
import pytest
from nodes import bytescale_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence as evidence, credential_connect as cc

KEY = {"credential_type": p.TYPE, "api_key": "secret_synthetic_private", "account_id": "A623uY2", "folder_paths": ["/uploads"]}
FILE = {"type": "File", "filePath": "/uploads/photo 01.jpg", "size": 43, "fileUrl": "https://capability.example.test/private"}
FOLDER = {"type": "Folder", "folderPath": "/uploads", "virtual": True, "settings": {"secret": KEY["api_key"]}}

@pytest.fixture
def ensure_native_db_pool():
    yield

def create(operation, **args):
    return NodeFactory.create_node("fixture", "automation-bytescale", {"config": {"operation": operation, **args}, "credentials": deepcopy(KEY)})

@pytest.fixture
def wire(monkeypatch):
    state = {"calls": [], "responses": {}, "status": 200, "content": None, "headers": {"content-type": "application/json"}}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert method == "GET" and url.startswith(p.ROOT + "/accounts/A623uY2/")
                assert kwargs["headers"]["Authorization"] == "Bearer " + KEY["api_key"]
                assert KEY["api_key"] not in url and KEY["api_key"] not in repr(kwargs)
                assert "json" not in kwargs and "data" not in kwargs
                endpoint = url.split("/accounts/A623uY2/", 1)[1]
                query = deepcopy(kwargs["params"])
                state["calls"].append((endpoint, query))
                if endpoint in state["responses"]:
                    payload = state["responses"][endpoint]
                    if callable(payload): payload = payload(query)
                elif endpoint == "folders/list":
                    payload = {"folder": FOLDER, "items": [FILE], "cursor": FILE["filePath"], "isPaginationComplete": True}
                elif endpoint == "folders":
                    payload = FOLDER
                elif endpoint == "files/details":
                    payload = {**FILE, "accountId": KEY["account_id"], "mime": "image/jpeg", "originalFileName": None, "metadata": {"private": KEY["api_key"]}, "tags": ["private-tag"]}
                else:
                    raise AssertionError("Undocumented endpoint")
                yield httpx.Response(state["status"], content=state["content"] if state["content"] is not None else json.dumps(payload).encode(), headers=state["headers"], request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


def test_native_schema_and_visible_only_credential():
    schema = p.BytescaleNode.get_config_schema()
    refs = schema["properties"]["config"].get("oneOf") or schema["properties"]["config"]["anyOf"]
    actual = {schema["$defs"][ref["$ref"].rsplit("/", 1)[1]]["properties"]["operation"]["const"] for ref in refs}
    assert actual == p.OPERATIONS == {"list_folder", "get_folder_details", "get_file_details"}
    assert not any(name in schema.get("properties", {}) for name in ("url", "method", "query", "headers"))
    visible = {k: v for k, v in KEY.items() if k != "credential_type"}
    shaped = p.BytescaleSecretAPIKeyCredential.model_validate(visible).model_dump(exclude_unset=True)
    assert shaped == KEY and KEY["api_key"] not in repr(p.guard(KEY))


@pytest.mark.parametrize("change", [{"credential_type": "foreign"}, {"api_key": "public_upload_key"}, {"api_key": "Bearer secret_private"}, {"account_id": "bad/path"}, {"folder_paths": ["/uploads/*"]}, {"folder_paths": ["/uploads", "/uploads"]}, {"folder_paths": ["/uploads/../other"]}])
def test_invalid_credential_has_no_secret_diagnostic(change):
    with pytest.raises(ValueError) as error:
        p.guard({**KEY, **change})
    assert KEY["api_key"] not in str(error.value)


@pytest.mark.asyncio
async def test_real_connect_probe_is_reachability_only(wire, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", evidence.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=p.TYPE, credential_data={k: v for k, v in KEY.items() if k != "credential_type"}, user_id="fixture", probe=True)
    assert verdict.ok and verdict.credential_data == KEY
    assert verdict.evidence.reachable is True
    assert p.BytescaleNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.answers_field is None and verdict.evidence.account_label is None
    assert len(wire["calls"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(p.OPERATIONS))
async def test_real_factory_closed_three_metadata_routes(wire, operation):
    args = {"file_path": FILE["filePath"]} if operation == "get_file_details" else {}
    result = await create(operation, **args).execute({})
    serialized = json.dumps(result)
    assert not any(private in serialized for private in (KEY["api_key"], FILE["filePath"], FILE["fileUrl"], "private-tag"))
    if operation == "list_folder":
        assert result["items"] == [{"type": "File", "size": 43}]
        assert result["total"] is None and result["is_pagination_complete"] is True
        assert not result["principal_identity_verified"] and not result["account_ownership_verified"]
        assert wire["calls"] == [("folders/list", {"folderPath": "/uploads", "limit": 1}), ("folders/list", {"folderPath": "/uploads", "limit": 20})]
    elif operation == "get_folder_details":
        assert result == {"type": "Folder", "virtual": True}
        assert wire["calls"][-1] == ("folders", {"folderPath": "/uploads"})
    else:
        assert result == {"type": "File", "size": 43, "mime": "image/jpeg"}
        assert wire["calls"][-1] == ("files/details", {"filePath": FILE["filePath"]})


@pytest.mark.asyncio
async def test_documented_empty_folder_metadata_and_nullable_file_name(wire):
    wire["responses"]["folders"] = {}
    assert await create("get_folder_details").execute({}) == {"type": "Folder", "settings_configured": False, "metadata_available": False}
    result = await create("get_file_details", file_path=FILE["filePath"], include_paths_and_names=True).execute({})
    assert result["path"] == FILE["filePath"] and result["original_file_name"] is None
    assert "fileUrl" not in result and "metadata" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"folder_path": "/uploads-other"}, {"folder_path": "/uploads", "file_path": "/other/file.jpg"}])
async def test_foreign_root_or_direct_parent_denied_without_http(wire, args):
    operation = "get_file_details" if "file_path" in args else "list_folder"
    with pytest.raises(ValueError): await create(operation, **args).execute({})
    assert wire["calls"] == []


@pytest.mark.asyncio
async def test_absent_parent_member_prevents_point_read(wire):
    wire["responses"]["folders/list"] = {"folder": FOLDER, "items": [], "cursor": "/uploads/missing", "isPaginationComplete": True}
    with pytest.raises(ValueError, match="absent"): await create("get_file_details", file_path=FILE["filePath"]).execute({})
    assert all(endpoint == "folders/list" for endpoint, _ in wire["calls"])


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("accountId", "B623uY2"), ("filePath", "/uploads/foreign.jpg")])
async def test_point_record_must_match_account_and_path(wire, field, value):
    wire["responses"]["files/details"] = {**FILE, "accountId": KEY["account_id"], "mime": "image/jpeg", field: value}
    with pytest.raises(ValueError, match="different account"): await create("get_file_details", file_path=FILE["filePath"]).execute({})


@pytest.mark.asyncio
async def test_short_incomplete_page_encrypted_continuation_and_exact_cursor(wire):
    def response(query):
        if query["limit"] == 1:
            return {"folder": FOLDER, "items": [], "cursor": "/uploads/witness", "isPaginationComplete": True}
        return {"folder": FOLDER, "items": [] if "cursor" not in query else [FILE], "cursor": "/uploads/next private" if "cursor" not in query else FILE["filePath"], "isPaginationComplete": "cursor" in query}
    wire["responses"]["folders/list"] = response
    first = await create("list_folder").execute({})
    token = first["next_page_token"]
    assert first["count"] == 0 and first["is_pagination_complete"] is False
    assert token and all(s not in token for s in (KEY["api_key"], "/uploads", "next private"))
    second = await create("list_folder", page_token=token).execute({})
    assert second["next_page_token"] is None and second["count"] == 1
    assert wire["calls"][-1][1]["cursor"] == "/uploads/next private"
    for changed in ({"limit": 21}, {"include_paths_and_names": True}):
        wire["calls"].clear()
        with pytest.raises(ValueError, match="continuation"): await create("list_folder", page_token=token, **changed).execute({})
        assert wire["calls"] == []
    wire["calls"].clear()
    with pytest.raises(ValueError, match="continuation"): await create("list_folder", page_token=token[:-2] + "xx").execute({})
    assert wire["calls"] == []
    with pytest.raises(ValueError, match="continuation"):
        p.continuation(p.guard({**KEY, "api_key": "secret_changed_private"}), token, {"mode": "list_folder", "folder": "/uploads", "limit": 20, "include_paths": False})


@pytest.mark.asyncio
async def test_native_page_cap_does_not_invent_completion(wire):
    binding = {"mode": "list_folder", "folder": "/uploads", "limit": 20, "include_paths": False}
    token = p.next_token(p.guard(KEY), binding, "/uploads/previous", [], 9)
    wire["responses"]["folders/list"] = lambda q: {"folder": FOLDER, "items": [], "cursor": "/uploads/current", "isPaginationComplete": q["limit"] == 1}
    result = await create("list_folder", page_token=token).execute({})
    assert result["local_limit_reached"] and result["next_page_token"] is None
    assert result["is_pagination_complete"] is False and result["total"] is None


@pytest.mark.asyncio
async def test_picker_string_ids_private_labels_and_parent_required(wire):
    roots = await p.BytescaleNode.load_field_options("folder_path", KEY)
    assert roots["options"] == [{"value": "/uploads", "label": "Allowed folder 1"}]
    files = await p.BytescaleNode.load_field_options("file_path", KEY, {"folder_path": "/uploads"})
    assert files["options"] == [{"value": FILE["filePath"], "label": "File 1"}]
    wire["calls"].clear()
    with pytest.raises(ValueError, match="parent"): await p.BytescaleNode.load_field_options("file_path", KEY)
    assert wire["calls"] == []


@pytest.mark.parametrize("change", [{"isPaginationComplete": 1}, {"cursor": None}, {"items": [FILE, FILE]}, {"items": [{**FILE, "size": True}]}, {"items": [{**FILE, "filePath": "/foreign/file"}]}, {"folder": {**FOLDER, "folderPath": "/foreign"}}])
def test_exact_page_shape_and_parent_guards(change):
    with pytest.raises(ValueError): p.page({"folder": FOLDER, "items": [FILE], "cursor": FILE["filePath"], "isPaginationComplete": True, **change}, "/uploads", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,headers", [(403, None, None), (429, None, None), (302, None, {"location": "https://elsewhere.example.test"}), (200, b'{"items":[],"items":[]}', None), (200, b'{"x":NaN}', None), (200, b'private provider body', {"content-type": "text/plain"})])
async def test_refusal_and_invalid_transport_are_sanitized_without_retry(wire, status, content, headers):
    wire.update(status=status, content=content)
    if headers is not None: wire["headers"] = headers
    with pytest.raises(ValueError) as error: await create("list_folder").execute({})
    assert len(wire["calls"]) == 1
    assert KEY["api_key"] not in str(error.value) and "private provider body" not in str(error.value)


@pytest.mark.asyncio
async def test_nested_folder_requires_each_current_parent_before_details(wire):
    child = {"type": "Folder", "folderPath": "/uploads/child", "virtual": False}
    def catalog(query):
        selected = query["folderPath"]
        return {"folder": FOLDER if selected == "/uploads" else child, "items": [child] if selected == "/uploads" else [], "cursor": child["folderPath"], "isPaginationComplete": True}
    wire["responses"]["folders/list"] = catalog
    wire["responses"]["folders"] = child
    result = await create("get_folder_details", folder_path=child["folderPath"]).execute({})
    assert result == {"type": "Folder", "virtual": False}
    assert wire["calls"] == [("folders/list", {"folderPath": "/uploads", "limit": 1}), ("folders/list", {"folderPath": "/uploads", "limit": 100}), ("folders", {"folderPath": "/uploads/child"})]
    wire["calls"].clear()
    with pytest.raises(ValueError, match="four-level"): await create("list_folder", folder_path="/uploads/a/b/c/d/e").execute({})
    assert wire["calls"] == []


@pytest.mark.asyncio
async def test_membership_is_bounded_even_with_empty_progressing_pages(wire):
    count = 0
    def catalog(query):
        nonlocal count
        count += 1
        return {"folder": FOLDER, "items": [], "cursor": f"/uploads/cursor-{count}", "isPaginationComplete": False}
    wire["responses"]["folders/list"] = catalog
    with pytest.raises(ValueError, match="ten-page"): await create("get_file_details", file_path=FILE["filePath"]).execute({})
    assert len(wire["calls"]) == 11 and all(endpoint == "folders/list" for endpoint, _ in wire["calls"])


@pytest.mark.asyncio
async def test_response_body_bound_and_cursor_repetition(wire):
    wire["content"] = b'x' * (p.MAX_BYTES + 1)
    with pytest.raises(ValueError): await create("list_folder").execute({})
    assert len(wire["calls"]) == 1
    wire["calls"].clear()
    wire["content"] = None
    wire["responses"]["folders/list"] = lambda q: {"folder": FOLDER, "items": [], "cursor": "/uploads/repeat", "isPaginationComplete": q["limit"] == 1}
    first = await create("list_folder").execute({})
    with pytest.raises(ValueError, match="repeated"): await create("list_folder", page_token=first["next_page_token"]).execute({})
