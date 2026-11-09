"""Exercise Tinyfish through the real factory; HTTP only is replaced.

Request fixtures follow Tinyfish v1 OpenAPI and its authentication, dataset,
monitor, research, search and fetch reference examples. No live key is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import tinyfish_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / "fixtures/tinyfish/requests.json").read_text())
TOKEN = "tinyfish-synthetic-key-42"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="tinyfish-fixture", node_type="automation-tinyfish",
        node_data={"config": config, "credentials": {"api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_tinyfish_single_contract_request(monkeypatch, case):
    response = {"items": [{"id": "owned", "goal": "Extract page title"}], "next_cursor": "next-page"}
    requests = transport(monkeypatch, response)
    output = await node(case["config"]).execute({})
    assert output == {"status": "success", "http_status": 200, "data": response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert str(request.url.copy_with(query=None)) == case["url"]
    assert request.headers["X-API-Key"] == TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"] == "search":
        assert dict(request.url.params) == {"query": "web automation tools"}


@pytest.mark.asyncio
async def test_tinyfish_filters_and_cursor_are_forwarded_without_fetching_another_page(monkeypatch):
    page = {"data": [{"id": "owned", "goal": "Find pricing"}], "pagination": {"next_cursor": "next+cursor=", "has_more": True}}
    requests = transport(monkeypatch, page)
    result = await node({"operation": "list_runs", "status": "COMPLETED", "cursor": "prior+cursor=", "limit": 10, "owner": "team"}).execute({})
    assert dict(requests[0].url.params) == {"status": "COMPLETED", "cursor": "prior+cursor=", "limit": "10", "owner": "team"}
    assert result["data"] == page and len(requests) == 1


@pytest.mark.asyncio
async def test_tinyfish_query_options_are_not_discarded(monkeypatch):
    requests = transport(monkeypatch, {"items": [], "next_cursor": None})
    await node({"operation": "get_dataset_rows", "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "after": "prior", "limit": 500}).execute({})
    assert dict(requests[0].url.params) == {"after": "prior", "limit": "500"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_tinyfish_provider_rejection_is_an_error_without_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"code": "INVALID_API_KEY", "message": "Rejected " + TOKEN}}, status)
    result = await node({"operation": "list_runs"}).execute({})
    assert result == {"status": "error", "http_status": status, "status_code": status, "message": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_tinyfish_error_envelope_on_200_is_not_success(monkeypatch):
    transport(monkeypatch, {"error": {"message": "The provided API key is invalid"}})
    result = await node({"operation": "list_runs"}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_tinyfish_204_delete_keeps_empty_acknowledgment(monkeypatch):
    transport(monkeypatch, None, 204)
    result = await node({"operation": "delete_profile", "profile_id": "prof_abc123def4567890"}).execute({})
    assert result == {"status": "success", "http_status": 204, "data": None}


@pytest.mark.parametrize("config", [
    {"operation": "get_run", "id": "../other"},
    {"operation": "get_run", "id": ""},
    {"operation": "run", "url": "file:///etc/passwd", "goal": "Read"},
    {"operation": "run", "url": "https://example.com", "goal": "Read", "webhook_url": "http://example.com"},
    {"operation": "create_dataset", "prompt": "a"},
    {"operation": "get_dataset", "id": "not-a-uuid"},
    {"operation": "fetch_urls", "urls": []},
    {"operation": "get_run", "id": "owned", "screenshots": "base64"},
    {"operation": "update_monitor", "id": "owned", "status": "paused", "name": "Mixed update"},
    {"operation": "update_monitor", "id": "owned"},
    {"operation": "update_profile", "profile_id": "owned"},
])
def test_tinyfish_invalid_input_rejected_before_request(config):
    with pytest.raises((ValidationError, ValueError)):
        native.TinyfishFullConfig.model_validate({"config": config, "credentials": {"api_key": TOKEN}})


def test_tinyfish_manual_key_defaults_type_and_shapes_paste():
    credential = native.TinyfishAPIKeyCredential.model_validate({"api_key": "  " + TOKEN + "\n"})
    assert credential.credential_type == "tinyfish_api_key" and credential.api_key == TOKEN
    for key in ("https://example.com/api-keys", "<token>", "bad\r\nheader"):
        with pytest.raises(ValidationError):
            native.TinyfishAPIKeyCredential(api_key=key)


def test_tinyfish_evidence_is_an_account_read_requiring_only_a_key():
    evidence = native.TinyfishNode.connection_evidence
    assert evidence.operation == "list_runs" and evidence.proves == "account"
    assert native.TinyfishListRunsConfig().operation == "list_runs"


@pytest.mark.asyncio
async def test_tinyfish_documented_research_acceptance(monkeypatch):
    body = json.loads((Path(__file__).parent / "fixtures/tinyfish/research-accepted.json").read_text())
    transport(monkeypatch, body)
    result = await node({"operation": "start_research", "query": "Compare long-duration energy storage approaches"}).execute({})
    assert result["status"] == "success" and result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("operation, identifier", [("get_run", "id"), ("get_research", "research_run_id")])
async def test_tinyfish_failed_task_is_still_a_successful_record_read(monkeypatch, operation, identifier):
    body = {"status": "FAILED", "error": {"code": "SYSTEM_FAILURE", "message": "Browser crashed during execution"}}
    transport(monkeypatch, body)
    result = await node({"operation": operation, identifier: "owned-run"}).execute({})
    assert result["status"] == "success" and result["data"] == body


def test_tinyfish_canvas_attachment_metadata_is_not_an_api_field():
    config = native.TinyfishFullConfig.model_validate({"config": {
        "operation": "list_runs", "credentialIds": {"tinyfish_api_key": "saved-id"}}})
    assert config.config.model_dump(exclude_none=True) == {"operation": "list_runs"}


@pytest.mark.asyncio
async def test_tinyfish_connect_evidence_shows_owned_goals(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"data": [{"run_id": "owned-run", "goal": "Find all pricing information"}],
        "pagination": {"has_more": False, "next_cursor": None}})
    result = await collect_evidence(node_type="automation-tinyfish", user_id="tinyfish-test",
        credential_data={"api_key": TOKEN})
    assert result.reachable is True
    assert result.samples[0].label == "Find all pricing information"


@pytest.mark.asyncio
async def test_tinyfish_connect_evidence_definitively_rejects_401(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"error": {"message": "Key is no longer active"}}, 401)
    result = await collect_evidence(node_type="automation-tinyfish", user_id="tinyfish-test",
        credential_data={"api_key": TOKEN})
    assert result.reachable is False
    assert "Key is no longer active" in result.error
