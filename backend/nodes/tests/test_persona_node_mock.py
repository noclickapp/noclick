"""Persona wire contracts: one published operation per request, without network."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import persona_node as native
from nodes.core.credential_connect import shape_credential

CASES = json.loads((Path(__file__).parent / "fixtures/persona/requests.json").read_text())
CLIENT = httpx.AsyncClient


async def run(monkeypatch, config, handler):
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kw: CLIENT(transport=httpx.MockTransport(handler), **kw))
    data = {"config": config, "credentials": {"api_key": "persona-test-secret"}}
    parsed = native.PersonaNode.parse_config(data)
    node = native.PersonaNode("test", "automation-persona", data, config=parsed)
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_published_requests(monkeypatch, case):
    calls = []

    def provider(request):
        calls.append(request)
        assert request.method == case["method"]
        assert str(request.url).split("?")[0] == native.BASE_URL + case["path"]
        assert dict(request.url.params) == case.get("query", {})
        assert (json.loads(request.content) if request.content else None) == case.get("body")
        assert request.headers["Authorization"] == "Bearer persona-test-secret"
        assert request.headers["Persona-Version"] == "2026-09-29"
        assert request.headers["Key-Inflection"] == "kebab"
        resource = {"id": "inq_ABC123", "type": "inquiry", "attributes": {"status": "completed"}}
        data = [resource] if case["config"]["operation"].startswith("list_") else resource
        return httpx.Response(200, json={"data": data, "links": {"next": None}})

    output = await run(monkeypatch, case["config"], provider)
    assert output["status"] == "success"
    assert output["data"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_pagination_never_follows_provider_url(monkeypatch):
    calls = []

    def provider(request):
        calls.append(request)
        assert dict(request.url.params) == {"page[size]": "5", "page[after]": "inq_ABC123", "filter[status]": "completed,approved"}
        return httpx.Response(200, json={"data": [], "links": {"next": "https://untrusted.example/page"}})

    result = await run(monkeypatch, {"operation": "list_inquiries", "page_size": 5, "page_after": "inq_ABC123", "inquiry_status": "completed,approved"}, provider)
    assert result["status"] == "success" and result["data"] == []
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_errors_do_not_succeed_or_retry(monkeypatch, status):
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(status, json={"errors": [{"title": "Not authorized"}]})

    result = await run(monkeypatch, {"operation": "expire_inquiry", "inquiry_id": "inq_ABC123"}, provider)
    assert result == {"status": "error", "http_status": status, "error": "Not authorized"}
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": None}, {"data": {}}, {"data": [], "errors": [{"title": "Rejected"}]}])
async def test_malformed_success_is_not_connection_evidence(monkeypatch, body):
    result = await run(monkeypatch, {"operation": "list_inquiries"}, lambda request: httpx.Response(200, json=body))
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_transport_failure_is_not_retried(monkeypatch):
    calls = []

    def provider(request):
        calls.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    result = await run(monkeypatch, {"operation": "create_account", "reference_id": "abc-123"}, provider)
    assert result["status"] == "error" and len(calls) == 1


def test_manual_credential_and_evidence():
    credential = native.PersonaAPIKeyCredential(api_key="persona-test-secret")
    assert credential.credential_type == "persona_api_key"
    shaped, errors, resolved = shape_credential("persona_api_key", {"api_key": "persona-test-secret"})
    assert not errors and resolved[1] is native.PersonaAPIKeyCredential
    assert native.PersonaAPIKeyCredential.model_validate(shaped).credential_type == "persona_api_key"
    assert native.PersonaNode.connection_evidence.operation == "list_inquiries"
    assert native.PersonaNode.parse_config({"config": {"operation": "list_inquiries"}, "credentials": shaped})


@pytest.mark.parametrize("bad", ["../inq_other", "inq_a/b", "https://example.com", "inq_a?x=y"])
def test_path_injection_rejected(bad):
    with pytest.raises(ValidationError):
        native.GetInquiry(inquiry_id=bad)


def test_fixture_covers_every_operation():
    assert {case["config"]["operation"] for case in CASES} == set(native.ROUTES)
