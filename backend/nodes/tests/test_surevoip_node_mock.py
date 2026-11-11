"""Native operation execution against fixture HTTP; no live account or calls."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import surevoip_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "surevoip_basic", "username": "fixture-account", "password": "fixture-password"}
USER = "00000000-0000-4000-8000-000000000001"
CALL = json.loads((Path(__file__).parent / "fixtures/surevoip/create_call.json").read_text())["config"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        status, body, *headers = replies.pop(0)
        return httpx.Response(status, **({"content": body} if isinstance(body, bytes) else {"json": body}),
            headers=headers[0] if headers else {})
    client = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-surevoip", operation=operation,
        arguments=arguments or {}, credential_data=dict(auth), user_id=USER)


# Expected routes and statuses are transcribed from the provider's pinned path files.
CASES = [
    ("create_call", {k: v for k, v in CALL.items() if k != "operation"}, "POST", "/calls", 202),
    ("list_sms", {}, "GET", "/sms", 200),
    ("list_customers", {}, "GET", "/customers", 302),
    ("get_customer", {"account": 123456}, "GET", "/customers/123456", 200),
    ("list_contacts", {}, "GET", "/contacts", 200),
    ("list_billing", {}, "GET", "/billing", 200),
    ("list_charges", {}, "GET", "/charges", 200),
    ("list_topups", {}, "GET", "/topups", 200),
    ("list_sip_accounts", {}, "GET", "/sip", 200),
    ("list_numbers", {}, "GET", "/numbers", 200),
    ("list_areacodes", {}, "GET", "/areacodes", 200),
    ("list_customer_announcements", {"account": 123456}, "GET", "/customers/123456/announcements", 200),
    ("get_announcement", {"account": 123456, "announcement_id": "hgCRVfWB4hGRSEAkICyA"}, "GET", "/customers/123456/announcements/hgCRVfWB4hGRSEAkICyA", 200),
    ("list_announcements", {}, "GET", "/announcements", 200),
    ("list_hosted_domains", {}, "GET", "/hosted", 200),
    ("list_mobile_accounts", {}, "GET", "/mobile", 200),
    ("list_partners", {}, "GET", "/partners", 200),
    ("list_ported_numbers", {}, "GET", "/porting", 200),
    ("get_service_status", {}, "GET", "/service-status", 200),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,status", CASES)
async def test_native_routes_auth_and_raw_response(transport, operation, arguments, method, path, status):
    requests, queue = transport
    payload = {"location": "/customers/123456"} if status == 302 else {"status": "OK"}
    queue.append((status, payload))
    result = await run(operation, arguments)
    assert result["data"] == payload and result["http_status"] == status
    assert len(requests) == 1 and not queue
    request = requests[0]
    assert request.method == method and request.url == "https://api.surevoip.co.uk" + path
    expected = base64.b64encode(b"fixture-account:fixture-password").decode()
    assert request.headers["Authorization"] == "Basic " + expected
    assert request.headers["Accept"] == "application/json"
    assert not request.url.query and not request.url.userinfo
    if method == "GET":
        assert request.content == b""


@pytest.mark.asyncio
async def test_call_example_body_and_acceptance(transport):
    requests, queue = transport
    queue.append((202, {"Call": "queued", "Location": "/calls/fixture"}))
    result = await run("create_call", {k: v for k, v in CALL.items() if k != "operation"})
    body = json.loads(requests[0].content)
    assert body == {
        "from": "442035159999", "to": "442035159995", "caller_id": "01224900123",
        "announcement_at": "180", "announcement_id": "hgCRVfWB4hGRSEAkICyA",
        "hangup_at": "300", "hangup_announcement_id": "RVfWB4hGRSEAkIXYCyA",
        "options": {"a_leg_only": 1, "a_leg_caller_id": "01224900123", "connect_key": 1,
            "cancel_key": 2, "play_audio": [{"announcement_id": "zgL4QmsB6hGmv5YnsW_4lQ"}]},
    }
    assert requests[0].headers["Content-Type"] == "application/json"
    assert result["http_status"] == 202  # Accepted is not proof that either party answered.


@pytest.mark.asyncio
async def test_call_omits_unset_fields(transport):
    requests, queue = transport
    queue.append((202, {}))
    await run("create_call", {k: CALL[k] for k in ("from_number", "to_number", "caller_id")})
    assert set(json.loads(requests[0].content)) == {"from", "to", "caller_id"}


@pytest.mark.asyncio
async def test_account_redirect_is_returned_without_following(transport):
    requests, queue = transport
    queue.append((302, {"location": "/customers/123456"}, {"Location": "https://other.example/customers/123456"}))
    result = await run("list_customers")
    assert result["data"]["location"] == "/customers/123456"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_manual_connection_evidence_names_customer(transport):
    requests, queue = transport
    queue.append((302, {"location": "/customers/123456"}))
    evidence = await collect_evidence(node_type="automation-surevoip", credential_data=AUTH, user_id=USER)
    assert evidence.reachable is True and evidence.account_label == "/customers/123456"
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_fail_without_retrying(transport, status):
    requests, queue = transport
    queue.append((status, {"message": "Request rejected"}))
    with pytest.raises(ValueError, match=f"SureVoIP HTTP {status}"):
        await run("create_call", {k: CALL[k] for k in ("from_number", "to_number", "caller_id")})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_sparse_spec_allows_empty_read_response(transport):
    _, queue = transport
    queue.append((200, b""))
    assert (await run("list_sms"))["data"] is None


@pytest.mark.asyncio
async def test_documented_nested_announcement_response_is_preserved(transport):
    _, queue = transport
    # Schema-shaped synthetic values; these are not claimed as a captured provider response.
    payload = {"list": [{"announcement": {"id": "audio", "description": "Greeting", "size": 42,
        "creation_date": "2026-01-01", "url": {"href": "/audio", "title": "Greeting", "download": "/download"}}}]}
    queue.append((200, payload))
    assert (await run("list_customer_announcements", {"account": 123456}))["data"] == payload


@pytest.mark.parametrize("updates", [
    {"announcement_at": "180"}, {"announcement_id": "audio"}, {"hangup_announcement_id": "audio"},
    {"from_number": "https://example.com"}, {"caller_id": "123\n"},
])
def test_call_validation_refuses_incomplete_or_invalid_values(updates):
    arguments = {k: CALL[k] for k in ("from_number", "to_number", "caller_id")}
    with pytest.raises(ValidationError):
        native.CreateCall(**{**arguments, **updates})


@pytest.mark.parametrize("identifier", ["..", ".", "../customers", "x?admin=true", "x#fragment"])
def test_announcement_path_cannot_escape_resource(identifier):
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS["get_announcement"](account=123456, announcement_id=identifier)


def test_credential_can_be_entered_without_type_tag():
    credential = native.SureVoIPCredential(username="fixture-account", password="fixture-password")
    assert credential.credential_type == "surevoip_basic"
    assert "fixture-password" not in repr(credential)


@pytest.mark.parametrize("field,value", [("username", "u:p"), ("username", "u\n"), ("password", "p\n")])
def test_basic_credentials_reject_control_or_separator_characters(field, value):
    with pytest.raises(ValidationError):
        native.SureVoIPCredential(**{**AUTH, field: value})


def test_saved_canvas_metadata_does_not_block_runtime_config():
    parsed = native.SureVoIPNode.parse_config({
        "config": {"operation": "get_customer", "account": 123456,
            "credentialIds": {"surevoip_basic": "00000000-0000-4000-8000-000000000002"},
            "goal": "Read account", "account__label": "Customer"}, "credentials": AUTH})
    assert parsed.config.account == 123456
    assert parsed.config.model_dump() == {"operation": "get_customer", "account": 123456}
