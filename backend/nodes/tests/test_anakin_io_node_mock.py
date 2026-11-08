"""Native factory HTTP tests; synthetic examples follow the pinned Anakin 1.1.0 contract."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest

from nodes import anakin_io_node as native
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = "anakin-synthetic-test-token"
AUTH = {"credential_type": "anakin_io_api_key", "api_key": TOKEN}
CASES = json.loads(
    (Path(__file__).parent / "fixtures/anakin-io/operations.json").read_text()
)["operations"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)

    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(
        native,
        "guarded_async_client",
        lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(
        node_type="automation-anakin-io",
        operation=operation,
        arguments=config if config is not None else CASES[operation]["config"],
        credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", CASES, ids=lambda operation: "anakin-io:" + operation
)
async def test_each_operation_is_one_native_authenticated_contract_request(
    transport, operation
):
    requests, replies = transport
    route = native.ROUTES[operation]
    payload = (
        [{"id": "monitor-42", "url": "https://example.com"}]
        if operation == "list_monitors"
        else {"id": "job-42", "status": "completed"}
    )
    replies.append((route["statuses"][0], payload))
    result = await run(operation)
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    expected = CASES[operation]
    assert request.method == expected["method"]
    path = expected["path"]
    for key in route["path_fields"]:
        path = path.replace("{" + key + "}", quote(expected["config"][key], safe=""))
    assert request.url.path == "/v1" + path
    assert request.url.host == "api.anakin.io"
    assert request.headers["X-API-Key"] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    if route["body_fields"]:
        body = json.loads(request.content)
        assert set(body) <= set(route["body_fields"])
        for key, value in expected["config"].items():
            assert body["schema" if key == "output_schema" else key] == value
    else:
        assert not request.content
    for key in route["query_fields"]:
        if key in expected["config"]:
            assert request.url.params[key] == str(expected["config"][key])
    assert result.get("items", result.get("data")) == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_refusal_is_not_connection_success_and_redacts_secrets(
    transport, status
):
    requests, replies = transport
    replies.append((status, {"error": "Denied " + TOKEN}))
    result = await run("list_monitors")
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Denied [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, ["wrong"], None])
async def test_unexpected_evidence_shape_fails(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    assert (await run("list_monitors"))["status"] == "error"


@pytest.mark.asyncio
async def test_empty_account_and_webhook_secret_redaction(transport):
    _, replies = transport
    replies.append((200, []))
    assert (await run("list_monitors"))["items"] == []
    replies.append((200, {"id": "monitor-42", "alertWebhookSecret": "must-not-escape"}))
    assert "must-not-escape" not in str(await run("get_monitor"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 202])
async def test_sync_scrape_keeps_pending_job_for_explicit_poll(transport, status):
    requests, replies = transport
    replies.append((status, {"id": "job-42", "status": "processing"}))
    result = await run("scrape_url_sync")
    assert result["data"]["status"] == "processing" and len(requests) == 1


@pytest.mark.asyncio
async def test_failed_job_is_an_error_even_with_200(transport):
    _, replies = transport
    replies.append(
        (200, {"id": "job-42", "status": "failed", "error": "Extraction failed"})
    )
    assert (await run("get_scrape_result"))["status"] == "error"


@pytest.mark.asyncio
async def test_path_identifier_cannot_inject_route_or_query(transport):
    requests, replies = transport
    replies.append((200, {"id": "a/b?c"}))
    await run("get_monitor", {"id": "a/b?c"})
    assert requests[0].url.raw_path == b"/v1/monitors/a%2Fb%3Fc"


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "search", "prompt": "test", "limit": 21},
        {
            "operation": "create_monitor",
            "url": "https://example.com",
            "intervalMinutes": 14,
        },
        {
            "operation": "create_monitor",
            "url": "https://example.com",
            "intervalMinutes": 30,
            "watchMode": "specific_data",
        },
        {
            "operation": "create_monitor",
            "url": "https://example.com",
            "intervalMinutes": 30,
            "scope": "wire",
        },
        {"operation": "get_monitor", "id": ".."},
        {"operation": "get_monitor", "id": "monitor-42", "unpublished": True},
    ],
)
def test_invalid_inputs_fail_before_any_request(config):
    with pytest.raises(ValueError):
        native.AnakinIoNode.parse_config({"config": config, "credentials": AUTH})


def test_schema_and_evidence_declarations():
    schema = native.AnakinIoNode.get_config_schema()
    credential = schema["$defs"]["AnakinIoCredential"]
    assert credential["title"] == "Anakin Io API Key"
    assert credential["properties"]["api_key"]["ui:widget"] == "password"
    assert native.AnakinIoNode.connection_evidence.operation == "list_monitors"
    assert set(CASES) == set(native.ROUTES) and len(CASES) == 25
