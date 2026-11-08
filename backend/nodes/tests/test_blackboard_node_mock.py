"""Offline wire tests; fixture values are synthetic, routes follow Learn 4001.4.0."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import blackboard_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-blackboard-token"
CREDENTIAL = {"credential_type": "blackboard_access_token", "site_url": "https://school.blackboard.com", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/blackboard/wire_cases.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="blackboard-fixture", node_type="automation-blackboard",
        node_data={"config": config, "credentials": CREDENTIAL if credential is None else credential})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert "trusted_exact_urls" not in kwargs
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_all_operations_through_real_factory(monkeypatch, case):
    payload = {"results": [{"id": "_123_1", "name": "Mathematics"}], "paging": {"nextPage": "/learn/api/public/v3/courses?offset=100&limit=100"}} if case["operation"].startswith("list_") else {"id": "_123_1", "courseId": "_123_1", "userId": "_456_1"}
    calls = transport(monkeypatch, lambda req: httpx.Response(case["status"], **({"json": payload} if case["status"] != 204 else {})))
    result = await node({"operation": case["operation"], **case["config"]}).execute({})
    assert result["status"] == "success" and result["http_status"] == case["status"]
    assert len(calls) == 1
    req = calls[0]
    assert req.method == case["method"] and req.url.path == case["path"]
    assert req.url.host == "school.blackboard.com" and req.url.scheme == "https"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert dict(req.url.params) == case["params"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    if case["status"] == 204:
        assert result["deletion_acknowledged"] is True
        assert "data" not in result
    else:
        assert result["data"] == payload


@pytest.mark.asyncio
async def test_empty_course_page_is_valid_connection_evidence(monkeypatch):
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json={"results": []}))
    spec = native.BlackboardNode.connection_evidence
    result = await node({"operation": spec.operation}).execute({})
    assert result["data"]["results"] == [] and result["status"] == "success"
    assert len(calls) == 1 and calls[0].url.path == "/learn/api/public/v3/courses"
    assert spec.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_do_not_follow_redirects_or_leak_token(monkeypatch, status):
    calls = transport(monkeypatch, lambda req: httpx.Response(status, headers={"Location": "https://other.example/"}, json={"message": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_courses"}).execute({})
    assert str(status) in str(exc.value) and TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_redacts_nested_response_secrets(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"id": "_123_1", "password": "never-return", "nested": {"access_token": TOKEN, "text": TOKEN}}))
    result = await node({"operation": "get_user", "user_id": "_123_1"}).execute({})
    assert TOKEN not in str(result) and "never-return" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}, {"results": {}}, {"results": ["bad-row"]}])
async def test_rejects_invalid_list_envelopes(monkeypatch, payload):
    transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_courses"}).execute({})


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_not_retried(monkeypatch):
    def timeout(req):
        raise httpx.ReadTimeout("request timed out", request=req)
    calls = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="write outcome is unknown"):
        await node({"operation": "create_course", "course_code": "math101", "name": "Math"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_guard_blocks_private_dns_before_sending_credentials(monkeypatch):
    import asyncio
    import socket
    from utils.ssrf import SSRFError

    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "0")
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(SSRFError, match="non-public"):
        await node({"operation": "list_courses"}).execute({})


@pytest.mark.parametrize("url", ["http://school.blackboard.com", "https://127.0.0.1", "https://[::1]", "https://school.blackboard.com/path", "https://school.blackboard.com?x=y", "https://user:secret@school.blackboard.com", "https://school.blackboard.com:8000", "https://school.blackboard.com/#fragment", "https://school.blackboard.com\n"])
def test_credential_rejects_invalid_site_origins(url):
    with pytest.raises(ValidationError):
        native.BlackboardAccessTokenCredential.model_validate({**CREDENTIAL, "site_url": url})


@pytest.mark.parametrize("token", ["Bearer some-token", "https://example.com", "token\nheader", ""])
def test_credential_rejects_bad_tokens(token):
    with pytest.raises(ValidationError):
        native.BlackboardAccessTokenCredential.model_validate({**CREDENTIAL, "access_token": token})


def test_manual_credential_default_and_custom_institution_domain():
    credential = native.BlackboardAccessTokenCredential(site_url="https://LEARN.university.edu/", access_token=TOKEN)
    assert credential.credential_type == "blackboard_access_token"
    assert credential.site_url == "https://learn.university.edu"
    assert native.BlackboardNode.get_config_schema()["$defs"]["BlackboardAccessTokenCredential"]["title"] == "Blackboard Access Token"


@pytest.mark.parametrize("config", [
    {"operation": "get_course", "course_id": "../users"},
    {"operation": "get_user", "user_id": "%2Fusers"},
    {"operation": "update_course", "course_id": "_123_1"},
    {"operation": "update_membership", "course_id": "_123_1", "user_id": "_456_1"},
    {"operation": "update_announcement", "course_id": "_123_1", "announcement_id": "_789_1"},
    {"operation": "list_courses", "limit": 0},
    {"operation": "list_courses", "offset": -1},
    {"operation": "create_membership", "course_id": "_123_1", "user_id": "_456_1", "course_role": "Administrator"},
])
def test_config_rejects_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)
