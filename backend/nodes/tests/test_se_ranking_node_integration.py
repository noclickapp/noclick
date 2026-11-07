"""SE Ranking factory, parent-resource, transport and projection contracts."""
import asyncio
from copy import deepcopy
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from nodes import se_ranking_node as sr
from nodes.core import credential_connect as cc
from nodes.core.registry import NodeFactory
from utils import ssrf

TYPE, FAMILY = "automation-se-ranking", "se_ranking_api_token"
USER = "00000000-0000-4000-8000-000000000001"
SITE, ENGINE, KEYWORD, GROUP, AUDIT = 42, 7, 11, 8, 13
CREDS = {"api_token": "synthetic-se-ranking-private-token-canary", "expected_email": "owner@example.test", "project_ids": [SITE]}
ME = {"email": CREDS["expected_email"], "email_verified": True, "first_name": "Fixture", "picture": "private-avatar-marker"}
SITE_ARGS = {"site_id": SITE}
ENGINE_ARGS = {**SITE_ARGS, "site_engine_id": ENGINE}
CREATE_ARGS = {**SITE_ARGS, "name": "Disposable Fixture", "confirm_create": True}
DELETE_ARGS = {**SITE_ARGS, "group_id": GROUP, "confirm_delete": True}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    return NodeFactory.create_node(node_id="se-ranking-fixture", node_type=TYPE, node_data=data, user_id=USER)


class Bodyless204(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("A documented 204 must not be consumed or decoded")
        yield b""
    async def aclose(self):
        pass


@pytest_asyncio.fixture
async def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, me=deepcopy(ME), address="8.8.8.8",
        projects=[{"id": SITE, "title": "Owned Fixture", "name": "example.test", "group_id": 0, "is_active": 1, "guest_link": "private-guest-marker"}],
        engines=[{"site_engine_id": ENGINE, "search_engine_id": 1, "region_id": 1, "region_name": "Fixture", "lang_code": "en", "business_phone": "private-phone-marker"}],
        keywords=[{"id": str(KEYWORD), "name": "fixture keyword", "group_id": "0", "site_engine_ids": [ENGINE], "first_check_date": "2026-10-01", "link": "private-keyword-link"}],
        groups=[{"id": str(GROUP), "name": "Empty Fixture", "creation_date": "2026-10-01"}],
        audits=[{"id": AUDIT, "has_project": True, "site_id": SITE, "title": "Existing Audit", "status": "finished", "owner_account_id": "private-owner-marker", "error": "private-error-marker", "error_params": {"secret": "private-config-marker"}}])
    def respond(request):
        state.calls.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.seranking.com" and not request.url.username
        assert request.headers["Authorization"] == "Token " + CREDS["api_token"]
        assert request.headers["Content-Type"] == "application/json" and "api_token" not in request.url.params
        assert CREDS["api_token"] not in str(request.url)
        if state.override:
            value = state.override(request)
            if value is not None:
                return value
        assert request.url.path.startswith(sr.PREFIX)
        route, query = request.url.path.removeprefix(sr.PREFIX), dict(request.url.params)
        if route == "/users/me":
            assert request.method == "GET" and query == {}
            return httpx.Response(200, json=state.me)
        if route == "/sites":
            assert request.method == "GET" and query == {}
            return httpx.Response(200, json=state.projects)
        if route == "/keywords/groups" and request.method == "POST":
            assert query == {} and json.loads(request.content) == {"site_id": SITE, "name": "Disposable Fixture"}
            state.groups.append({"id": "9", "name": "Disposable Fixture", "creation_date": "2026-10-06"})
            return httpx.Response(201, json={"group_id": 9})
        if route == "/keywords/groups" and request.method == "DELETE":
            assert query == {"group_id": str(GROUP)} and not request.content
            state.groups = [row for row in state.groups if int(row["id"]) != GROUP]
            return httpx.Response(204, stream=Bodyless204())
        assert request.method == "GET"
        if route == "/audits":
            assert set(query) == {"limit", "offset"}
            start, size = int(query["offset"]), int(query["limit"])
            return httpx.Response(200, json={"items": state.audits[start:start + size], "total": len(state.audits)})
        if route == "/audits/status":
            assert query == {"audit_id": str(AUDIT)}
            return httpx.Response(200, json={"status": "processing", "total_pages": 2})
        assert query.get("site_id") == str(SITE)
        if route == "/sites/search-engines":
            assert query == {"site_id": str(SITE)}
            return httpx.Response(200, json=state.engines)
        if route == "/keywords":
            assert query in ({"site_id": str(SITE)}, {"site_id": str(SITE), "site_engine_id": str(ENGINE)})
            return httpx.Response(200, json=state.keywords)
        if route == "/keywords/groups":
            return httpx.Response(200, json=state.groups)
        if route == "/competitors":
            return httpx.Response(200, json=[{"id": 6, "name": "Fixture Competitor", "url": "private-competitor-link", "domain_trust": 12}])
        if route == "/sites/summary":
            return httpx.Response(200, json={"site_id": SITE, "today_avg": 12.5, "top5": 2, "query": "private-query-marker"})
        if route == "/sites/positions/checkpoints":
            assert query == {"site_id": str(SITE), "site_engine_id": str(ENGINE)}
            return httpx.Response(200, json={"current": "2026-10-06", "first": "2026-10-01"})
        assert route == "/sites/positions"
        assert query == {"site_id": str(SITE), "site_engine_id": str(ENGINE), "date_from": "2026-10-01", "date_to": "2026-10-06"}
        return httpx.Response(200, json=[{"site_engine_id": ENGINE, "keywords": [{"id": str(KEYWORD), "suggested_bid": "private-price-marker", "positions": [{"date": "2026-10-06", "pos": 3, "change": -1, "is_map": 0, "price": "private-price-marker"}]}]}])
    async def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (state.address, 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(sr, "guarded_async_client", client)
    # The node spaces its requests 0.22 s apart for SE Ranking's rate limit; this fake API needs no spacing.
    real_sleep = asyncio.sleep

    async def unpaced(delay, *args, **kwargs):
        return await real_sleep(0 if delay <= 0.22 else delay, *args, **kwargs)

    monkeypatch.setattr(sr.asyncio, "sleep", unpaced)
    return state


CASES = [("get_profile", {}), ("list_projects", {}), ("get_project", SITE_ARGS), ("list_search_engines", SITE_ARGS),
    ("list_keywords", ENGINE_ARGS), ("get_project_summary", SITE_ARGS),
    ("get_keyword_positions", {**ENGINE_ARGS, "keyword_id": KEYWORD, "date_from": "2026-10-01", "date_to": "2026-10-06"}),
    ("get_historical_dates", ENGINE_ARGS), ("list_keyword_groups", SITE_ARGS), ("create_keyword_group", CREATE_ARGS),
    ("delete_keyword_group", DELETE_ARGS), ("list_competitors", SITE_ARGS), ("list_audits", SITE_ARGS), ("get_audit_status", {**SITE_ARGS, "audit_id": AUDIT})]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", CASES)
async def test_actual_factory_run_fourteen_routes_and_private_projection(wire, op, args):
    node = factory(op, args)
    assert isinstance(node, sr.SERankingNode)
    result = await node.run({})
    assert result["email"] == CREDS["expected_email"] and result["project_ownership_verified"] is False
    for marker in (CREDS["api_token"], "private-avatar", "private-phone", "private-owner", "private-guest", "private-keyword", "private-query", "private-price", "private-error", "private-config", "private-competitor"):
        assert marker not in json.dumps(result)
    if op == "create_keyword_group":
        assert result["readback_verified"] is True and result["ownership_verified"] is False
        assert result["http_status"] == 201
    if op == "delete_keyword_group":
        assert result["http_status"] == 204 and result["absence_verified"] is True and result["deleted"] is True
    if op == "get_audit_status":
        assert result["http_status"] == 200 and result["data"]["status"] == "processing"
    if op == "get_keyword_positions":
        assert result["data"] == [{"date": "2026-10-06", "pos": 3, "change": -1, "is_map": 0}]


def test_actual_three_value_connect_shape_schema_and_required_parents():
    blob, errors, resolved = cc.shape_credential(FAMILY, CREDS)
    assert not errors and "credential_type" not in blob and resolved == (TYPE, sr.SERankingApiTokenCredential)
    schema = sr.SERankingNodeConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 14
    assert schema["$defs"]["SERankingApiTokenCredential"]["properties"]["api_token"]["ui:widget"] == "password"
    assert schema["$defs"]["GetKeywordPositions"]["properties"]["keyword_id"]["x-dynamic-options"]["depends_on"] == "site_engine_id"


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_family_guard_before_factory_parse(tag):
    with pytest.raises(ValueError, match="native SE Ranking"):
        factory("get_profile", credential={**CREDS, "credential_type": tag})
    assert sr.SERankingNode.validate_config({"config": {"operation": "get_profile"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {}}, {"token": "foreign"}, {"check": True}, {"create_audit": True}, {"invite": True}])
def test_unknown_sidecars_cannot_turn_read_into_write_or_other_transport(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_project", {**SITE_ARGS, **sidecar})


@pytest.mark.asyncio
async def test_route_and_project_guards_before_http(wire):
    client = sr._Client(sr._Authority(CREDS))
    for method, route, kw in [("GET", "/whoami", {}), ("POST", "/sites/recheck", {}), ("POST", "/audits", {}),
        ("GET", "/sites", {"params": {"token": CREDS["api_token"]}}), ("GET", "/sites/search-engines", {"params": {"site_id": 99}}),
        ("POST", "/keywords/groups", {"body": {"site_id": SITE, "name": "Fixture", "keywords": [11]}})]:
        with pytest.raises(ValueError):
            await client._http(method, route, **kw)
    with pytest.raises(ValueError, match="allowed by"):
        await factory("get_project", {"site_id": 99}).run({})
    assert (await sr.SERankingNode.validate_credential_access(CREDS))["valid"] is None
    assert wire.calls == []


@pytest.mark.asyncio
async def test_profile_and_current_engine_keyword_audit_parent_witnesses(wire):
    wire.me["email"] = "foreign@example.test"
    with pytest.raises(ValueError, match="account differs"):
        await factory("get_project", SITE_ARGS).run({})
    assert len(wire.calls) == 1
    wire.me = deepcopy(ME)
    for op, args, forbidden in [("get_historical_dates", {**ENGINE_ARGS, "site_engine_id": 99}, "/sites/positions/checkpoints"),
        ("get_keyword_positions", {**ENGINE_ARGS, "keyword_id": 99, "date_from": "2026-10-01", "date_to": "2026-10-06"}, "/sites/positions"),
        ("get_audit_status", {**SITE_ARGS, "audit_id": 99}, "/audits/status")]:
        wire.calls.clear()
        with pytest.raises(ValueError):
            await factory(op, args).run({})
        assert not any(r.url.path.endswith(forbidden) for r in wire.calls)


@pytest.mark.asyncio
async def test_group_nonempty_guard_and_uncertain_creation_not_retried(wire):
    wire.keywords[0]["group_id"] = str(GROUP)
    with pytest.raises(ValueError, match="not proven empty"):
        await factory("delete_keyword_group", DELETE_ARGS).run({})
    assert not any(r.method == "DELETE" for r in wire.calls)
    wire.calls.clear()
    def fail(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("private " + CREDS["api_token"], request=request)
    wire.override = fail
    with pytest.raises(sr.SERankingRequestError, match="outcome is unknown") as error:
        await factory("create_keyword_group", CREATE_ARGS).run({})
    assert CREDS["api_token"] not in str(error.value) and error.value.__suppress_context__
    assert len([r for r in wire.calls if r.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_complete_array_paging_and_changed_collection_rejection(wire):
    wire.groups.append({"id": "9", "name": "Second Fixture"})
    args = {**SITE_ARGS, "page_size": 1}
    first = await factory("list_keyword_groups", args).run({})
    last = await factory("list_keyword_groups", {**args, "page_token": first["next_page_token"]}).run({})
    assert [first["data"][0]["id"], last["data"][0]["id"]] == [8, 9]
    assert first["total"] == 2 and last["next_page_token"] is None
    wire.groups[1]["name"] = "Changed Fixture"
    with pytest.raises(ValueError, match="continuation changed"):
        await factory("list_keyword_groups", {**args, "page_token": first["next_page_token"]}).run({})


@pytest.mark.asyncio
async def test_audit_provider_envelope_filters_other_projects_without_fabricating_total(wire):
    wire.audits.insert(0, {"id": 12, "has_project": True, "site_id": 99, "title": "Foreign"})
    first = await factory("list_audits", {**SITE_ARGS, "page_size": 1}).run({})
    assert first["data"] == [] and first["total"] is None and first["next_page_token"]
    second = await factory("list_audits", {**SITE_ARGS, "page_size": 1, "page_token": first["next_page_token"]}).run({})
    assert second["data"][0]["id"] == AUDIT and second["next_page_token"] is None
    wire.override = lambda r: httpx.Response(200, json={"items": [wire.audits[0]], "total": 2}) if r.url.path.endswith("/audits") else None
    with pytest.raises(ValueError, match="repeated or changed"):
        await factory("list_audits", {**SITE_ARGS, "page_size": 1, "page_token": first["next_page_token"]}).run({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_read_status_contract_sanitized_no_retry(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"error": CREDS["api_token"]})
    with pytest.raises(sr.SERankingRequestError) as error:
        await factory("get_profile").run({})
    assert CREDS["api_token"] not in str(error.value) and error.value.status == status and len(wire.calls) == 1


@pytest.mark.asyncio
async def test_private_dns_is_blocked_by_staging_guard(wire, monkeypatch):
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: False)
    wire.address = "169.254.169.254"
    with pytest.raises(ValueError, match="[Pp]rivate|[Bb]locked|[Pp]ublic"):
        await factory("get_profile").run({})
    assert wire.calls == []


@pytest.mark.asyncio
async def test_plain_credential_picker_checks_parent_resources(wire):
    result = await sr.SERankingNode.load_field_options("site_engine_id", CREDS, context=SITE_ARGS)
    assert result["options"] == [{"label": "Engine 7", "value": "7"}]
    with pytest.raises(ValueError):
        await sr.SERankingNode.load_field_options("keyword_id", CREDS, context={**SITE_ARGS, "site_engine_id": 99})


@pytest.mark.asyncio
async def test_inline_connect_account_evidence(wire):
    verdict = await cc.validate_for_connect(credential_type=FAMILY, credential_data=CREDS, user_id=USER)
    assert not verdict.field_errors and verdict.evidence.reachable is True
    assert verdict.evidence.account_label == CREDS["expected_email"]
