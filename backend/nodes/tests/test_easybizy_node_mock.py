"""Verify Easybizy requests and stateful polling without an account.

Fixtures cite the pinned contract and the provider's documentation sample
renderer. Tests cover auth, writes, pagination, baselines and changed versions.
"""
from contextlib import asynccontextmanager
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import easybizy_node as mod
from nodes.core.base import ConfigValidationError

FIXTURES = Path(__file__).parent / "fixtures" / "easybizy"
CASES = json.loads((FIXTURES / "request_cases.json").read_text())["cases"]
EXAMPLES = json.loads((FIXTURES / "provider_examples.json").read_text())
CREDENTIAL = {"credential_type": "easybizy_api_key", "api_key": "test-api-key-abc123", "api_secret": "test-api-secret-def456"}


def node(config):
    parsed = mod.EasybizyNode.parse_config({"config": config, "credentials": CREDENTIAL})
    return mod.EasybizyNode(node_id="easybizy-test", node_type="automation-easybizy",
                           node_data={"config": config}, config=parsed)


@pytest.fixture
def transport(monkeypatch):
    def install(handler):
        @asynccontextmanager
        async def client(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
                yield session
        monkeypatch.setattr(mod, "guarded_async_client", client)
    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_public_contract_requests(transport, case):
    seen = []
    def respond(request):
        seen.append(request)
        assert request.url.host == "api.easybizy.net"
        assert request.method == case["method"]
        assert request.url.path == case["path"]
        assert request.headers["x-api-key"] == CREDENTIAL["api_key"]
        assert request.headers["x-api-secret"] == CREDENTIAL["api_secret"]
        if request.content:
            expected = {key: value for key, value in case["config"].items()
                        if key not in {"operation", "id"} and not (key.endswith("Id") and "activity-info" in case["path"])}
            assert json.loads(request.content) == expected
            assert not request.url.query
        else:
            for key, value in case["config"].items():
                if key == "filter":
                    assert json.loads(request.url.params[key]) == value
                elif key in {"top", "skip", "startDate", "endDate"}:
                    assert request.url.params[key] == str(value)
        if request.method in {"PATCH", "DELETE"} and "scheduling" not in case["path"]:
            return httpx.Response(204)
        return httpx.Response(200, json={"data": []})
    transport(respond)
    assert (await node(case["config"]).execute({})).get("status") != "error"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_patch_preserves_consent_and_clears_substatus(transport):
    bodies = []
    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(204)
    transport(respond)
    await node({"operation": "update_customer", "id": 42, "firstName": "Dana"}).execute({})
    await node({"operation": "update_lead", "id": 42, "subStatus": None}).execute({})
    assert bodies == [{"firstName": "Dana"}, {"subStatus": None}]


def stateful(instance, state):
    async def update(mutator, **kwargs):
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return result
    instance._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,resource,schema", [
    ("on_customer_changed", "customers", "Customer"),
    ("on_lead_changed", "leads", "Lead"),
])
async def test_poll_baseline_changes_and_scope(transport, operation, resource, schema):
    record = copy.deepcopy(EXAMPLES[schema])
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.path == "/api/v1/" + resource
        assert request.url.params["order"] == "-timeCreated"
        return httpx.Response(200, json={"data": [record]})
    transport(respond)
    instance = node({"operation": operation})
    state = {}
    stateful(instance, state)
    assert (await instance.execute({}))["count"] == 0
    assert (await instance.execute({}))["count"] == 0
    record["timeUpdated"] = "2026-08-16T06:29:03.000Z"
    output = await instance.execute({})
    assert output["count"] == 1
    assert instance.trigger_emitted_event(output)
    event = instance.resolve_agent_event(output)
    assert "Easybizy" in event["text"] and str(record["id"]) in event["text"]
    assert resource in event["text"]
    assert (await instance.execute({}))["count"] == 0
    narrowed = node({"operation": operation, "modified_since": "2026-08-02T00:00:00.000Z"})
    stateful(narrowed, state)
    assert (await narrowed.execute({}))["count"] == 0
    assert json.loads(requests[-1].url.params["filter"]) == {"timeUpdated": {"gte": "2026-08-02T00:00:00.000Z"}}


@pytest.mark.asyncio
async def test_poll_pages_and_does_not_consume_partial_failure(transport):
    records = [{**EXAMPLES["Customer"], "id": i} for i in range(501)]
    mode = ["success"]
    def respond(request):
        skip = int(request.url.params["skip"])
        if skip and mode[0] == "failure":
            return httpx.Response(503, text="Please retry")
        return httpx.Response(200, json={"data": records[skip:skip+500]})
    transport(respond)
    instance = node({"operation": "on_customer_changed"})
    state = {"seen_ids": []}
    stateful(instance, state)
    assert (await instance.execute({}))["count"] == 501
    old = copy.deepcopy(state)
    mode[0] = "failure"
    assert (await instance.execute({}))["http_status"] == 503
    assert state == old


@pytest.mark.asyncio
async def test_auth_rejection_keeps_provider_message(transport):
    transport(lambda request: httpx.Response(401, text='{"message":"API credentials rejected"}'))
    assert (await node({"operation": "list_customers"}).execute({})) == {
        "status": "error", "http_status": 401, "error": '{"message":"API credentials rejected"}'}


@pytest.mark.asyncio
async def test_redirect_is_not_followed(transport):
    transport(lambda request: httpx.Response(302, headers={"Location": "https://example.com"}))
    assert (await node({"operation": "list_customers"}).execute({}))["http_status"] == 302


@pytest.mark.parametrize("secret", ["", "https://api.easybizy.net", "<token>", "one\ntwo"])
def test_invalid_manual_secret(secret):
    with pytest.raises(ValidationError):
        mod.EasybizyCredential(api_key=secret, api_secret="real-secret-value")


def test_manual_type_and_trim():
    value = mod.EasybizyCredential(api_key=" real-key-value ", api_secret=" real-secret-value ")
    assert value.credential_type == "easybizy_api_key"
    assert value.api_key == "real-key-value"


def test_contact_and_filter_requirements():
    with pytest.raises(ConfigValidationError):
        node({"operation": "create_lead"})
    with pytest.raises(ConfigValidationError):
        node({"operation": "list_customers", "filter": {}, "search": "Dana"})
