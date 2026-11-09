"""Exercise GoFundMe Pro through the real node runner and guarded HTTP seam."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import gofundme_pro_node as gfm
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "gofundme_pro_access_token", "access_token": "fixture-gofundme-token", "organization_id": 82364}
CASES = json.loads((Path(__file__).parent / "fixtures/gofundme-pro/wire_cases.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "pro.gofundme.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        code, body = responses.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(gfm, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-gofundme-pro", operation=operation,
        arguments=arguments or {}, credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,expected", CASES)
async def test_gofundme_pro_wire_contract(transport, operation, arguments, method, path, expected):
    requests, responses = transport
    body = {"id": 42, "name": "Annual Appeal"}
    if operation.startswith("list_"):
        body = {"data": [body], "current_page": 1, "last_page": 2,
            "next_page_url": "https://untrusted.example/page-2", "per_page": 20, "total": 21}
    responses.append((200, body))
    out = await run(operation, arguments)
    assert out["status"] == "success"
    assert len(requests) == 1  # Pagination URLs are metadata, never followed.
    request = requests[0]
    assert request.method == method and request.url.path == path
    if method == "GET":
        assert dict(request.url.params) == expected
        assert not request.content
    else:
        assert json.loads(request.content) == expected
    assert out["data"] == (body["data"] if operation.startswith("list_") else body)
    if operation.startswith("list_"):
        assert out["pagination"] == {k: v for k, v in body.items() if k != "data"}


@pytest.mark.asyncio
async def test_gofundme_pro_explicit_pagination_and_false_values(transport):
    transport[1].extend([(200, {"data": []}), (200, {"id": 42})])
    await run("list_supporters", {"page": 2, "per_page": 100, "credentialIds": {"gofundme_pro_access_token": "editor-only"}})
    assert dict(transport[0][0].url.params) == {"page": "2", "per_page": "100"}
    await run("update_transaction", {"transaction_id": 42, "hide_amount": False})
    assert json.loads(transport[0][1].content) == {"hide_amount": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_gofundme_pro_provider_failure_and_redaction(transport, status):
    transport[1].append((status, {"message": "Rejected " + AUTH["access_token"]}))
    out = await run("list_campaigns")
    assert out == {"status": "error", "http_status": status, "message": "Rejected [redacted]"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"message": "not a list"}, {"data": {}}, {"data": [], "errors": ["failed"]}, [], None])
async def test_gofundme_pro_malformed_response(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await run("list_campaigns")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [
    ("get_supporter", {"supporter_id": "../supporters"}),
    ("get_campaign", {"campaign_id": 0}),
    ("list_campaigns", {"page": 0}),
    ("list_supporters", {"per_page": 101}),
    ("create_supporter", {"email_address": "invalid"}),
    ("create_supporter", {}),
    ("update_supporter", {"supporter_id": 42}),
    ("update_designation", {"designation_id": 42}),
    ("update_transaction", {"transaction_id": 42}),
])
async def test_gofundme_pro_invalid_input_never_requests(transport, operation, arguments):
    with pytest.raises(ValueError):
        await run(operation, arguments)
    assert not transport[0]


@pytest.mark.parametrize("value", ["Bearer abc", "abc\nInjected", "https://example.org/key"])
def test_gofundme_pro_invalid_token(value):
    with pytest.raises(ValueError):
        gfm.GoFundMeProAccessTokenCredential(access_token=value, organization_id=82364)


def test_gofundme_pro_manual_credential_default():
    credential = gfm.GoFundMeProAccessTokenCredential(access_token=AUTH["access_token"], organization_id=82364)
    assert credential.credential_type == AUTH["credential_type"]
