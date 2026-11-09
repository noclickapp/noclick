"""Exact wire regressions for every Chili Piper operation; no live credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import chili_piper_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-chili-piper-secret-42"
CASES = json.loads((Path(__file__).parent / "fixtures/chili_piper/requests.json").read_text())["operations"]


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="fixture", node_type="automation-chili-piper",
        node_data={"config": config, "credentials": credential or {"credential_type": native.CREDENTIAL_TYPE, "api_key": TOKEN}},
    )


def transport(monkeypatch, body=None, status=200, responder=None):
    requests = []

    def respond(request):
        requests.append(request)
        if responder:
            return responder(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_every_operation_exact_method_route_parameters_body_and_response(monkeypatch, case):
    requests = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "fire.chilipiper.com"
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_account_evidence_uses_workspace_names_and_exact_page_metadata(monkeypatch):
    body = {"results": [{"id": "ws-1", "name": "Sales", "metadata": {}}], "total": 11, "page": 0, "pageSize": 10}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_workspaces", "name": "Sales + Growth"}).execute({})
    assert result["items"][0]["name"] == "Sales"
    assert result["has_more"] is True and result["next_page"] == 1
    assert requests[0].url.params["name"] == "Sales + Growth"
    body.update(page=1, total=11)
    result = await node({"operation": "list_workspaces", "page": 1}).execute({})
    assert result["has_more"] is False and result["next_page"] is None
    assert native.ChiliPiperNode.connection_evidence.operation == "list_workspaces"


@pytest.mark.asyncio
async def test_meetings_pagination_preserves_provider_data(monkeypatch):
    case = next(case for case in CASES if case["config"]["operation"] == "list_meetings")
    body = {"data": [{"meetingId": "fixture-meeting"}], "hasMore": "Yes", "hasMoreItems": True}
    transport(monkeypatch, body)
    result = await node(case["config"]).execute({})
    assert result["has_more"] is True and result["next_page"] == 1
    assert result["items"] == body["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 409, 429, 500])
async def test_errors_do_not_retry_follow_redirects_or_leak_credentials(monkeypatch, status):
    requests = transport(monkeypatch, {"errorCode": "Denied", "errorMessage": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_webhooks"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["message"] == "Rejected [redacted]"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unavailable_slot_is_a_failure_even_with_http_200(monkeypatch):
    case = next(case for case in CASES if case["config"]["operation"] == "create_meeting")
    requests = transport(monkeypatch, {"type": "Failure", "reason": "Slot unavailable"})
    result = await node(case["config"]).execute({})
    assert result["status"] == "error" and result["message"] == "Slot unavailable"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_interrupted_booking_is_unverified_and_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("secret transport details " + TOKEN, request=request)
    case = next(case for case in CASES if case["config"]["operation"] == "create_meeting")
    requests = transport(monkeypatch, responder=timeout)
    result = await node(case["config"]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unverified"
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"results": [], "total": 0, "page": 99, "pageSize": 10}])
async def test_malformed_pagination_does_not_claim_a_successful_read(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="pagination"):
        await node({"operation": "list_workspaces"}).execute({})


def test_schema_has_twenty_operations_and_manually_connectable_credential():
    schema = native.ChiliPiperNode.get_config_schema()
    assert len(CASES) == len(native.ROUTES) == 20
    cred = schema["$defs"]["ChiliPiperAPIKey"]
    assert cred["properties"]["credential_type"]["default"] == native.CREDENTIAL_TYPE
    assert cred["properties"]["api_key"]["ui:widget"] == "password"
    assert cred["required"] == ["api_key"]
    assert native.ChiliPiperAPIKey(api_key=TOKEN).credential_type == native.CREDENTIAL_TYPE


@pytest.mark.parametrize("config", [
    {"operation": "get_user", "user_id": "../other"},
    {"operation": "get_workspace", "workspace_id": ".."},
    {"operation": "get_meeting", "meeting_id": "not-a-uuid"},
    {"operation": "list_workspaces", "page": True},
    {"operation": "list_workspaces", "page_size": 51},
    {"operation": "list_meetings", "start": "2025-01-08T13:46:18Z", "end": "2025-02-08T13:46:18Z"},
    {"operation": "list_meetings", "start": "2025-01-08T13:46:18", "end": "2025-01-09T13:46:18"},
    {"operation": "create_meeting"},
    {"operation": "update_meeting", "meeting_id": "53b21d0e-d514-46b9-86eb-344653c44e5d"},
    {"operation": "list_webhooks", "url": "https://other.example.com"},
])
def test_invalid_configuration_is_rejected_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ChiliPiperNode.parse_config({"config": config, "credentials": {"api_key": TOKEN}})


@pytest.mark.parametrize("key", ["Bearer secret", "https://example.com/key", "<token>", "a\r\nb", "a b"])
def test_invalid_keys_are_rejected_without_echoing_the_input(key):
    with pytest.raises(ValidationError) as error:
        native.ChiliPiperAPIKey(api_key=key)
    assert "input_value" not in str(error.value)
