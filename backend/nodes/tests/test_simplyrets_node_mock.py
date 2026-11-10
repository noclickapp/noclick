"""SimplyRETS request contracts and poll behavior, using synthetic schema-shaped data.

Field names, response envelopes and query types come from the provider's
https://docs.simplyrets.com/api/simplyrets-openapi.yaml v1.0.0.
No live account or credentials are used.
"""
import base64
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import simplyrets_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

CREDENTIAL = {"credential_type": "simplyrets_api_key", "api_key": "fixture-key", "api_secret": "fixture-secret"}
LISTING = {"mlsId": 1005252, "listingId": "MLS123", "address": {"full": "123 Test Street", "city": "Houston"},
    "agent": {"firstName": "John", "lastName": "Doe", "id": "123456789"}, "listPrice": 325275,
    "mls": {"status": "Active"}, "modified": "2026-10-01T13:27:01.42Z", "remarks": "Test listing"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="simplyrets-fixture", node_type="automation-simplyrets",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", native.ROUTES)
async def test_simplyrets_all_contract_methods_and_routes(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    cfg = {"operation": operation}
    for key in ("mlsId", "openHouseKey"):
        if "{" + key + "}" in path:
            cfg[key] = 1005252
            path = path.replace("{" + key + "}", "1005252")
    body = [LISTING] if native.RESPONSE_SHAPES[operation] == "list" else {"message": "OK"}
    requests = transport(monkeypatch, body)
    result = await node(cfg).execute({})
    assert result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url) == native.BASE + path
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-key:fixture-secret").decode()
    assert request.headers["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_simplyrets_repeated_filters_pagination_and_headers(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[LISTING], headers={
        "Link": '<https://api.simplyrets.com/properties?lastId=1005252&limit=20>; rel="next"',
        "X-Total-Count": "21", "X-SimplyRETS-LastUpdate": "2026-10-01T00:00:00Z"}))
    result = await node({"operation": "list_properties", "vendor": "abcmls", "cities": ["Houston", "Austin"],
        "status": ["Active", "Pending"], "modified": "2026-10-01T00:00:00Z", "count": True, "limit": 20}).execute({})
    assert requests[0].url.params.get_list("cities") == ["Houston", "Austin"]
    assert requests[0].url.params.get_list("status") == ["Active", "Pending"]
    assert requests[0].url.params["count"] == "true"
    assert requests[0].url.params["modified"] == "2026-10-01T00:00:00Z"
    assert result["next_page"] == {"lastId": 1005252, "limit": 20}
    assert result["total_count"] == "21"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_simplyrets_errors_and_credentials_do_not_leak(monkeypatch, status):
    transport(monkeypatch, lambda req: httpx.Response(status, json={"error": status, "message": "Denied fixture-secret"}))
    with pytest.raises(ValueError) as err:
        await node({"operation": "get_account_metadata"}).execute({})
    assert f"HTTP {status}" in str(err.value)
    assert "fixture-secret" not in str(err.value)


@pytest.mark.asyncio
async def test_simplyrets_redirect_pagination_refused(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json=[], headers={
        "Link": '<https://attacker.example/properties?lastId=9>; rel="next"'}))
    with pytest.raises(ValueError, match="pagination URL"):
        await node({"operation": "list_properties"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_simplyrets_poll_paginates_and_only_emits_new_versions(monkeypatch):
    first = deepcopy(LISTING)
    second = {**LISTING, "mlsId": 1005253, "modified": None}
    def reply(req):
        if req.url.params.get("lastId"):
            return httpx.Response(200, json=[second])
        return httpx.Response(200, json=[first], headers={
            "Link": '<https://api.simplyrets.com/properties?lastId=1005252&limit=500>; rel="next"'})
    requests = transport(monkeypatch, reply)
    n = node({"operation": "on_new_or_updated_property", "vendor": "abcmls", "cities": ["Houston"]})
    seen = set()
    async def unseen(items, key):
        fresh = [row for row in items if key(row) not in seen]
        seen.update(key(row) for row in items)
        return fresh
    n._filter_unseen = unseen
    out = await n.execute({})
    assert out["new_or_updated_count"] == 2
    assert (await n.execute({}))["new_or_updated_count"] == 0
    # Even a feed with no modified timestamp must detect a changed listing.
    second["listPrice"] = 400000
    changed = await n.execute({})
    assert changed["listings"] == [second]
    assert all(req.url.params["vendor"] == "abcmls" and req.url.params.get_list("cities") == ["Houston"] for req in requests)
    assert "offset" not in requests[1].url.params
    event = native.SimplyRETSNode.resolve_agent_event(out)
    for value in ("123 Test Street", "John Doe", "325275", "1005252", "abcmls"):
        assert value in event["text"]
    assert native.SimplyRETSNode.should_propagate_output(changed, {"operation": "on_new_or_updated_property"})
    assert not native.SimplyRETSNode.should_propagate_output({"new_or_updated_count": 0}, {"operation": "on_new_or_updated_property"})


@pytest.mark.asyncio
async def test_simplyrets_incomplete_poll_never_changes_seen_state(monkeypatch):
    transport(monkeypatch, [LISTING] * 500)
    n = node({"operation": "on_new_or_updated_property"})
    n._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="full page"):
        await n.execute({})
    n._filter_unseen.assert_not_awaited()


def test_simplyrets_trigger_scope_and_manual_credentials():
    cfg = {"operation": "on_new_or_updated_property", "vendor": "abcmls"}
    original = poll_scope(native.SimplyRETSNode, cfg)
    assert original == poll_scope(native.SimplyRETSNode, {**cfg, "label": "New label", "goal": "ignored"})
    assert original != poll_scope(native.SimplyRETSNode, {**cfg, "vendor": "xyzmls"})
    assert original != poll_scope(native.SimplyRETSNode, {**cfg, "cities": ["Houston"]})
    assert native.SimplyRETSCredential(api_key="fixture-key", api_secret="fixture-secret").credential_type == "simplyrets_api_key"
    for key in ("api_key", "api_secret"):
        with pytest.raises(ValidationError):
            native.SimplyRETSCredential(**{**CREDENTIAL, key: "header:invalid"})
    with pytest.raises(ValueError):
        node({"operation": "get_property", "mlsId": "../invalid"})


@pytest.mark.asyncio
async def test_simplyrets_connection_evidence_lists_account_feeds_without_vendor(monkeypatch):
    requests = transport(monkeypatch, {"vendors": ["abcmls", "xyzmls"], "endpoints": ["/properties"]})
    options = await native.SimplyRETSNode.load_field_options("vendor", CREDENTIAL)
    assert options == [{"value": "abcmls", "label": "abcmls"}, {"value": "xyzmls", "label": "xyzmls"}]
    assert requests[0].method == "OPTIONS" and requests[0].url.path == "/"
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_simplyrets_poll_first_run_baselines_and_changed_listing_emits(monkeypatch):
    row = deepcopy(LISTING)
    transport(monkeypatch, lambda req: httpx.Response(200, json=[row]))
    n = node({"operation": "on_new_or_updated_property"})
    state = {}
    async def update(mutator, **kwargs):
        following, result = mutator(state)
        if following is not None:
            state.clear()
            state.update(following)
        return result
    n._update_node_state = update
    assert (await n.execute({}))["new_or_updated_count"] == 0
    assert (await n.execute({}))["new_or_updated_count"] == 0
    row["modified"] = "2026-10-02T00:00:00Z"
    assert (await n.execute({}))["listings"] == [row]
    assert (await n.execute({}))["new_or_updated_count"] == 0
