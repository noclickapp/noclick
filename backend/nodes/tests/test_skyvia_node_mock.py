"""Skyvia factory, connect, contract and paging fixtures with synthetic HTTP."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import skyvia_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence, credential_connect

KEY = {"credential_type": "skyvia_api_token", "api_token": "synthetic-skyvia-private-token", "workspace_ids": [101]}
RESOURCE = {"connections": {"id": 301, "name": "private business connection", "connector": "SQL Server", "type": "Direct"}, "integrations": {"id": 302, "name": "private business integration", "type": "import", "scheduled": True}, "backups": {"id": 303, "name": "private business backup", "scheduled": False}, "automations": {"id": 304, "name": "private business automation", "triggerType": "Manual"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


def create(operation, **arguments):
    return NodeFactory.create_node("fixture", "automation-skyvia", {"config": {"operation": operation, **arguments}, "credentials": deepcopy(KEY)})


@pytest.fixture
def wire(monkeypatch):
    state = {"calls": [], "responses": {}, "status": 200, "content": None, "headers": {"content-type": "application/json"}, "after": None, "workspace_ids": [101]}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert method == "GET" and url.startswith(p.ROOT + "/workspaces")
                assert kwargs["headers"]["Authorization"] == KEY["api_token"]
                assert not kwargs["headers"]["Authorization"].startswith("Bearer ")
                assert KEY["api_token"] not in url and KEY["api_token"] not in repr(kwargs)
                assert "json" not in kwargs and "data" not in kwargs
                path = url.removeprefix(p.ROOT)
                state["calls"].append((path, deepcopy(kwargs["params"])))
                if path in state["responses"]:
                    payload = state["responses"][path]
                    if callable(payload): payload = payload(kwargs["params"])
                elif path == "/workspaces":
                    payload = [{"id": v, "name": "private workspace", "isPersonal": False, "credential": KEY["api_token"]} for v in state["workspace_ids"]]
                elif path == "/workspaces/101":
                    payload = {"id": 101, "name": "private workspace", "isPersonal": False}
                else:
                    parts = path.split("/"); kind = parts[3]
                    item = {**RESOURCE[kind], "settings": {"password": KEY["api_token"]}, "key": KEY["api_token"], "runtimeError": "private error", "query": "private SQL", "log": "private log", "url": "https://capability.example.test/private"}
                    payload = {"data": [item], "hasMore": False} if len(parts) == 4 else item
                response = httpx.Response(state["status"], content=state["content"] if state["content"] is not None else json.dumps(payload).encode(), headers=state["headers"], request=httpx.Request(method, url))
                if state["after"]: await state["after"]()
                yield response
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


def test_real_native_schema_has_exact_ten_actions_and_no_raw_or_mutating_escape():
    schema = p.SkyviaNode.get_config_schema()
    refs = schema["properties"]["config"].get("oneOf") or schema["properties"]["config"].get("anyOf")
    definitions = [schema["$defs"][ref["$ref"].split("/")[-1]] for ref in refs]
    assert {d["properties"]["operation"]["const"] for d in definitions} == p.OPERATIONS
    assert len(definitions) == 10
    assert all(d["properties"]["operation"]["x-is-trigger"] is False for d in definitions)
    assert all(not ({"url", "method", "body", "query", "sql", "settings"} & set(d["properties"])) for d in definitions)
    credential = schema["$defs"]["SkyviaAPITokenCredential"]
    assert credential["properties"]["api_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in credential and "x-oauth-scopes" not in credential
    assert credential["properties"]["workspace_ids"]["minItems"] == 1
    assert credential["properties"]["workspace_ids"]["maxItems"] == 50
    for d in definitions:
        for name, field in d["properties"].items():
            if name in p.KINDS:
                assert field["x-dynamic-options"]["depends_on"] == ["workspace_id"]


@pytest.mark.parametrize("value", [True, -1, 1.5, "1.0", "1e2", "+1", "01", "-0", "2147483648"])
def test_actual_native_id_validation_rejects_noncanonical_or_out_of_bounds(value):
    verdict = p.SkyviaNode.validate_config({"config": {"operation": "get_workspace", "workspace_id": value}, "credentials": KEY})
    assert verdict["valid"] is False
    assert KEY["api_token"] not in repr(verdict)


def test_visible_only_credential_connect_shape_and_actual_picker_strings():
    visible = {"api_token": KEY["api_token"], "workspace_ids": [101]}
    shaped = p.SkyviaAPITokenCredential.model_validate(visible).model_dump(exclude_unset=True)
    assert shaped == KEY
    assert KEY["api_token"] not in repr(p.SkyviaAPITokenCredential.model_validate(visible))
    model = p.SkyviaNode.parse_config({"config": {"operation": "get_connection", "workspace_id": "101", "connection_id": "301"}, "credentials": KEY})
    assert model.config.workspace_id == 101 and model.config.connection_id == 301
    for bad in ["Bearer synthetic-token", "line\nsecret", "line\rsecret", " ", "é"]:
        verdict = p.SkyviaNode.validate_config({"config": {"operation": "list_workspaces"}, "credentials": {**KEY, "api_token": bad}})
        assert verdict["valid"] is False
        assert verdict["errors"] == ["Skyvia credential shape is invalid; reconnect it"]
    verdict = p.SkyviaNode.validate_config({"config": {"operation": "list_workspaces"}, "credentials": {**KEY, "credential_type": "foreign"}})
    assert verdict["valid"] is False


@pytest.mark.asyncio
async def test_actual_connect_and_collector_prove_protected_workspace_visibility(wire, monkeypatch):
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=p.TYPE, credential_data={"api_token": KEY["api_token"], "workspace_ids": [101]}, user_id="11111111-1111-4111-8111-111111111111", probe=True)
    assert verdict.ok and verdict.credential_data == KEY
    assert verdict.evidence.reachable is True and p.SkyviaNode.connection_evidence.proves == "account"
    result = await connection_evidence.collect_evidence(node_type="automation-skyvia", credential_data=KEY, user_id="11111111-1111-4111-8111-111111111111")
    assert result.reachable is True and "101" in repr(result.samples)
    assert KEY["api_token"] not in repr(result) and "private workspace" not in repr(result)
    output = await create("list_workspaces").execute({})
    assert output["principal_identity_verified"] is False and output["account_ownership_verified"] is False and output["provider_permissions_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,kind", [
    ("list_workspaces", {}, "workspaces"), ("get_workspace", {"workspace_id": 101}, "workspaces"),
    ("list_connections", {"workspace_id": 101}, "connections"), ("get_connection", {"workspace_id": 101, "connection_id": 301}, "connections"),
    ("list_integrations", {"workspace_id": 101}, "integrations"), ("get_integration", {"workspace_id": 101, "integration_id": 302}, "integrations"),
    ("list_backups", {"workspace_id": 101}, "backups"), ("get_backup", {"workspace_id": 101, "backup_id": 303}, "backups"),
    ("list_automations", {"workspace_id": 101}, "automations"), ("get_automation", {"workspace_id": 101, "automation_id": 304}, "automations"),
])
async def test_all_ten_actual_factory_dispatch_paths_are_closed_and_projected(wire, operation, arguments, kind):
    result = await create(operation, **arguments).execute({})
    assert wire["calls"][0] == ("/workspaces", {})
    if operation != "list_workspaces": assert wire["calls"][1] == ("/workspaces/101", {})
    if kind != "workspaces":
        suffix = "/workspaces/101/" + kind
        if operation.startswith("list_"):
            assert wire["calls"][-1] == (suffix, {"take": 20, "skip": 0})
            assert result["has_more"] is False and result["next_skip"] is None
        else:
            assert wire["calls"][-2] == (suffix, {"take": 100, "skip": 0})
            assert wire["calls"][-1] == (suffix + "/" + str(RESOURCE[kind]["id"]), {})
    for forbidden in [KEY["api_token"], "private business", "private workspace", "private SQL", "private error", "private log", "capability.example"]:
        assert forbidden not in repr(result)


@pytest.mark.asyncio
async def test_names_are_explicit_opt_in_and_workspace_scope_excludes_other_catalog_ids(wire):
    wire["workspace_ids"] = [101, 102]
    result = await create("list_workspaces", include_names=True).execute({})
    assert result["items"] == [{"id": 101, "isPersonal": False, "name": "private workspace"}]
    result = await create("get_connection", workspace_id=101, connection_id=301, include_names=True).execute({})
    assert result["name"] == "private business connection" and "settings" not in result
    with pytest.raises(ValueError, match="saved scope"):
        await create("get_workspace", workspace_id=102).execute({})
    assert all("/102" not in path for path, _ in wire["calls"])


@pytest.mark.asyncio
async def test_missing_catalog_membership_and_foreign_point_ids_refuse_descendants(wire):
    wire["workspace_ids"] = [102]
    with pytest.raises(ValueError, match="catalog"):
        await create("list_connections", workspace_id=101).execute({})
    assert wire["calls"] == [("/workspaces", {})]
    wire["workspace_ids"] = [101]; wire["calls"].clear()
    wire["responses"]["/workspaces/101"] = {"id": 102}
    with pytest.raises(ValueError, match="different scoped workspace"):
        await create("list_connections", workspace_id=101).execute({})
    assert len(wire["calls"]) == 2
    wire["responses"].clear(); wire["calls"].clear()
    wire["responses"]["/workspaces/101/connections/301"] = {"id": 999}
    with pytest.raises(ValueError, match="different scoped resource"):
        await create("get_connection", workspace_id=101, connection_id=301).execute({})


@pytest.mark.asyncio
async def test_point_read_requires_current_resource_membership_before_detail(wire):
    wire["responses"]["/workspaces/101/connections"] = {"data": [{"id": 999}], "hasMore": False}
    with pytest.raises(ValueError, match="absent"):
        await create("get_connection", workspace_id=101, connection_id=301).execute({})
    assert not any(path.endswith("/301") for path, _ in wire["calls"])


@pytest.mark.asyncio
async def test_documented_automation_zero_identifier_is_preserved(wire):
    row = {"id": 0, "triggerType": "Manual"}
    wire["responses"]["/workspaces/101/automations"] = {"data": [row], "hasMore": False}
    wire["responses"]["/workspaces/101/automations/0"] = row
    result = await create("get_automation", workspace_id="101", automation_id="0").execute({})
    assert result == {"id": 0, "triggerType": "Manual", "workspace_id": 101}
    assert wire["calls"][-1] == ("/workspaces/101/automations/0", {})


@pytest.mark.asyncio
async def test_documented_short_page_offsets_advance_by_returned_rows_not_take(wire):
    wire["responses"]["/workspaces/101/connections"] = lambda query: {"data": [{"id": 299 if query["skip"] == 0 else 301}], "hasMore": query["skip"] == 0}
    result = await create("list_connections", workspace_id=101, take=20).execute({})
    assert result["count"] == 1 and result["has_more"] is True and result["next_skip"] == 1 and result["total"] is None
    wire["calls"].clear()
    await create("get_connection", workspace_id=101, connection_id=301).execute({})
    assert ("/workspaces/101/connections", {"take": 100, "skip": 1}) in wire["calls"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": [], "hasMore": True}, {"data": [{"id": 301}], "hasMore": "false"}, {"data": [{"id": 301}]}, [{"id": 301}], {"data": [{"id": 301}, {"id": 301}], "hasMore": False}, {"data": [{"id": "301"}], "hasMore": False}])
async def test_documented_list_envelope_progress_and_actual_id_types(wire, payload):
    wire["responses"]["/workspaces/101/connections"] = payload
    with pytest.raises(ValueError): await create("list_connections", workspace_id=101).execute({})


@pytest.mark.asyncio
async def test_membership_and_picker_caps_are_explicit_refusals(wire):
    wire["responses"]["/workspaces/101/connections"] = lambda query: {"data": [{"id": query["skip"] + 1}], "hasMore": True}
    with pytest.raises(ValueError, match="ten bounded pages"):
        await create("get_connection", workspace_id=101, connection_id=301).execute({})
    assert len([c for c in wire["calls"] if c[0].endswith("/connections")]) == 10
    token = None
    for index in range(10):
        if index == 9:
            with pytest.raises(ValueError, match="ten bounded pages"):
                await p.SkyviaNode.load_field_options("connection_id", KEY, {"workspace_id": 101}, page_token=token)
        else:
            result = await p.SkyviaNode.load_field_options("connection_id", KEY, {"workspace_id": 101}, page_token=token)
            token = result["next_page_token"]
            assert token and result["options"][0]["value"] == str(index + 1)


@pytest.mark.asyncio
async def test_picker_continuations_bind_current_token_workspace_field_search_and_seen_ids(wire):
    wire["responses"]["/workspaces/101/connections"] = lambda query: {"data": [{"id": 301 + query["skip"]}], "hasMore": query["skip"] == 0}
    first = await p.SkyviaNode.load_field_options("connection_id", KEY, {"workspace_id": "101"}, search="30")
    token = first["next_page_token"]
    assert first["options"] == [{"value": "301", "label": "301"}] and token
    second = await p.SkyviaNode.load_field_options("connection_id", KEY, {"workspace_id": 101}, page_token=token, search="30")
    assert second["options"] == [{"value": "302", "label": "302"}] and second["next_page_token"] is None
    for field, data, context, search, bad_token in [
        ("integration_id", KEY, {"workspace_id": 101}, "30", token),
        ("connection_id", KEY, {"workspace_id": 102}, "30", token),
        ("connection_id", KEY, {"workspace_id": 101}, "301", token),
        ("connection_id", {**KEY, "api_token": "synthetic-rebound"}, {"workspace_id": 101}, "30", token),
        ("connection_id", KEY, {"workspace_id": 101}, "30", token + "x"),
        ("connection_id", KEY, {"workspace_id": 101}, "30", ""),
    ]:
        before = len(wire["calls"])
        with pytest.raises(ValueError, match="continuation"):
            await p.SkyviaNode.load_field_options(field, data, context, page_token=bad_token, search=search)
        assert len(wire["calls"]) == before
    wire["responses"]["/workspaces/101/connections"] = {"data": [{"id": 301}], "hasMore": False}
    with pytest.raises(ValueError, match="repeated"):
        await p.SkyviaNode.load_field_options("connection_id", KEY, {"workspace_id": 101}, page_token=token, search="30")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,headers", [(403, b'private token error', {"content-type": "application/json"}), (429, b'private rate error', {"content-type": "application/json"}), (302, b'', {"location": "https://capability.example.test/private"}), (200, b'<html>private</html>', {"content-type": "text/html"}), (200, b'{"id":1,"id":2}', {"content-type": "application/json"}), (200, b'{"id":NaN}', {"content-type": "application/json"}), (200, b'x' * (p.MAX_BYTES + 1), {"content-type": "application/json"})])
async def test_refusals_errors_formats_and_duplicate_keys_are_sanitized_without_retry(wire, status, content, headers):
    wire.update(status=status, content=content, headers=headers)
    with pytest.raises(ValueError) as error: await create("list_workspaces").execute({})
    assert KEY["api_token"] not in str(error.value) and "private token error" not in str(error.value) and "capability.example" not in str(error.value)
    assert len(wire["calls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content", [(403, None), (200, b'not JSON')])
async def test_current_reader_is_reread_after_refusal_or_json_failure(wire, status, content):
    wire.update(status=status, content=content)
    reader = p.Reader(None, None)
    reader.read = AsyncMock(side_effect=[p.guard(KEY), ValueError("synthetic access removed")])
    with pytest.raises(ValueError, match="access removed"):
        await p.request(p.guard(KEY), "/workspaces", reader=reader)
    assert reader.read.await_count == 2 and len(wire["calls"]) == 1


@pytest.mark.asyncio
async def test_closed_transport_refuses_foreign_roots_control_routes_and_query_keys_before_io(wire):
    for path, query in [("https://evil.example/", None), ("/workspaces/101/connections/301/test", None), ("/workspaces/101/automations/304/enable", None), ("/workspaces/102", None), ("/workspaces", {"Authorization": KEY["api_token"]}), ("/workspaces/101/connections", {"take": True, "skip": 0})]:
        with pytest.raises(ValueError): await p.request(p.guard(KEY), path, params=query)
    assert wire["calls"] == []
