"""Exercise SmartHR through the native operation runner with fixture-only HTTP.

These tests pin routes, payload boundaries and account evidence independently
of the conformance harness, without using a live HR account.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import smarthr_node as module
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import shape_credential
from utils import ssrf

AUTH = {"credential_type": "smarthr_access_token", "subdomain": "fixture", "access_token": "fixture-synthetic-token"}
CASES = json.loads((Path(__file__).parent / "fixtures/smarthr/operations.json").read_text())
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
        assert request.url.host == "fixture.smarthr.jp"
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        assert AUTH["access_token"] not in str(request.url)
        return replies.pop(0)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(module, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-smarthr", operation=operation,
        arguments=arguments or {}, credential_data=AUTH, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_smarthr_contract_routes_and_payloads(transport, case):
    requests, replies = transport
    replies.append(httpx.Response(case["http_status"], content=b"" if case["http_status"] == 204 else json.dumps(case["response"]).encode(), headers={"Content-Type": "application/json"}))
    result = await run(case["operation"], case["arguments"])
    assert result["status"] == "success"
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    if case["method"] in {"POST", "PATCH"}:
        expected = {k: v for k, v in case["arguments"].items() if k not in {"id", "crew_id"}}
        assert json.loads(request.content) == expected
        assert request.headers["Content-Type"] == "application/json"
    elif case["operation"].startswith("list_"):
        assert dict(request.url.params) == {"page": "1", "per_page": "10"}
        assert result["items"] == case["response"] and result["next_page"] is None
    if case["http_status"] == 204:
        assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_smarthr_query_dates_boolean_and_list_filter(transport):
    transport[1].append(httpx.Response(200, json=[]))
    await run("list_employees", {"id": "a,b", "prefer_business_name": False, "entered_at_from": "2026-01-01", "q": "山田", "page": 2, "per_page": 100})
    params = transport[0][0].url.params
    assert params["id"] == "a,b" and params["prefer_business_name"] == "false"
    assert params["entered_at_from"] == "2026-01-01" and params["q"] == "山田"


@pytest.mark.asyncio
async def test_smarthr_pagination_reads_link_without_following(transport):
    transport[1].append(httpx.Response(200, json=[{"id": "c1", "name": "Fixture Ltd"}], headers={"Link": '<https://fixture.smarthr.jp/api/v1/companies?page=3>; rel="next"'}))
    result = await run("list_companies", {"page": 2})
    assert result["next_page"] == 3 and len(transport[0]) == 1
    assert module.SmartHRNode.connection_evidence.operation == "list_companies"
    assert result["items"][0]["name"] == "Fixture Ltd"


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ['https://evil.example/api/v1/companies?page=2', 'https://fixture.smarthr.jp/api/v1/companies?page=1'])
async def test_smarthr_pagination_refuses_foreign_and_repeated_pages(transport, link):
    transport[1].append(httpx.Response(200, json=[], headers={"Link": '<' + link + '>; rel="next"'}))
    with pytest.raises(ValueError, match="pagination"):
        await run("list_companies")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_smarthr_provider_errors_do_not_report_success(transport, status):
    transport[1].append(httpx.Response(status, json={"type": "unauthorized_token", "message": "refused " + AUTH["access_token"]}))
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await run("list_companies")
    assert AUTH["access_token"] not in str(exc.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "denied"}, {"errors": ["denied"]}, {"id": "unexpected object"}])
async def test_smarthr_wrong_list_envelopes_fail(transport, payload):
    transport[1].append(httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await run("list_companies")


@pytest.mark.parametrize("value", ["https://fixture.smarthr.jp", "fixture.smarthr.jp", "../other", "fixture:443", "evil@example", "fixture/other"])
def test_smarthr_host_is_tenant_subdomain_only(value):
    with pytest.raises(ValueError):
        module.SmartHRAccessTokenCredential.model_validate({**AUTH, "subdomain": value})


def test_smarthr_manual_credential_type_default_and_fields():
    shaped, errors, resolved = shape_credential("smarthr_access_token", {"subdomain": " fixture ", "access_token": AUTH["access_token"]})
    assert not errors and resolved is not None
    assert resolved[1].model_validate(shaped).model_dump() == AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["../other", "a/b", "a?b", "a%2Fb"])
async def test_smarthr_resource_path_injection_fails_before_http(transport, value):
    with pytest.raises(ValueError):
        await run("get_employee", {"id": value})
    assert not transport[0]


@pytest.mark.asyncio
async def test_smarthr_invalid_page_fails_before_http(transport):
    with pytest.raises(ValueError):
        await run("list_companies", {"per_page": 101})
    assert not transport[0]


@pytest.mark.parametrize("token", ["", "   ", "Bearer synthetic-token", "https://example.test/token", "token—bad"])
def test_smarthr_secret_paste_errors(token):
    with pytest.raises(ValueError):
        module.SmartHRAccessTokenCredential.model_validate({**AUTH, "access_token": token})
