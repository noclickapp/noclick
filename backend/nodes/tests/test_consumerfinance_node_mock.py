"""Contract routes, wire parameters, and polling against a recorded public response."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import consumerfinance_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

SEARCH = json.loads((Path(__file__).parent / "fixtures/consumerfinance/public_search.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="consumerfinance-test", node_type="automation-consumerfinance", node_data={"config": config})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body,key", [
    ({"operation": "search_complaints"}, "/", SEARCH, "data"),
    ({"operation": "get_complaint", "complaint_id": 123456}, "/123456", {"complaint_id": 123456, "company": "Example"}, "data"),
    ({"operation": "suggest_companies", "text": "Ba"}, "/_suggest_company", ["BANK OF AMERICA, NATIONAL ASSOCIATION"], "suggestions"),
    ({"operation": "suggest_zip_codes", "text": "20"}, "/_suggest_zip", ["20001", "20002"], "suggestions"),
])
async def test_contract_operations(monkeypatch, config, path, body, key):
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result[key] == body
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url).split("?")[0] == native.BASE + path
    assert request.method == "GET" and not request.content
    assert request.headers["Accept"] == "application/json"
    assert "authorization" not in request.headers
    assert "format" not in request.url.params  # Never accidentally activate CSV export.


@pytest.mark.asyncio
async def test_all_search_filters_and_pagination(monkeypatch):
    requests = transport(monkeypatch, SEARCH)
    config = {
        "operation": "search_complaints", "search_term": "mortgage", "field": "company",
        "company": ["Bank A", "Bank B"], "company_public_response": ["Company has responded"],
        "company_response": ["Closed with explanation"], "company_received_min": "2017-03-04",
        "company_received_max": "2017-04-04", "date_received_min": "2017-03-04", "date_received_max": "2017-04-04",
        "issue": ["Getting a Loan"], "product": ["Mortgage•FHA mortgage"], "state": ["CA", "VA"],
        "submitted_via": ["Web"], "tags": ["Older American"], "timely": ["Yes"], "zip_code": ["20001"],
        "frm": 25, "size": 25, "search_after": "123_456", "sort": "created_date_desc",
        "no_aggs": True, "no_highlight": False,
    }
    await node(config).execute({})
    params = requests[0].url.params
    assert set(params) == set(config) - {"operation"}
    for key, value in config.items():
        if key == "operation":
            continue
        if isinstance(value, list):
            assert params.get_list(key) == value
        else:
            assert params[key] == (str(value).lower() if isinstance(value, bool) else str(value))


@pytest.mark.parametrize("config", [
    {"operation": "search_complaints", "size": 101},
    {"operation": "search_complaints", "frm": 0},
    {"operation": "search_complaints", "sort": "updated_date_desc"},
    {"operation": "search_complaints", "date_received_min": "not-a-date"},
    {"operation": "search_complaints", "company_received_min": "2017-04-04", "company_received_max": "2017-03-04"},
    {"operation": "get_complaint", "complaint_id": "../secrets"},
    {"operation": "get_complaint", "complaint_id": 10000000000},
    {"operation": "suggest_companies"},
    {"operation": "suggest_zip_codes", "text": ""},
    {"operation": "suggest_companies", "text": "Ba", "company": ["unsupported filter"]},
    {"operation": "create_complaint"},
])
def test_invalid_configs(config):
    assert native.ConsumerfinanceNode.validate_config({"config": config})["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body,status", [
    ("search_complaints", {"error": "OpenSearch failed"}, 200),
    ("search_complaints", {"hits": {"hits": "bad"}}, 200),
    ("search_complaints", {"hits": {"hits": []}}, 429),
    ("search_complaints", {"hits": {"hits": []}}, 302),
    ("suggest_companies", {"unexpected": []}, 200),
    ("suggest_zip_codes", [12], 200),
    ("get_complaint", [], 200),
])
async def test_provider_errors(monkeypatch, operation, body, status):
    transport(monkeypatch, body, status)
    config = {"operation": operation}
    if operation.startswith("suggest_"):
        config["text"] = "Ba"
    if operation == "get_complaint":
        config["complaint_id"] = 123456
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await node(config).execute({})


@pytest.mark.asyncio
async def test_poll_baselines_deduplicates_and_rebaselines_scope(monkeypatch):
    requests = transport(monkeypatch, SEARCH)
    poll = node({"operation": "on_new_complaint", "company": ["Bank A"], "date_received_min": "2017-03-04"})
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    poll._update_node_state = update
    assert (await poll.execute({}))["new_complaint_count"] == 0
    assert poll.trigger_produced_no_event({})
    assert (await poll.execute({}))["new_complaint_count"] == 0
    state["seen_ids"] = []
    result = await poll.execute({})
    assert result["complaints"] == [SEARCH["hits"]["hits"][0]["_source"]]
    assert poll.trigger_emitted_event(result)
    event = poll.resolve_agent_event(result)
    complaint = result["complaints"][0]
    assert str(complaint["complaint_id"]) in event["text"]
    assert complaint["company"] in event["text"]
    assert complaint["issue"] in event["text"]
    assert (await poll.execute({}))["new_complaint_count"] == 0
    poll._config = native.ConsumerfinanceFullConfig(config={"operation": "on_new_complaint", "company": ["Bank B"]})
    assert (await poll.execute({}))["new_complaint_count"] == 0
    params = requests[0].url.params
    assert dict(params) == {"company": "Bank A", "date_received_min": "2017-03-04", "field": "all", "size": "100", "sort": "created_date_desc", "no_aggs": "true", "no_highlight": "true"}
    assert not any(key in params for key in native.PollTriggerConfigBase.model_fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [42, "42", 0])
async def test_poll_accepts_contract_and_public_api_ids(monkeypatch, identifier):
    body = {"hits": {"hits": [{"_source": {"complaint_id": identifier}}]}}
    transport(monkeypatch, body)
    poll = node({"operation": "on_new_complaint"})

    async def update(mutator, **kwargs):
        return mutator({"seen_ids": []})[1]

    poll._update_node_state = update
    assert (await poll.execute({}))["new_complaint_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [{}, {"complaint_id": True}, {"complaint_id": "invalid"}, None])
async def test_malformed_poll_does_not_advance_state(monkeypatch, source):
    transport(monkeypatch, {"hits": {"hits": [{"_source": source}]}})
    poll = node({"operation": "on_new_complaint"})

    async def update(*args, **kwargs):
        pytest.fail("Malformed responses must not write the seen set")

    poll._update_node_state = update
    with pytest.raises(ValueError):
        await poll.execute({})


def test_public_api_metadata_and_poll_scope():
    assert native.ConsumerfinanceFullConfig.model_fields["credentials"].annotation is type(None)
    assert native.ConsumerfinanceNode.connection_evidence.proves == "reachability"
    config = {"operation": "on_new_complaint", "state": ["CA"]}
    assert poll_scope(native.ConsumerfinanceNode, config) is not None
    assert poll_scope(native.ConsumerfinanceNode, config) == poll_scope(native.ConsumerfinanceNode, {**config, "schedule": {"frequency": "minutes", "interval": 10}})
    assert poll_scope(native.ConsumerfinanceNode, config) == poll_scope(native.ConsumerfinanceNode, {**config, "goal": "Watch complaints", "label": "My trigger", "credentialIds": {}})
    assert poll_scope(native.ConsumerfinanceNode, config) != poll_scope(native.ConsumerfinanceNode, {**config, "state": ["VA"]})
