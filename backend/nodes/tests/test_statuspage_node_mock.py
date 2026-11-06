"""Every operation against unmodified provider responses and real HTTP serialization.

Response samples: https://developer.statuspage.io/ . Each JSON fixture records
its exact #operation source URL. Tests never contact the live provider.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.statuspage_node import (
    StatuspageNode, StatuspageNodeConfig, CreateIncidentConfig,
    CreateSubscriberConfig, UpdateSubscriberConfig,
)
from nodes.core.connection_evidence import collect_evidence

FIXTURES = Path(__file__).parent / "fixtures/statuspage"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
CASES = json.loads((FIXTURES / "operations.json").read_text())
TOKEN = "statuspage-test-api-key"


def node(operation, config=None, credentials=True):
    return StatuspageNode(
        node_id="statuspage-test", node_type="automation-statuspage", node_data={},
        config=StatuspageNodeConfig.model_validate({
            "config": {**(config if config is not None else CASES[operation]["config"]), "operation": operation},
            "credentials": {"api_key": TOKEN} if credentials else None,
        }), sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )


def client_patch(handler):
    original = httpx.AsyncClient
    return patch("nodes.statuspage_node.httpx.AsyncClient", side_effect=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_documented_operation(operation):
    case = CASES[operation]
    fixture = RESPONSES[case["method"] + " " + case["spec_path"]]
    requests = []
    def respond(request):
        requests.append(request)
        assert request.method == case["method"]
        assert request.url.scheme == "https"
        assert request.url.host == "api.statuspage.io"
        assert request.url.path == "/v1" + case["path"]
        assert dict(request.url.params) == case["params"]
        assert request.headers["Authorization"] == "OAuth " + TOKEN
        assert request.headers["Accept"] == "application/json"
        if case["body"] is None:
            assert request.content == b""
        else:
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == case["body"]
        return httpx.Response(204) if fixture["status"] == 204 else httpx.Response(fixture["status"], json=fixture["body"])
    with client_patch(respond):
        result = await node(operation).execute({})
    assert len(requests) == 1
    assert result["status"] == "success", result
    assert result["status_code"] == fixture["status"]
    expected = {"deleted": True} if fixture["status"] == 204 else fixture["body"]
    if operation.startswith("list_"):
        collection = "pages" if operation == "list_pages" else "components" if operation == "list_components" else "subscribers" if operation == "list_subscribers" else "maintenances" if "maintenance" in operation else "incidents"
        expected = {collection: expected, "count": len(expected)}
    assert result["data"] == expected
    assert result["operation"] == operation
    assert result["timing_ms"]["total"] >= 0
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [400, 401, 403, 404, 420, 422, 429, 500])
async def test_provider_rejection_preserves_message_and_no_retry(code):
    calls = []
    # Documented ApiV1_ErrorEntity: https://developer.statuspage.io/#operation/getPages
    body = {"error": "Could not authenticate"}
    def respond(request):
        calls.append(request)
        return httpx.Response(code, json=body, headers={"Retry-After": "60"})
    with client_patch(respond):
        result = await node("list_pages").execute({})
    assert result["status"] == "error"
    assert json.loads(result["error"]) == body
    assert result["status_code"] == code
    assert result["retry_after"] == "60"
    assert len(calls) == 1
    assert "timing_ms" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"error": "Could not authenticate"}, {"success": False}, [{"id": "p"}], [{"id": "", "name": "Page"}], [{"id": "p", "name": ""}], ["Page"], None])
async def test_connection_probe_rejects_invalid_success_bodies(body):
    with client_patch(lambda request: httpx.Response(200, json=body)):
        result = await node("list_pages").execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_connection_evidence_shows_account_pages():
    body = RESPONSES["GET /pages"]["body"]
    with client_patch(lambda request: httpx.Response(200, json=body)):
        evidence = await collect_evidence(node_type="automation-statuspage", credential_data={"api_key": TOKEN}, user_id="test")
    assert evidence.reachable is True
    assert evidence.samples[0].label == body[0]["name"]


@pytest.mark.asyncio
async def test_connection_evidence_rejection():
    with client_patch(lambda request: httpx.Response(401, json={"error": "Could not authenticate"})):
        evidence = await collect_evidence(node_type="automation-statuspage", credential_data={"api_key": TOKEN}, user_id="test")
    assert evidence.reachable is False
    assert "Could not authenticate" in evidence.error


@pytest.mark.asyncio
async def test_empty_account_and_invalid_json():
    with client_patch(lambda request: httpx.Response(200, json=[])):
        result = await node("list_pages").execute({})
    assert result["status"] == "success"
    assert result["data"] == {"pages": [], "count": 0}
    with client_patch(lambda request: httpx.Response(200, text="<html>Login</html>")):
        result = await node("list_pages").execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_timeout():
    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)
    with client_patch(timeout):
        result = await node("list_pages").execute({})
    assert result["status"] == "error"
    assert "timing_ms" in result


@pytest.mark.asyncio
async def test_missing_credentials():
    with pytest.raises(ValueError, match="API key"):
        await node("list_pages", credentials=False).execute({})


@pytest.mark.asyncio
async def test_subscriber_update_omission_means_all_components():
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=RESPONSES["PATCH /pages/{page_id}/subscribers/{subscriber_id}"]["body"])
    with client_patch(respond):
        result = await node("update_subscriber", {"page_id": "p", "subscriber_id": "s"}).execute({})
    assert result["status"] == "success"
    assert seen == [{}]


@pytest.mark.parametrize("field,value", [("component_ids", "[]"), ("component_ids", '[1]'), ("component_ids", '{}'), ("components", '[]'), ("components", '{"id":"broken"}'), ("scheduled_for", "2026-01-01")])
def test_invalid_incident_fields(field, value):
    with pytest.raises(ValidationError):
        CreateIncidentConfig(page_id="p", name="Incident", **{field:value})


def test_maintenance_requires_a_valid_window():
    with pytest.raises(ValidationError, match="both"):
        CreateIncidentConfig(page_id="p", name="Maintenance", status="scheduled")
    with pytest.raises(ValidationError, match="follow"):
        CreateIncidentConfig(page_id="p", name="Maintenance", status="scheduled", scheduled_for="2026-01-02T00:00:00Z", scheduled_until="2026-01-01T00:00:00Z")


@pytest.mark.parametrize("config", [{}, {"endpoint":"https://example.com"}, {"phone_number":"202-555-0105"}, {"phone_country":"US"}])
def test_subscriber_requires_contact(config):
    with pytest.raises(ValidationError):
        CreateSubscriberConfig(page_id="p", **config)


def test_sms_and_webhook_subscriber_fields():
    assert CreateSubscriberConfig(page_id="p", phone_country="US", phone_number="202-555-0105").phone_country == "US"
    assert CreateSubscriberConfig(page_id="p", email="foo@example2.com", endpoint="http://example.com/").endpoint == "http://example.com/"


def test_subscriber_component_array_cannot_be_empty():
    with pytest.raises(ValidationError):
        UpdateSubscriberConfig(page_id="p", subscriber_id="s", component_ids="[]")


def test_every_exposed_operation_has_a_documented_fixture():
    schema = StatuspageNodeConfig.model_json_schema()
    members = schema["properties"]["config"]["oneOf"]
    operations = {schema["$defs"][member["$ref"].split('/')[-1]]["properties"]["operation"]["const"] for member in members}
    assert operations == set(CASES)
    assert all(case["source"].startswith("https://developer.statuspage.io/#operation/") for case in CASES.values())
