"""Factory, private expiry cache, credential binding and GraphQL seams."""
import asyncio
import base64
from copy import deepcopy
import json
import socket
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from nodes import leanix_node as lx
from nodes.core import credential_connect as cc
from nodes.core.registry import NodeFactory
from utils import ssrf

TYPE, FAMILY = "automation-leanix", "leanix_api_token"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
WITNESS, OTHER = ID, "00000000-0000-4000-8000-000000000043"
CREDS = {"api_token": "synthetic-leanix-private-api-canary", "workspace_subdomain": "fixture-workspace", "witness_fact_sheet_id": WITNESS}
ACCESS = "synthetic-leanix-private-bearer-canary"
ME = {"id": WITNESS, "name": "Fixture Application", "type": "Application", "description": "private-description-marker", "documents": [{"url": "private-document-marker"}]}
ARGS = {"fact_sheet_type": "Application", "fact_sheet_id": OTHER}
TYPE_ARGS = {"fact_sheet_type": "Application"}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None, current=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    if current:
        data.update(credential_id=ID, _approval_pool=current.pool)
    return NodeFactory.create_node(node_id="leanix-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest_asyncio.fixture
async def wire(monkeypatch):
    lx.TOKEN_CACHE.clear()
    state = SimpleNamespace(calls=[], override=None, me=deepcopy(ME), address="8.8.8.8", token_reply={"access_token": ACCESS, "expires_in": 3599, "token_type": "bearer", "expired": False, "scope": ""})
    async def respond(request):
        state.calls.append(request)
        assert request.method == "POST" and request.url.scheme == "https" and request.url.host == "fixture-workspace.leanix.net"
        assert not request.url.params and not request.url.username
        if state.override:
            value = state.override(request)
            if value is not None:
                return value
        if request.url.path == lx.TOKEN_PATH:
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(("apitoken:" + CREDS["api_token"]).encode()).decode()
            assert request.headers["Content-Type"] == "application/x-www-form-urlencoded" and request.content == b"grant_type=client_credentials"
            await asyncio.sleep(0)
            return httpx.Response(200, json=state.token_reply)
        assert request.url.path == lx.GRAPHQL_PATH and request.headers["Authorization"] == "Bearer " + ACCESS
        assert request.headers["Content-Type"] == "application/json"
        body = json.loads(request.content)
        assert set(body) == {"query", "variables"} and body["query"] in lx.QUERIES and body["query"].startswith("query ")
        query, variables = body["query"], body["variables"]
        if query == lx.FACT_SHEET:
            assert set(variables) == {"id"} and variables["id"] in {WITNESS, OTHER}
            return httpx.Response(200, json={"data": {"factSheet": {**state.me, "id": variables["id"]}}})
        if query in {lx.TYPE_FACETS, lx.APPLICATION_FACETS}:
            assert variables == {}
            facet = {"facetKey": "technicalSuitability", "results": [{"key": "unreasonable", "name": "Unreasonable"}]} if query == lx.APPLICATION_FACETS else {"facetKey": "FactSheetTypes", "results": [{"key": "Application", "name": "Application"}, {"key": "BusinessCapability", "name": "Business Capability"}]}
            return httpx.Response(200, json={"data": {"allFactSheets": {"filterOptions": {"facets": [facet, {"facetKey": "private-unrequested", "results": [{"name": "private-subscriber-marker", "key": "private-owner-marker"}]}]}}}})
        assert query in {lx.ALL_SHEETS, lx.FILTERED_SHEETS, lx.FIT_SHEETS}
        assert set(variables) == ({"first", "after"} if query == lx.ALL_SHEETS else {"first", "after", "filter"})
        if query != lx.ALL_SHEETS:
            facets = [{"facetKey": "FactSheetTypes", "operator": "OR", "keys": ["Application"]}]
            if query == lx.FIT_SHEETS:
                facets.append({"facetKey": "technicalSuitability", "operator": "OR", "keys": ["unreasonable"]})
            assert variables["filter"] == {"facetFilters": facets}
        start = 0 if variables["after"] is None else 1
        assert variables["after"] in {None, "opaque-next-1"}
        rows = [{**ME, "id": identifier} for identifier in [WITNESS, OTHER]]
        selected = rows[start:start + variables["first"]]
        if query == lx.FIT_SHEETS:
            selected = [{**row, "technicalSuitability": "unreasonable"} for row in selected]
        more = start + len(selected) < len(rows)
        return httpx.Response(200, json={"data": {"allFactSheets": {"edges": [{"node": row} for row in selected], "totalCount": 2, "pageInfo": {"hasNextPage": more, "endCursor": "opaque-next-1" if more else "opaque-final-2"}}}})
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(lx, "guarded_async_client", client)
    yield state
    lx.TOKEN_CACHE.clear()


CASES = [("test_authentication", {}), ("get_fact_sheet", ARGS), ("list_fact_sheets", {}), ("list_fact_sheet_types", {}), ("list_applications_by_technical_fit", {"technical_fit": "unreasonable"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", CASES)
async def test_actual_factory_run_five_native_queries_with_private_projection(wire, op, args):
    node = factory(op, args)
    assert isinstance(node, lx.LeanIXNode)
    result = await node.run({})
    for marker in (CREDS["api_token"], ACCESS, "private-description", "private-document", "private-subscriber", "private-owner"):
        assert marker not in json.dumps(result)
    if op == "test_authentication":
        assert result["reachable"] is True and result["identity_verified"] is False and result["workspace_identity_verified"] is False
    if op in {"list_fact_sheets", "list_applications_by_technical_fit"}:
        assert result["snapshot_consistency_verified"] is False and result["idempotence_verified"] is False
    assert len([r for r in wire.calls if r.url.path == lx.TOKEN_PATH]) == 1


def test_actual_three_value_shape_schema_and_fact_sheet_parent():
    blob, errors, resolved = cc.shape_credential(FAMILY, CREDS)
    assert not errors and "credential_type" not in blob and resolved == (TYPE, lx.LeanIXApiTokenCredential)
    schema = lx.LeanIXNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 5
    assert schema["$defs"]["LeanIXApiTokenCredential"]["properties"]["api_token"]["ui:widget"] == "password"
    assert schema["$defs"]["GetFactSheet"]["properties"]["fact_sheet_id"]["x-dynamic-options"]["depends_on"] == "fact_sheet_type"


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_family_guard_before_factory_parse(tag):
    with pytest.raises(ValueError, match="native SAP LeanIX"):
        factory("test_authentication", credential={**CREDS, "credential_type": tag})
    assert lx.LeanIXNode.validate_config({"config": {"operation": "test_authentication"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("host", ["https://fixture.leanix.net", "fixture.leanix.net", "localhost", "127.0.0.1", "fixture/other", "fixture:443", "Fixture", "-fixture", "fixture."])
def test_native_workspace_subdomain_contract(host):
    # A single ordinary label such as localhost is still provider-bound, never a local host.
    if host == "localhost":
        assert lx._Client(lx._Authority({**CREDS, "workspace_subdomain": host})).origin == "https://localhost.leanix.net"
    else:
        with pytest.raises(ValueError):
            lx._credential({**CREDS, "workspace_subdomain": host})


@pytest.mark.parametrize("sidecar", [{"query": "mutation { deleteFactSheet }"}, {"variables": {}}, {"endpoint": "https://foreign.example.test"}, {"headers": {}}, {"scripts": []}, {"subscriptions": []}])
def test_unknown_sidecars_cannot_change_native_read_transport(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("test_authentication", sidecar)


@pytest.mark.asyncio
async def test_private_cache_reuse_concurrency_expiry_and_nonminting_freshen(wire):
    assert (await lx.LeanIXNode.freshen_credential(CREDS))["api_token"] == CREDS["api_token"]
    assert (await lx.LeanIXNode.validate_credential_access(CREDS))["valid"] is None and wire.calls == []
    first, second = await asyncio.gather(factory("test_authentication").run({}), factory("test_authentication").run({}))
    assert first == second and len([r for r in wire.calls if r.url.path == lx.TOKEN_PATH]) == 1
    entry = next(iter(lx.TOKEN_CACHE.values()))
    assert time.monotonic() < entry.expires_at <= time.monotonic() + 3599 - 30
    await factory("test_authentication").run({})
    assert len([r for r in wire.calls if r.url.path == lx.TOKEN_PATH]) == 1
    entry.expires_at = 0
    await factory("test_authentication").run({})
    assert len([r for r in wire.calls if r.url.path == lx.TOKEN_PATH]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"expires_in": None}, {"expires_in": True}, {"expires_in": 0}, {"expires_in": 3601}, {"expired": True}, {"token_type": 42}, {"token_type": "Basic"}])
async def test_malformed_token_expiry_cannot_populate_cache(wire, change):
    wire.token_reply.update(change)
    with pytest.raises(lx.LeanIXRequestError, match="bounded expiry"):
        await factory("test_authentication").run({})
    assert len(wire.calls) == 1 and all(entry.access_token is None for entry in lx.TOKEN_CACHE.values())


@pytest.mark.asyncio
async def test_closed_query_variables_before_transport_and_unavailable_parent_before_target(wire):
    client = lx._Client(lx._Authority(CREDS))
    for body in [{"query": "mutation { deleteFactSheet }", "variables": {}}, {"query": lx.FACT_SHEET, "variables": {"id": WITNESS, "url": "foreign"}},
        {"query": lx.FILTERED_SHEETS, "variables": {"first": 2, "after": None, "filter": {"advanced": "arbitrary"}}}]:
        with pytest.raises(ValueError):
            await client._http(lx.GRAPHQL_PATH, body=body, token=ACCESS)
    assert wire.calls == []
    with pytest.raises(ValueError, match="not currently available"):
        await factory("get_fact_sheet", {**ARGS, "fact_sheet_type": "ForeignType"}).run({})
    assert not any(r.url.path == lx.GRAPHQL_PATH and json.loads(r.content).get("variables", {}).get("id") == OTHER for r in wire.calls)


@pytest.mark.asyncio
async def test_opaque_forward_cursor_scope_and_cycle_without_snapshot_claim(wire):
    first = await factory("list_fact_sheets", {"page_size": 1}).run({})
    second = await factory("list_fact_sheets", {"page_size": 1, "page_token": first["next_page_token"]}).run({})
    assert [first["data"][0]["id"], second["data"][0]["id"]] == [WITNESS, OTHER] and second["next_page_token"] is None
    calls = [json.loads(r.content)["variables"] for r in wire.calls if r.url.path == lx.GRAPHQL_PATH and json.loads(r.content)["query"] == lx.ALL_SHEETS]
    assert calls == [{"first": 1, "after": None}, {"first": 1, "after": "opaque-next-1"}]
    with pytest.raises(ValueError, match="continuation is invalid"):
        await factory("list_fact_sheets", {"page_size": 2, "page_token": first["next_page_token"]}).run({})
    wire.override = lambda r: httpx.Response(200, json={"data": {"allFactSheets": {"edges": [{"node": ME}], "totalCount": 2, "pageInfo": {"hasNextPage": True, "endCursor": "opaque-next-1"}}}}) if r.url.path == lx.GRAPHQL_PATH and json.loads(r.content)["query"] == lx.ALL_SHEETS else None
    with pytest.raises(ValueError, match="did not advance"):
        await factory("list_fact_sheets", {"page_size": 1, "page_token": first["next_page_token"]}).run({})


@pytest.mark.asyncio
async def test_empty_advancing_dynamic_page_is_preserved(wire):
    wire.override = lambda r: httpx.Response(200, json={"data": {"allFactSheets": {"edges": [], "totalCount": 0, "pageInfo": {"hasNextPage": True, "endCursor": "opaque-empty-page"}}}}) if r.url.path == lx.GRAPHQL_PATH and json.loads(r.content)["query"] == lx.ALL_SHEETS else None
    result = await factory("list_fact_sheets").run({})
    assert result["data"] == [] and result["next_page_token"] and result["snapshot_consistency_verified"] is False


@pytest.mark.asyncio
async def test_partial_graphql_error_null_witness_and_private_output_fail_closed(wire):
    for response in [{"data": {"factSheet": ME}, "errors": [{"message": ACCESS, "extensions": {"private": CREDS["api_token"]}}]}, {"data": {"factSheet": None}}, {"data": {"factSheet": {**ME, "name": "https://private.example.test/download?signature=synthetic"}}}]:
        wire.override = lambda r: httpx.Response(200, json=response) if r.url.path == lx.GRAPHQL_PATH else None
        with pytest.raises(ValueError) as error:
            await factory("test_authentication").run({})
        assert ACCESS not in str(error.value) and CREDS["api_token"] not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_status_contract_no_retry_and_no_raw_error(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"error": CREDS["api_token"]})
    with pytest.raises(lx.LeanIXRequestError) as error:
        await factory("test_authentication").run({})
    assert error.value.status == status and CREDS["api_token"] not in str(error.value) and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_graphql401_invalidates_matching_cache_without_same_operation_remint(wire):
    await factory("test_authentication").run({})
    wire.calls.clear()
    wire.override = lambda r: httpx.Response(401, json={"error": ACCESS})
    with pytest.raises(lx.LeanIXRequestError):
        await factory("test_authentication").run({})
    assert len(wire.calls) == 1 and wire.calls[0].url.path == lx.GRAPHQL_PATH
    assert all(entry.access_token is None for entry in lx.TOKEN_CACHE.values())


@pytest.mark.asyncio
async def test_private_dns_is_rejected_by_staging_guard(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ValueError):
        await factory("test_authentication").run({})
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, {**CREDS, "workspace_subdomain": "changed-workspace"}, {**CREDS, "api_token": "changed-private-token"}, {**CREDS, "witness_fact_sheet_id": OTHER}])
async def test_saved_credential_resolution_rejects_missing_or_changed_binding(wire, monkeypatch, current):
    resolver = AsyncMock(return_value=current)
    monkeypatch.setattr(lx, "resolve_credential_with_owner_fallback", resolver)
    authority = lx._Authority(CREDS, credential_id=ID, user_id=USER)
    with pytest.raises(ValueError, match="unavailable or revoked|binding changed"):
        await lx._Client(authority).witness()
    assert wire.calls == []
    resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_selectors_accept_staging_plain_credential_and_parent_context(wire):
    result = await lx.LeanIXNode.load_field_options("fact_sheet_id", CREDS, context=TYPE_ARGS, search="Fixture")
    assert result["options"] == [{"label": "Fixture Application", "value": WITNESS}, {"label": "Fixture Application", "value": OTHER}]
    with pytest.raises(ValueError):
        await lx.LeanIXNode.load_field_options("fact_sheet_id", CREDS, context={})


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign"])
async def test_bad_family_freshen_and_picker_before_provider(wire, tag):
    for method in (lx.LeanIXNode.freshen_credential, lx.LeanIXNode.validate_credential_access):
        with pytest.raises(ValueError, match="native SAP LeanIX"):
            await method({**CREDS, "credential_type": tag})
    with pytest.raises(ValueError, match="native SAP LeanIX"):
        await lx.LeanIXNode.load_field_options("fact_sheet_id", {**CREDS, "credential_type": tag}, context=TYPE_ARGS)
    assert wire.calls == []
