"""Contract routes and official Atlassian example responses, plus poll lifecycle."""
import base64
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import jira_service_management_alert_ca_node as m
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / "fixtures/jira-service-management-alert-ca"
EXAMPLES = json.loads((FIXTURES / "official-examples.json").read_text())["responses"]
CASES = json.loads((FIXTURES / "operation-cases.json").read_text())
CREDENTIAL = {"credential_type": "jira_service_management_alert_ca_token",
              "email": "email@example.com", "api_token": "test-api-value-93427",
              "cloud_id": "3d916f39-0d68-4729-a556-7ac5f30a1c62"}
REAL_CLIENT = httpx.AsyncClient


def node(config, credential=None):
    data = {"config": config, "credentials": credential or CREDENTIAL}
    return m.JiraServiceManagementAlertNode("test", m.JiraServiceManagementAlertNode.integration_type,
                                           data, config=m.JiraServiceManagementAlertNode.parse_config(data))


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(m.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(
        **kw, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: "jira-service-management-alert-ca-" + c["config"]["operation"])
async def test_documented_operation(monkeypatch, case):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == case["method"]
        assert request.url.host == "api.atlassian.com"
        assert request.url.path == f"/jsm/ops/api/{CREDENTIAL['cloud_id']}/v1" + case["route"]
        if case["config"]["operation"] == "get_alert_by_alias":
            assert request.url.params["alias"] == case["config"]["alias"]
        assert request.headers["authorization"] == "Basic " + base64.b64encode(
            f"{CREDENTIAL['email']}:{CREDENTIAL['api_token']}".encode()).decode()
        assert (json.loads(request.content) if request.content else None) == case["body"]
        if case["config"]["operation"] == "delete_note":
            return httpx.Response(204)
        return httpx.Response(200, json=EXAMPLES[case["response"]])
    mock_http(monkeypatch, handler)
    out = await node(case["config"]).execute({})
    assert len(calls) == 1
    if out["status"] == "accepted":
        assert out["completed"] is False
        assert out["request_id"] == EXAMPLES["accepted"]["requestId"]
    elif case["config"]["operation"] != "delete_note":
        assert out["data"] == EXAMPLES[case["response"]]


@pytest.mark.asyncio
async def test_queries_are_provider_named_and_pagination_preserved(monkeypatch):
    def handler(request):
        assert dict(request.url.params) == {"size": "25", "offset": "50", "sort": "createdAt",
            "order": "asc", "query": "status:open", "from": "1704440650", "to": "1704440660"}
        return httpx.Response(200, json=EXAMPLES["alerts"])
    mock_http(monkeypatch, handler)
    out = await node({"operation": "list_alerts", "size": 25, "offset": 50, "sort": "createdAt",
                      "order": "asc", "query": "status:open", "from_time": 1704440650,
                      "to_time": 1704440660}).execute({})
    assert out["data"]["links"] == EXAMPLES["alerts"]["links"]


@pytest.mark.asyncio
async def test_path_ids_are_encoded_without_changing_host(monkeypatch):
    def handler(request):
        assert b"%2F" in request.url.raw_path
        assert request.url.host == "api.atlassian.com"
        return httpx.Response(200, json=EXAMPLES["alert"])
    mock_http(monkeypatch, handler)
    await node({"operation": "get_alert", "alert_id": "an/id?x=1"}).execute({})


@pytest.mark.parametrize("field,value", [("cloud_id", "https://evil.example"), ("cloud_id", "../x"),
    ("email", "email@example.com:secret"), ("email", "bad"), ("api_token", "two words")])
def test_credential_validation(field, value):
    with pytest.raises(ValidationError):
        m.JiraServiceManagementAlertTokenCredential.model_validate({**CREDENTIAL, field: value})


def test_manual_type_default_and_shaping():
    assert m.JiraServiceManagementAlertTokenCredential.model_validate({
        "email": " email@example.com ", "api_token": "test-api-value-93427",
        "cloud_id": " cloud-id-1 "}).model_dump() == {**CREDENTIAL, "cloud_id": "cloud-id-1"}


@pytest.mark.parametrize("config", [
    {"operation": "list_alerts", "offset": 19999},
    {"operation": "list_alerts", "size": 101},
    {"operation": "list_alerts", "from_time": 10, "to_time": 1},
    {"operation": "add_tags", "alert_id": "a", "tags": " , "},
    {"operation": "snooze_alert", "alert_id": "a", "end_time": "2024-01-05T12:00:00"},
])
def test_config_validation(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_http_failures_are_not_success_or_secret_leaks(monkeypatch, status):
    mock_http(monkeypatch, lambda req: httpx.Response(status, json={"error": CREDENTIAL["api_token"]}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_alert", "message": "test"}).execute({})
    assert str(status) in str(exc.value)
    assert CREDENTIAL["api_token"] not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {}, {"values": {}}, {"values": [None]}])
async def test_bad_list_response_does_not_baseline(monkeypatch, body):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "on_new_alert"}).execute({})


@pytest.mark.asyncio
async def test_invalid_json_and_timeout(monkeypatch):
    mock_http(monkeypatch, lambda req: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "get_alert", "alert_id": "a"}).execute({})
    def timeout(req):
        raise httpx.ReadTimeout(CREDENTIAL["api_token"], request=req)
    mock_http(monkeypatch, timeout)
    with pytest.raises(ValueError, match="timed out") as exc:
        await node({"operation": "get_alert", "alert_id": "a"}).execute({})
    assert CREDENTIAL["api_token"] not in str(exc.value)


@pytest.mark.asyncio
async def test_poll_documented_payload_baseline_dedup_and_scope(monkeypatch):
    state = {}
    payload = copy.deepcopy(EXAMPLES["alerts"])
    def handler(req):
        assert dict(req.url.params) == {"size": "100", "offset": "0", "sort": "createdAt", "order": "desc"}
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handler)
    async def update(self, mutator, skip_result=None):
        nonlocal state
        new_state, result = mutator(copy.deepcopy(state))
        if new_state is not None:
            state = new_state
        return result
    monkeypatch.setattr(m.JiraServiceManagementAlertNode, "_update_node_state", update)
    n = node({"operation": "on_new_alert"})
    first = await n.execute({})
    assert first["alerts"] == []
    assert n.trigger_produced_no_event(first)
    assert n.resolve_agent_event(first) is None
    # A second published example ID models a newly returned alert.
    second = copy.deepcopy(payload["values"][0])
    second["id"] = EXAMPLES["request_status"]["alertId"]
    payload["values"].append(second)
    out = await n.execute({})
    assert out["alerts"] == [second]
    assert n.should_propagate_output(out, {"operation": "on_new_alert"})
    event = n.resolve_agent_event(out)
    assert second["id"] in event["text"] and second["message"] in event["text"]
    assert "owner:" in event["text"] and "source:" in event["text"]
    assert (await n.execute({}))["new_alert_count"] == 0
    assert poll_scope(type(n), {"operation": "on_new_alert"}) == poll_scope(type(n), {
        "operation": "on_new_alert", "label": "renamed", "goal": "cosmetic"})
    assert poll_scope(type(n), {"operation": "on_new_alert"}) != poll_scope(type(n), {
        "operation": "on_new_alert", "query": "status:open"})


@pytest.mark.asyncio
async def test_poll_paginates_before_new_item_detection(monkeypatch):
    rows = [{**EXAMPLES["alert"], "id": f"alert-{i}"} for i in range(101)]
    calls = []
    def handler(req):
        offset = int(req.url.params["offset"])
        calls.append(offset)
        return httpx.Response(200, json={"values": rows[offset:offset + 100], "count": 101})
    mock_http(monkeypatch, handler)
    n = node({"operation": "on_new_alert"})
    async def unseen(items, id_fn):
        assert [id_fn(row) for row in items] == [row["id"] for row in rows]
        return items
    monkeypatch.setattr(n, "_filter_unseen", unseen)
    out = await n.execute({})
    assert calls == [0, 100] and out["new_alert_count"] == 101


@pytest.mark.asyncio
async def test_poll_missing_id_and_overlapping_pages_leave_state_untouched(monkeypatch):
    n = node({"operation": "on_new_alert"})
    async def forbidden_update(*args, **kwargs):
        pytest.fail("An invalid alert listing must not change poll state")
    monkeypatch.setattr(n, "_update_node_state", forbidden_update)
    mock_http(monkeypatch, lambda req: httpx.Response(200, json={"values": [{}]}))
    with pytest.raises(ValueError, match="without an ID"):
        await n.execute({})
    mock_http(monkeypatch, lambda req: httpx.Response(200, json={"values": [EXAMPLES["alert"], EXAMPLES["alert"]]}))
    with pytest.raises(ValueError, match="overlap"):
        await n.execute({})
