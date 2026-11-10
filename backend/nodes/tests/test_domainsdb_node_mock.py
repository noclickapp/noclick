"""Contract-shaped transport and poll regression tests; no live credential used."""
from copy import deepcopy
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.domainsdb_node import DomainsdbNode, DomainsdbAPIKeyCredential, ROUTES


def node(operation, **config):
    return NodeFactory.create_node(node_id="domainsdb-test", node_type="automation-domainsdb", node_data={
        "config": {"operation": operation, **config},
        "credentials": {"credential_type": "domainsdb_api_key", "api_key": "test-domain-license-key"}})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path", list(ROUTES.items()))
async def test_routes_and_auth(monkeypatch, operation, path):
    calls = []
    async def request(self, method, url, **kwargs):
        calls.append((method, url, deepcopy(kwargs)))
        return httpx.Response(200, json={"time": "0.01", "domains": [{"domain": "example.com"}]}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    instance = node(operation, **({"zone_id": "co.uk"} if "{zone_id}" in path else {"zone": "com"} if "{zone}" in path else {}))
    instance._filter_unseen = AsyncMock(side_effect=lambda rows, id_fn: rows)
    result = await instance.execute({})
    method, url, kwargs = calls[0]
    assert method == "GET"
    assert url == "https://api.domains-index.com/v1" + path.replace("{zone_id}", "co.uk").replace("{zone}", "com")
    assert ("api_key" in kwargs["params"]) == (path.startswith("/domains/") or path == "/info/api")
    assert "test-domain-license-key" not in str(result)


@pytest.mark.asyncio
async def test_search_preserves_false_dns_filters_and_cursor():
    instance = node("search_domains", isDead=False, A="192.0.2.1", MX="example.com", page="cursor", domain="example", country="US", limit=10)
    instance._request = AsyncMock(return_value={"time": "0.01", "domains": [], "next_page": "next"})
    result = await instance.execute({})
    params = instance._request.call_args.args[1]
    assert params == {"isDead": False, "A": "192.0.2.1", "MX": "example.com", "page": "cursor", "domain": "example", "country": "US", "limit": 10, "api_key": "test-domain-license-key"}
    assert result["data"]["next_page"] == "next"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_added_domain", "on_deleted_domain"])
async def test_poll_baseline_new_dedup_and_agent_event(operation):
    instance = node(operation, date="2026-11-01")
    state = {}
    async def update(mutator, skip_result):
        nonlocal state
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state = new_state
        return result
    instance._update_node_state = update
    first = {"domain": "example.com", "create_date": "2026-11-01T00:00:00Z"}
    second = {"domain": "example.org", "update_date": "2026-11-01T01:00:00Z"}
    instance._request = AsyncMock(return_value={"time": "0.01", "domains": [first]})
    assert (await instance.execute({}))["domains"] == []
    assert instance.trigger_produced_no_event({})
    instance._request.return_value = {"time": "0.01", "domains": [first, second]}
    output = await instance.execute({})
    assert output["domains"] == [second]
    assert instance.trigger_emitted_event(output)
    event = DomainsdbNode.resolve_agent_event(output)
    assert "example.org" in event["text"] and output["change"] in event["text"]
    assert (await instance.execute({}))["domains"] == []


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_recording_seen():
    instance = node("on_added_domain")
    instance._request = AsyncMock(side_effect=[{"time": "0.01", "domains": [{"domain": "example.com"}], "next_page": "two"}, {"time": "0.01", "domains": [{"domain": "example.org"}]}])
    instance._filter_unseen = AsyncMock(side_effect=lambda items, fn: items)
    assert (await instance.execute({}))["domain_count"] == 2
    assert instance._request.call_args.args[1]["page"] == "two"


@pytest.mark.asyncio
async def test_poll_repeated_cursor_never_advances_state():
    instance = node("on_added_domain")
    instance._request = AsyncMock(return_value={"time": "0.01", "domains": [], "next_page": "repeated"})
    instance._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match="repeats"):
        await instance.execute({})
    instance._filter_unseen.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(403, {}), (200, {"success": "false"}), (200, {"error": "invalid key"}), (200, "invalid")])
async def test_failure_never_reports_connection_success(monkeypatch, status, body):
    async def request(self, method, url, **kwargs):
        return httpx.Response(status, json=body, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    with pytest.raises(ValueError) as error:
        await node("get_api_info").execute({})
    assert "test-domain-license-key" not in str(error.value)


def test_manual_connect_and_poll_scope():
    assert DomainsdbAPIKeyCredential(api_key="actual-license-key").credential_type == "domainsdb_api_key"
    assert DomainsdbNode.schedule_poll_scope({"operation": "on_added_domain", "date": "2026-11-01"}) != DomainsdbNode.schedule_poll_scope({"operation": "on_added_domain", "date": "2026-11-02"})
