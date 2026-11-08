"""Exercise FullEnrich through the native node factory with captured HTTP requests.

Fixtures use values in the official v2 contract; negative cases cover credential
rejection, ambiguous writes, pagination, and response shape failures.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import fullenrich_node as node
from nodes.core.run_op import run_node_operation
from nodes.core.base import ConfigValidationError

CASES = json.loads((Path(__file__).parent / "fixtures/fullenrich/requests.json").read_text())["cases"]
AUTH = {"credential_type": "fullenrich_api_key", "api_key": "fullenrich-test-token-12345"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    seen, replies = [], []
    native = httpx.AsyncClient

    async def send(request):
        seen.append(request)
        assert request.url.host == "app.fullenrich.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        code, body = reply
        if isinstance(body, bytes):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)

    monkeypatch.setattr(node.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return seen, replies


async def run(operation, config=None, credential=None):
    return await run_node_operation(node_type="automation-fullenrich", operation=operation,
        arguments=config or {}, credential_data=credential or AUTH,
        user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_all_operations(transport, case):
    seen, replies = transport
    replies.append((case.get("response_status", 200), case["response"]))
    result = await run(case["operation"], case["config"])
    assert result == {"status": "success", "data": case["response"]}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == case["method"]
    assert request.url.path == "/api/v2" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    if request.method == "POST":
        expected = {k: v for k, v in case["config"].items()
                    if k not in {"silent_fail", "sub_account_id"}}
        if case["operation"].startswith("search_"):
            expected = {"limit": 10, "offset": 0, **expected}
        assert json.loads(request.content) == expected
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_cursor_pagination_omits_offset_and_preserves_metadata(transport):
    seen, replies = transport
    payload = {"companies": [], "metadata": {"search_after": "next-page", "total": 200}}
    replies.append((200, payload))
    result = await run("search_companies", {"offset": 10000, "search_after": "previous-page"})
    assert json.loads(seen[0].content) == {"limit": 10, "search_after": "previous-page"}
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 401, 403, 429, 500])
async def test_provider_errors_do_not_claim_success_or_echo_secrets(transport, code):
    _, replies = transport
    replies.append((code, {"code": "error.api.key", "message": "Unknown api key " + AUTH["api_key"]}))
    result = await run("verify_api_key")
    assert result["status"] == "error"
    assert result["http_status"] == code
    assert "Unknown api key" in result["error"]
    assert AUTH["api_key"] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(200, b"<html>Wrong endpoint</html>"), (200, {}), (200, []), (302, {"url":"https://example.com"})])
async def test_invalid_identity_and_redirects(transport, code, body):
    seen, replies = transport
    replies.append((code, body))
    with pytest.raises(ValueError):
        await run("verify_api_key")
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_retry_a_write(transport):
    seen, replies = transport
    replies.append(httpx.ReadTimeout("timeout"))
    with pytest.raises(ValueError, match="inspect the dashboard"):
        await run("create_sub_account", {"name":"Acme Europe"})
    assert len(seen) == 1


@pytest.mark.parametrize("operation,config", [
    ("enrich_contacts", {"name":"Batch", "data":[]}),
    ("enrich_contacts", {"name":"Batch", "data":[{"enrich_fields":["contact.phones"]}]}),
    ("lookup_person", {}), ("lookup_company", {}),
    ("search_people", {"limit":101}), ("search_companies", {"offset":10001}),
    ("update_sub_account", {"sub_account_id":"70ff6a88-6291-417d-b6cd-04f1ca123470"}),
    ("get_sub_account", {"sub_account_id":"../other"}),
    ("get_enrichment", {"enrichment_id":"../other"}),
    ("search_people", {"current_company_headcounts":[{"min":500,"max":100}]}),
])
def test_invalid_configuration(operation, config):
    with pytest.raises(ConfigValidationError):
        node.FullenrichNode.parse_config({"config":{"operation":operation, **config}, "credentials":AUTH})


@pytest.mark.parametrize("value", ["Bearer token", "https://example.com/key", "", "<token>"])
def test_pasted_key_validation(value):
    with pytest.raises(ValidationError):
        node.FullenrichAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_connection_evidence_names_the_verified_workspace(transport):
    from nodes.core.connection_evidence import collect_evidence
    seen, replies = transport
    workspace = "2db5ea61-1752-42cf-8ea1-ab1da060cd0a"
    replies.append((200, {"workspace_id": workspace}))
    evidence = await collect_evidence(node_type="automation-fullenrich", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert evidence.account_label == workspace
    assert len(seen) == 1
    assert seen[0].url.path == "/api/v2/account/keys/verify"
