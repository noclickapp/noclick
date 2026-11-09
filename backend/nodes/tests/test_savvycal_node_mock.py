"""Native SavvyCal node requests and parsing against unmodified provider examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import savvycal_node as savvycal
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures" / "savvycal"
CONTRACT = json.loads((FIXTURES / "contract_examples.json").read_text())["operations"]
CASES = json.loads((FIXTURES / "cases.json").read_text())
TOKEN = "pt_secret_fixture-synthetic-not-live"
CREDENTIAL = {"credential_type": "savvycal_token", "access_token": TOKEN}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.savvycal.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply[0], json=reply[1]) if len(reply) == 2 else httpx.Response(reply[0], content=reply[1], headers=reply[2])

    native = ssrf.guarded_async_client
    monkeypatch.setattr(savvycal, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-savvycal", operation=operation,
        arguments=config or {}, credential_data=CREDENTIAL.copy(), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_documented_operations_through_native_runner(transport, case):
    requests, replies = transport
    contract = CONTRACT[case["contract_operation"]]
    replies.append((contract["status"], contract["response"]))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success", result
    assert result["data"] == contract["response"]
    assert result["http_status"] == contract["status"]
    assert len(requests) == 1  # Writes are never retried and pages are never silently truncated.
    request = requests[0]
    path = contract["path"]
    for name, value in case["config"].items():
        path = path.replace("{" + name + "}", str(value))
    assert request.method == contract["method"]
    assert request.url.path == path
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["operation"] == "get_time_zone":
        assert b"America/Chicago" in request.url.raw_path
        assert b"%2F" not in request.url.raw_path


@pytest.mark.asyncio
async def test_link_update_preserves_explicit_clears_and_omits_other_fields(transport):
    requests, replies = transport
    replies.append((200, CONTRACT["getSchedulingLink"]["response"]))
    result = await run("update_link", {"link_id": "link_123", "description": None})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"description": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_rejections_are_not_success_and_never_retried(transport, status):
    requests, replies = transport
    replies.append((status, {"message": "Provider rejected " + TOKEN}))
    result = await run("cancel_event", {"event_id": "event_123"})
    assert result["status"] == "error"
    assert result["http_status"] == status
    assert "Provider rejected" in result["error"]
    assert TOKEN not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    (200, b"<html>Sign in</html>", {"Content-Type": "text/html"}),
    (200, b"not json", {"Content-Type": "application/json"}),
    (200, {"error": "Unauthorized"}),
    (200, {"entries": [], "metadata": "bad"}),
])
async def test_unexpected_responses_fail_closed(transport, reply):
    requests, replies = transport
    replies.append(reply)
    with pytest.raises(ValueError):
        await run("list_links")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_transport_failure_does_not_repeat_a_write(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout("not a completed write"))
    with pytest.raises(ValueError, match="Inspect the provider"):
        await run("create_personal_link", {"name": "My New Link"})
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_event", "event_id": "../me"},
    {"operation": "get_link", "link_id": "x?query=y"},
    {"operation": "get_time_zone", "time_zone": "../me"},
    {"operation": "list_events", "period": "fixed"},
    {"operation": "list_links", "limit": 101},
    {"operation": "list_links", "after": "a", "before": "b"},
    {"operation": "get_available_slots", "link_id": "link_123", "from_time": "2024-01-20T00:00:00Z", "until": "2024-03-20T00:00:00Z"},
    {"operation": "update_link", "link_id": "link_123"},
    {"operation": "create_webhook", "url": "https://user:password@example.com/hook"},
    {"operation": "create_webhook", "url": "http://example.com/hook"},
    {"operation": "create_event", "link_id": "link_123", "display_name": "Jane Smith", "email": "jane@example.com", "start_at": "2024-01-20T14:00:00Z", "end_at": "2024-01-20T13:00:00Z", "time_zone": "America/New_York"},
])
def test_invalid_config_is_rejected_before_http(config):
    result = savvycal.SavvyCalNode.validate_config({"config": config, "credentials": CREDENTIAL})
    assert not result["valid"]


@pytest.mark.parametrize("token", ["", "https://example.com/token", "Bearer abc", "abc\nheader"])
def test_manual_credential_rejects_urls_headers_and_blanks(token):
    with pytest.raises(ValueError):
        savvycal.SavvyCalTokenCredential(access_token=token)


def test_manual_credential_defaults_and_trims_private_key():
    credential = savvycal.SavvyCalTokenCredential(access_token="  " + TOKEN + "  ")
    assert credential.credential_type == "savvycal_token"
    assert credential.access_token == TOKEN


@pytest.mark.asyncio
async def test_connection_evidence_shows_links_or_account_identity(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((200, CONTRACT["listSchedulingLinks"]["response"]))
    evidence = await collect_evidence(node_type="automation-savvycal", user_id=USER, credential_data=CREDENTIAL.copy())
    assert evidence.reachable is True
    assert evidence.samples
    replies.extend([(200, {"entries": [], "metadata": {"after": None, "before": None}}), (200, CONTRACT["getCurrentUser"]["response"])])
    evidence = await collect_evidence(node_type="automation-savvycal", user_id=USER, credential_data=CREDENTIAL.copy())
    assert evidence.reachable is True
    assert evidence.account_label == "John Doe"


@pytest.mark.asyncio
async def test_connection_rejection_preserves_provider_reason(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((401, {"message": "No access for this request"}))
    evidence = await collect_evidence(node_type="automation-savvycal", user_id=USER, credential_data=CREDENTIAL.copy())
    assert evidence.reachable is False
    assert "No access for this request" in evidence.error
    assert "401" in evidence.error


@pytest.mark.asyncio
async def test_connection_timeout_is_unverified(transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append(httpx.ReadTimeout("timeout"))
    evidence = await collect_evidence(node_type="automation-savvycal", user_id=USER, credential_data=CREDENTIAL.copy())
    assert evidence.reachable is None
