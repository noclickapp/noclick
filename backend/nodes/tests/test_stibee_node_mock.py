"""Contract fixtures exercise the real factory with intercepted HTTP only.

Cases preserve Stibee v2 request spellings, published response examples and
schema-derived responses where no complete example is published.
The conformance harness independently validates wire traffic against the pin.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import stibee_node as stibee
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads(
    (Path(__file__).parent / "fixtures/stibee/contract_cases.json").read_text()
)
TOKEN = "stibee-fixture-api-key"
AUTH = {"credential_type": "stibee_api_key", "api_key": TOKEN}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.stibee.com"
        assert request.headers["AccessToken"] == TOKEN
        assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
        return responses.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        stibee,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, responses


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-stibee",
        operation=operation,
        arguments=arguments or {},
        credential_data=auth,
        user_id="00000000-0000-4000-8000-000000000001",
    )


def response(case):
    if case["content_type"] == "application/json":
        return httpx.Response(200, json=case["response"])
    return httpx.Response(
        200, text=case["response"], headers={"Content-Type": case["content_type"]}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_stibee_published_wire_contract(case, transport):
    requests, responses = transport
    responses.append(response(case))
    result = await run(case["operation"], case["arguments"])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.raw_path.split(b"?", 1)[0].decode() == case["path"]
    assert dict(request.url.params) == case["query"]
    if isinstance(case["body"], dict):
        assert json.loads(request.content) == case["body"]
    elif isinstance(case["body"], str):
        assert request.content.decode() == case["body"]
        assert request.headers["Content-Type"] == "text/html; charset=utf-8"
    else:
        assert not request.content
    assert result["http_status"] == 200
    assert result["status"] == (
        "accepted" if case["operation"] == "send_email" else "success"
    )
    if case["operation"] == "send_email":
        assert result["delivery_verified"] is False
    if case["content_type"] == "application/json":
        assert result["data"] == (
            case["response"]["items"]
            if "items" in case["response"]
            else case["response"]
        )
    elif case["operation"] == "get_email_content":
        assert result["html"] == case["response"]
    else:
        assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_stibee_empty_lists_and_explicit_page_boundary(transport):
    requests, responses = transport
    responses.extend(
        [
            httpx.Response(
                200, json=None, headers={"Content-Type": "application/json"}
            ),
            httpx.Response(200, json=[{"id": 1, "name": "One"}]),
            httpx.Response(
                200,
                json={
                    "items": [{"id": 2, "subject": "Next"}],
                    "total": 3,
                    "offset": 1,
                    "limit": 1,
                },
            ),
        ]
    )
    # httpx's json=None creates an empty body: use the actual documented JSON null.
    responses[0] = httpx.Response(
        200, content=b"null", headers={"Content-Type": "application/json"}
    )
    assert (await run("list_lists"))["data"] == []
    first = await run("list_groups", {"list_id": 1234, "offset": 7, "limit": 1})
    assert first["next_offset"] == 8
    page = await run("list_emails", {"offset": 1, "limit": 1})
    assert page["next_offset"] == 2 and page["total"] == 3
    assert len(requests) == 3  # never silently follow pagination or retry writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,mime,body",
    [
        (
            401,
            "application/json",
            '{"code":"Errors.Authorization.NoToken","message":"존재하지 않는 토큰 입니다."}',
        ),
        (
            429,
            "application/json",
            '{"code":"Errors.Authorization.TooManyRequest","message":"rate limited"}',
        ),
        (
            200,
            "application/json",
            '{"code":"Errors.Authorization.NoToken","message":"bad key"}',
        ),
        (302, "text/html", '<a href="https://other.example">redirect</a>'),
        (200, "text/html", "<html>unexpected</html>"),
        (200, "application/json", '{"items":false}'),
        (200, "application/json", "not-json"),
    ],
)
async def test_stibee_refuses_provider_errors_and_invalid_reads(
    status, mime, body, transport
):
    requests, responses = transport
    responses.append(httpx.Response(status, text=body, headers={"Content-Type": mime}))
    with pytest.raises(ValueError):
        await run("list_emails")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_stibee_error_keeps_provider_message_but_redacts_key(transport):
    _, responses = transport
    responses.append(
        httpx.Response(
            400,
            json={
                "code": "Errors.Authorization.NoToken",
                "message": "rejected " + TOKEN,
            },
        )
    )
    with pytest.raises(ValueError, match="rejected ") as exc:
        await run("list_emails")
    assert TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_stibee_writes_require_ok_and_do_not_retry(transport):
    requests, responses = transport
    responses.append(
        httpx.Response(200, text="not ok", headers={"Content-Type": "text/plain"})
    )
    with pytest.raises(ValueError, match="acknowledgement"):
        await run("send_email", {"email_id": 123456})
    assert len(requests) == 1


@pytest.mark.parametrize(
    "data",
    [
        {"operation": "get_list", "list_id": -1},
        {"operation": "list_emails", "limit": 101},
        {"operation": "update_email", "email_id": 1},
        {
            "operation": "update_subscriber",
            "list_id": 1,
            "subscriber": "../escape",
            "fields": {"name": "x"},
        },
        {
            "operation": "delete_subscribers",
            "list_id": 1,
            "subscribers": ["x@example.com"] * 101,
        },
        {"operation": "get_email_stats", "ids": ",".join(str(i) for i in range(1, 12))},
        {
            "operation": "add_subscriber",
            "list_id": 1,
            "subscriber": {"email": "x@example.com", "status": "ready"},
        },
    ],
)
def test_stibee_rejects_invalid_configs(data):
    with pytest.raises((ValidationError, ValueError)):
        stibee.StibeeNode.parse_config({"config": data, "credentials": AUTH})


def test_stibee_manual_credential_and_family():
    assert stibee.StibeeAPIKeyCredential(api_key=" " + TOKEN + " ").model_dump() == AUTH
    for secret in ("https://example.com", "<token>", "one\ntwo"):
        with pytest.raises(ValueError):
            stibee.StibeeAPIKeyCredential(api_key=secret)
    with pytest.raises(ValueError, match="Stibee"):
        stibee.StibeeNode.parse_config(
            {
                "config": {"operation": "list_emails"},
                "credentials": {**AUTH, "credential_type": "foreign_key"},
            }
        )
    assert stibee.StibeeNode.connection_evidence.operation == "list_emails"
