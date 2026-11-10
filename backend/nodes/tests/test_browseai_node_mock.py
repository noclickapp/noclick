"""Browse AI requests and official webhook examples without an account."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock
import httpx
import pytest
from nodes.browseai_node import BrowseaiAPIKeyCredential, BrowseaiNode, BrowseaiNodeConfig

FIXTURES = Path(__file__).parent / "fixtures" / "browseai"
CREDENTIAL = {"credential_type": "browseai_api_key", "api_key": "browseai-test-secret-123"}
ROBOT = "robot_xyz789"


def node(config):
    instance = BrowseaiNode(node_id="browseai-test", node_type="automation-browseai",
        node_data={"config": config}, config=BrowseaiNodeConfig.model_validate({"config": config, "credentials": CREDENTIAL}), sio=Mock())
    instance.emit = AsyncMock()
    return instance


@pytest.fixture
def api(monkeypatch):
    calls = []
    response = {"statusCode": 200, "messageCode": "success"}
    async def request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json=response, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    return calls, response


def test_manual_credential_needs_only_api_key():
    credential = BrowseaiAPIKeyCredential(api_key="  browseai-test-secret-123  ")
    assert credential.credential_type == "browseai_api_key"
    assert credential.api_key == CREDENTIAL["api_key"]
    for invalid in ["Bearer browseai-test-secret-123", "https://example.com/key"]:
        with pytest.raises(ValueError):
            BrowseaiAPIKeyCredential(api_key=invalid)


@pytest.mark.asyncio
async def test_task_filters_preserve_false_and_pagination(api):
    calls, response = api
    response["result"] = {"robotTasks": {"items": [], "hasMore": True, "pageNumber": 2, "totalCount": 20}}
    result = await node({"operation": "list_tasks", "robotId": ROBOT, "page": 2, "pageSize": 10,
        "includeRetried": False, "status": "successful", "sort": "-createdAt", "fromDate": 1678795867879}).execute({})
    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", f"https://api.browse.ai/v2/robots/{ROBOT}/tasks")
    assert kwargs["params"] == {"page": 2, "pageSize": 10, "includeRetried": "false", "status": "successful", "sort": "-createdAt", "fromDate": 1678795867879}
    assert kwargs["headers"]["Authorization"] == "Bearer " + CREDENTIAL["api_key"]
    assert result["data"]["result"]["robotTasks"]["hasMore"] is True
    assert CREDENTIAL["api_key"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_bulk_run_uses_documented_array(api):
    calls, _ = api
    example = json.loads((FIXTURES / "bulk_run_input.json").read_text())
    await node(example["config"]).execute({})
    assert calls[0][0] == "POST"
    body = calls[0][2]["json"]
    assert len(body["inputParameters"]) == 2
    assert body["inputParameters"][0]["originUrl"] == "https://www.ycombinator.com/companies/airbnb"
    assert "inputParameters_json" not in body


@pytest.mark.asyncio
async def test_task_and_monitor_writes_send_selected_fields(api):
    calls, _ = api
    await node({"operation": "run_task", "robotId": ROBOT, "recordVideo": False,
        "inputParameters_json": '{"originUrl":"https://www.ycombinator.com/companies/airbnb"}'}).execute({})
    assert calls[0][2]["json"] == {"recordVideo": False, "inputParameters": {"originUrl": "https://www.ycombinator.com/companies/airbnb"}}
    await node({"operation": "update_monitor", "robotId": ROBOT, "monitorId": "monitor/with slash", "status": "paused"}).execute({})
    assert calls[1][0] == "PATCH"
    assert calls[1][1].endswith("/monitors/monitor%2Fwith%20slash")
    assert calls[1][2]["json"] == {"status": "paused"}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["not json", "{}", '[{"originUrl":true}]'])
async def test_bad_bulk_input_never_makes_request(api, value):
    calls, _ = api
    with pytest.raises(ValueError):
        await node({"operation": "create_bulk_run", "robotId": ROBOT, "inputParameters_json": value}).execute({})
    assert calls == []


@pytest.mark.asyncio
async def test_webhook_registration_and_cleanup(api):
    calls, response = api
    response["webhook"] = {"id": "6d7f1218-43fb-4735-ac71-21e81b1ab23e"}
    for operation, event_type in [("on_task_finished", "taskFinished"), ("on_data_changed", "taskCapturedDataChanged"), ("on_table_export_finished", "tableExportFinishedSuccessfully")]:
        config = {"operation": operation, "robotId": ROBOT}
        registered = await BrowseaiNode._register_external_webhook(webhook_url="https://example.com/v2/webhooks/callback/events",
            credential=CREDENTIAL, config=config, node_id="n")
        assert calls[-1][2]["json"] == {"hookUrl": "https://example.com/v2/webhooks/callback/events", "eventType": event_type}
        await BrowseaiNode._unregister_external_webhook(credential=CREDENTIAL, config={**config, **registered}, node_id="n")
        assert calls[-1][0] == "DELETE"
        assert calls[-1][1].endswith("/webhooks/" + response["webhook"]["id"])
    assert BrowseaiNode.webhook_signing_secret_not_issued is True
    assert BrowseaiNode.verify_webhook_signature(b"{}", {}, {}) is True


@pytest.mark.parametrize("fixture,operation", [("task_finished_docs", "on_task_finished"), ("data_changed_docs", "on_data_changed")])
def test_official_events_reach_agent(fixture, operation):
    payload = json.loads((FIXTURES / "events.json").read_text())[fixture]["body"]
    config = {"operation": operation, "robotId": ROBOT}
    assert BrowseaiNode.filter_trigger_payload(payload, config)
    assert not BrowseaiNode.filter_trigger_payload(payload, {**config, "robotId": "another-robot"})
    event = BrowseaiNode.resolve_agent_event(BrowseaiNode.resolve_trigger_payload(payload, config))
    assert event["conversation_key"] == ROBOT
    assert "task_abc123" in event["text"]
    assert "get_task" in event["text"]
    assert "Price" in event["text"]


@pytest.mark.asyncio
async def test_manual_trigger_has_no_event(api):
    calls, _ = api
    result = await node({"operation": "on_task_finished", "robotId": ROBOT}).execute({})
    assert result["status"] == "no_event"
    assert calls == []


@pytest.mark.asyncio
async def test_rejected_key_is_not_success(api):
    _, response = api
    response["messageCode"] = "invalid_api_key"
    with pytest.raises(ValueError, match="invalid_api_key"):
        await node({"operation": "list_robots"}).execute({})
