"""Offline OpsGenie wire contracts; no provider account or live key is used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import opsgenie_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-opsgenie-key"
AUTH = {"credential_type": "opsgenie_api_key", "api_key": TOKEN}
ALERT = {"identifier": "alert-id"}
CASES = [
    ("list_alerts", {"query": "status:open", "offset": 20}, "GET", "/v2/alerts", None),
    ("get_alert", ALERT, "GET", "/v2/alerts/alert-id", None),
    ("create_alert", {"message": "Disk full", "responders": [{"type": "team", "id": "team-id"}]}, "POST", "/v2/alerts", {"message": "Disk full", "priority": "P3", "responders": [{"type": "team", "id": "team-id"}]}),
    ("acknowledge_alert", ALERT, "POST", "/v2/alerts/alert-id/acknowledge", {}),
    ("unacknowledge_alert", ALERT, "POST", "/v2/alerts/alert-id/unacknowledge", {}),
    ("close_alert", {**ALERT, "note": "Resolved"}, "POST", "/v2/alerts/alert-id/close", {"note": "Resolved"}),
    ("delete_alert", {**ALERT, "user": "operator"}, "DELETE", "/v2/alerts/alert-id", None),
    ("add_note", {**ALERT, "note": "Investigating"}, "POST", "/v2/alerts/alert-id/notes", {"note": "Investigating"}),
    ("list_notes", {**ALERT, "offset": "opaque-next"}, "GET", "/v2/alerts/alert-id/notes", None),
    ("add_tags", {**ALERT, "tags": ["production"]}, "POST", "/v2/alerts/alert-id/tags", {"tags": ["production"]}),
    ("update_alert_message", {**ALERT, "message": "Updated"}, "PUT", "/v2/alerts/alert-id/message", {"message": "Updated"}),
    ("update_alert_priority", {**ALERT, "priority": "P1"}, "PUT", "/v2/alerts/alert-id/priority", {"priority": "P1"}),
    ("get_request_status", {"request_id": "request-id"}, "GET", "/v2/alerts/requests/request-id", None),
    ("list_teams", {}, "GET", "/v2/teams", None),
    ("list_users", {"offset": 100}, "GET", "/v2/users", None),
    ("list_schedules", {}, "GET", "/v2/schedules", None),
    ("get_on_calls", {"identifier": "Schedule name", "schedule_identifier_type": "name", "flat": True}, "GET", "/v2/schedules/Schedule name/on-calls", None),
    ("list_heartbeats", {}, "GET", "/v2/heartbeats", None),
    ("create_heartbeat", {"name": "worker", "interval": 5, "interval_unit": "minutes"}, "POST", "/v2/heartbeats", {"name": "worker", "interval": 5, "intervalUnit": "minutes", "enabled": True}),
    ("ping_heartbeat", {"name": "worker"}, "GET", "/v2/heartbeats/worker/ping", None),
]


def node(operation, config=None, credential=None):
    return NodeFactory.create_node(node_id="opsgenie-test", node_type="automation-opsgenie",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": credential or AUTH})


def transport(monkeypatch, code=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(code, json=body if body is not None else {"data": [], "requestId": "request-id"})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_every_operation_uses_one_published_route(monkeypatch, operation, config, method, path, body):
    accepted = method in {"POST", "PUT", "DELETE"} and operation != "create_heartbeat" or operation == "ping_heartbeat"
    response = {"result": "Request will be processed", "requestId": "request-id"} if accepted else {"data": {"isSuccess": True}} if operation == "get_request_status" else {"data": []}
    requests = transport(monkeypatch, 202 if accepted else 201 if operation == "create_heartbeat" else 200, response)
    result = await node(operation, config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.headers["Authorization"] == "GenieKey " + TOKEN
    assert request.url.host == "api.opsgenie.com"
    assert json.loads(request.content) == body if body is not None else not request.content
    if "identifier" in config and operation != "get_on_calls":
        assert request.url.params["identifierType"] == "id"
    if operation == "get_on_calls":
        assert dict(request.url.params) == {"scheduleIdentifierType": "name", "flat": "true"}
    if operation == "list_notes": assert request.url.params["offset"] == "opaque-next"
    if operation == "list_users": assert request.url.params["offset"] == "100"
    if operation == "delete_alert": assert request.url.params["user"] == "operator"
    if accepted:
        assert result["status"] == "accepted" and result["request_id"] == "request-id"
        assert "success" not in result
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_eu_region_and_encoded_alias(monkeypatch):
    requests = transport(monkeypatch)
    await node("get_alert", {"identifier": "alias/with?query#fragment", "identifier_type": "alias"}, {**AUTH, "region": "eu"}).execute({})
    assert requests[0].url.host == "api.eu.opsgenie.com"
    assert "/alias%2Fwith%3Fquery%23fragment" in str(requests[0].url)
    assert dict(requests[0].url.params) == {"identifierType": "alias"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
async def test_errors_preserve_provider_message_and_redact_key(monkeypatch, code):
    transport(monkeypatch, code, {"message": "Rejected " + TOKEN})
    result = await node("list_alerts").execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "http_status": code}


@pytest.mark.asyncio
async def test_processing_failure_is_not_success(monkeypatch):
    transport(monkeypatch, 200, {"data": {"isSuccess": False, "status": "Alert does not exist"}})
    result = await node("get_request_status", {"request_id": "request-id"}).execute({})
    assert result["status"] == "error" and result["error"] == "Alert does not exist"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(202, {"result": "Accepted"}), (200, {}), (200, []), (200, {"message": "error"})])
async def test_malformed_success_does_not_pass(monkeypatch, code, body):
    transport(monkeypatch, code, body)
    with pytest.raises(ValueError): await node("list_alerts").execute({})


@pytest.mark.parametrize("operation,config", [("create_alert", {}), ("add_note", ALERT), ("add_tags", {**ALERT, "tags": []}), ("update_alert_priority", {**ALERT, "priority": "P0"}), ("create_heartbeat", {"name": "worker", "interval": 0, "interval_unit": "minutes"}), ("list_alerts", {"limit": 101}), ("get_alert", {**ALERT, "url": "https://evil.test"})])
def test_required_and_unknown_fields_fail_before_transport(operation, config):
    with pytest.raises(ValueError): node(operation, config)


def test_manual_credential_has_default_type_and_only_human_inputs():
    credential = native.OpsGenieApiKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "opsgenie_api_key" and credential.region == "us"
    with pytest.raises(ValidationError): native.OpsGenieApiKeyCredential(api_key="GenieKey token")
    assert native.OpsGenieNode.connection_evidence.operation == "list_alerts"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config", [("get_alert", ALERT), ("list_teams", {})])
async def test_documented_responses_without_spec_only_metadata(monkeypatch, operation, config):
    # Published examples omit took (get alert) and expandable (list teams).
    # Those metadata fields are not necessary to return the actual account data.
    fixture = json.loads((Path(__file__).parent / "fixtures" / "opsgenie" / (operation + ".json")).read_text())
    transport(monkeypatch, 200, fixture["body"])
    result = await node(operation, config).execute({})
    assert result["status"] == "success" and result["data"] == fixture["body"]["data"]
