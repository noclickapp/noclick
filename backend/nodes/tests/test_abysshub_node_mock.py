"""Run the native node against the provider's verbatim OpenAPI examples."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import abysshub_node as api
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/abysshub/responses.json").read_text())["examples"]
RUN_ID = EXAMPLES["getRun_200"]["id"]
AUTH = {"credential_type": "abysshub_api_key", "api_key": "abyss_sk_fixture_only"}


def node(operation, **config):
    return NodeFactory.create_node(node_id="abysshub-test", node_type="automation-abysshub",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.abysshub.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers={"Content-Type": "application/json"})
        return httpx.Response(status, json=payload)

    monkeypatch.setattr(api, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(
        **kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.parametrize("operation,config,method,path,example", [
    ("get_key", {}, "GET", "/v1/key", "getKey_200"),
    ("get_widget", {"widget_id": "widget_1660"}, "GET", "/v1/widgets/widget_1660", "getWidget_200"),
    ("prepare_upload", {"widget_id": "widget_1660", "field": "data", "filename": "sales.csv", "size": 48213}, "POST", "/v1/widgets/widget_1660/uploads", "createUpload_200"),
    ("run_widget", {"widget_id": "widget_1660", "input": {"title": "Sales by month", "data": "https://example.com/sales.csv"}, "max_price": 5}, "POST", "/v1/widgets/widget_1660/runs", "createRun_200"),
    ("start_widget", {"widget_id": "widget_1660"}, "POST", "/v1/widgets/widget_1660/runs", "createRun_202"),
    ("list_runs", {"limit": 100, "starting_after": RUN_ID}, "GET", "/v1/runs", "listRuns_200"),
    ("get_run", {"run_id": RUN_ID}, "GET", f"/v1/runs/{RUN_ID}", "getRun_200"),
    ("wait_for_run", {"run_id": RUN_ID}, "GET", f"/v1/runs/{RUN_ID}", "getRun_200"),
    ("wake_run", {"run_id": RUN_ID}, "POST", f"/v1/runs/{RUN_ID}/wake", "wakeRun_200"),
])
async def test_abysshub_documented_operations(transport, operation, config, method, path, example):
    requests, replies = transport
    expected = EXAMPLES[example]
    replies.append((int(example[-3:]), expected))
    assert await node(operation, **config).execute({}) == {"status": "success", "data": expected}
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if operation in ("run_widget", "start_widget"):
        body = json.loads(request.content)
        assert body == {"input": config.get("input", {}), "wait": operation == "run_widget",
                        **({"max_price": 5} if operation == "run_widget" else {})}
    elif operation == "prepare_upload":
        assert json.loads(request.content) == {"field": "data", "filename": "sales.csv", "size": 48213}
    elif operation == "list_runs":
        assert dict(request.url.params) == {"limit": "100", "starting_after": RUN_ID}
    elif operation in ("get_run", "wait_for_run"):
        assert request.url.params["wait"] == ("true" if operation == "wait_for_run" else "false")


async def test_abysshub_held_response_and_idempotency(transport):
    requests, replies = transport
    expected = EXAMPLES["createRun_202"]
    replies.append((202, b"  \n " + json.dumps(expected).encode()))
    result = await node("run_widget", widget_id="widget_1660", idempotency_key="same-press").execute({})
    assert result["status"] == "success"
    assert result["data"]["status"] == "queued"
    assert requests[0].headers["Idempotency-Key"] == "same-press"
    assert len(requests) == 1


async def test_abysshub_json_editor_input(transport):
    requests, replies = transport
    replies.append((202, EXAMPLES["createRun_202"]))
    await node("start_widget", widget_id="widget_1660", input='{"title":"Sales by month","data":"https://example.com/sales.csv"}').execute({})
    assert json.loads(requests[0].content)["input"] == {"title": "Sales by month", "data": "https://example.com/sales.csv"}


async def test_abysshub_key_rejection_preserves_provider_message(transport):
    requests, replies = transport
    replies.append((401, {"error": {"code": "invalid_api_key", "message": "This API Key is not valid."}, "request_id": "req_1"}))
    with pytest.raises(ValueError, match="invalid_api_key: This API Key is not valid"):
        await node("get_key").execute({})
    assert len(requests) == 1


async def test_abysshub_failed_run_is_a_result_not_a_request_failure(transport):
    _, replies = transport
    expected = EXAMPLES["getRun_failed_200"]
    replies.append((200, expected))
    result = await node("get_run", run_id=expected["id"]).execute({})
    assert result == {"status": "success", "data": expected}
    event = api.AbyssHubNode.resolve_agent_event({"runs": [expected]})
    assert expected["error"]["message"] in event["text"]


async def test_abysshub_private_widget_token_is_path_encoded(transport):
    requests, replies = transport
    replies.append((200, EXAMPLES["getWidget_200"]))
    await node("get_widget", widget_id="private/token?x=1").execute({})
    assert b"private%2Ftoken%3Fx%3D1" in requests[0].url.raw_path
    assert not requests[0].url.query


def stateful(instance, initial=None):
    state = deepcopy(initial or {})
    instance._load_node_state = AsyncMock(side_effect=lambda: deepcopy(state))

    async def update(mutator, **kwargs):
        new, result = mutator(deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result

    instance._update_node_state = update
    return state


async def test_abysshub_poll_baselines_then_emits_once_with_agent_context(transport):
    _, replies = transport
    instance = node("on_new_run")
    stateful(instance)
    page = deepcopy(EXAMPLES["listRuns_200"])
    replies.append((200, page))
    assert await instance.execute({}) == {"runs": [], "new_run_count": 0}
    assert instance.trigger_produced_no_event({})
    new_run = {**page["data"][0], "id": "run_" + "A" * 24}
    replies.append((200, {"data": [new_run, *page["data"]], "has_more": False}))
    result = await instance.execute({})
    assert result == {"runs": [new_run], "new_run_count": 1}
    event = instance.resolve_agent_event(result)
    assert new_run["id"] in event["text"] and new_run["widget"] in event["text"]
    assert new_run["status"] in event["text"] and new_run["created_at"] in event["text"]
    assert instance.trigger_emitted_event(result)
    replies.append((200, {"data": [new_run, *page["data"]], "has_more": False}))
    assert (await instance.execute({}))["new_run_count"] == 0


async def test_abysshub_poll_follows_pages_until_known_run(transport):
    requests, replies = transport
    instance = node("on_new_run")
    stateful(instance, {"seen_ids": [RUN_ID], "scope": poll_scope(api.AbyssHubNode, {"operation": "on_new_run"})})
    first = {**EXAMPLES["getRun_200"], "id": "run_" + "B" * 24}
    replies.extend([(200, {"data": [first], "has_more": True}),
                    (200, {"data": [EXAMPLES["getRun_200"]], "has_more": True})])
    assert (await instance.execute({}))["runs"] == [first]
    assert requests[1].url.params["starting_after"] == first["id"]
    assert len(requests) == 2


async def test_abysshub_poll_does_not_advance_state_after_api_failure(transport):
    _, replies = transport
    instance = node("on_new_run")
    state = stateful(instance, {"seen_ids": []})
    replies.append((429, {"error": {"code": "rate_limited", "message": "Try again later."}}))
    with pytest.raises(ValueError, match="rate_limited"):
        await instance.execute({})
    assert state == {"seen_ids": []}


@pytest.mark.parametrize("operation,config", [
    ("get_run", {"run_id": "not-a-run"}),
    ("list_runs", {"limit": 101}),
    ("list_runs", {"starting_after": "invalid"}),
    ("prepare_upload", {"widget_id": "widget_1660", "field": "", "filename": "sales.csv"}),
    ("run_widget", {"widget_id": "widget_1660", "idempotency_key": "bad\nheader"}),
    ("run_widget", {"widget_id": "widget_1660", "input": "[]"}),
    ("run_widget", {"widget_id": "widget_1660", "input": "broken JSON"}),
])
def test_abysshub_contract_input_constraints(operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)


def test_abysshub_manual_credential_and_trigger_declarations():
    credential = api.AbyssHubAPIKeyCredential(api_key="abyss_sk_fixture_only")
    assert credential.credential_type == "abysshub_api_key"
    assert not api.AbyssHubAPIKeyCredential.model_fields["credential_type"].is_required()
    assert api.AbyssHubNode.connection_evidence.identity_operation == "get_key"
    assert api.OnNewRunConfig.model_fields["operation"].json_schema_extra["x-is-trigger"]
    assert api.AbyssHubNode.resolve_agent_event({"runs": []}) is None
