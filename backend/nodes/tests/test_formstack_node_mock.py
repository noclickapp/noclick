"""Verify Formstack requests through the actual node factory and HTTP transport.

Fixtures use synthetic account data; no provider account or API token is needed.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import formstack_node as native
from nodes.core.registry import NodeFactory

TOKEN = "fs_pat_synthetic_test_credential"
CASES = json.loads((Path(__file__).parent / "fixtures/formstack/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="formstack-test", node_type="automation-formstack",
        node_data={"config": config, "credentials": {"credential_type": "formstack_token", "access_token": TOKEN}})


def transport(monkeypatch, status=200, payload=None, content=None):
    calls = []
    client_class = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=payload if payload is not None else {"id": 73})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        return client_class(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_all_operations_send_the_documented_request(monkeypatch, case):
    calls = transport(monkeypatch)
    result = await node(case["config"]).execute({})
    assert result == {"data": {"id": 73}, "http_status": 200}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert str(request.url.copy_with(query=None)) == "https://www.formstack.com/api/v2025" + case["path"]
    assert dict(request.url.params) == case.get("query", {})
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Accept"] == "application/json"
    assert TOKEN not in str(request.url)
    if "body" in case:
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == case["body"]
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_pagination_and_submission_values_are_preserved(monkeypatch):
    body = {"page": {"size": 1, "pageNumber": 2, "pageSize": 10, "totalElements": 21, "totalPages": 3},
            "submissions": [{"id": 73, "data": [{"id": "10", "parsedValue": {"first": "Ada", "last": "Lovelace"}}]}]}
    calls = transport(monkeypatch, payload=body)
    output = await node({"operation": "list_form_submissions", "form_id": 12, "pageNumber": 2, "pageSize": 10,
                         "minTime": "2026-01-01", "keyword": "A+B & C"}).execute({})
    assert output["data"] == body
    assert len(calls) == 1
    assert calls[0].url.params["pageNumber"] == "2"
    assert calls[0].url.params["keyword"] == "A+B & C"
    assert calls[0].url.params["minTime"] == "2026-01-01"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500])
async def test_provider_failures_do_not_retry_or_expose_token(monkeypatch, status):
    calls = transport(monkeypatch, status=status, payload={"error": "Rejected " + TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({"operation": "create_folder", "name": "Reports"}).execute({})
    assert str(status) in str(exc.value)
    assert TOKEN not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"success": False, "message": "Rejected"}, {"error": "Bad request"}, 42, "unexpected"])
async def test_invalid_and_error_json_is_rejected(monkeypatch, payload):
    transport(monkeypatch, payload=payload)
    with pytest.raises(ValueError):
        await node({"operation": "list_forms"}).execute({})


@pytest.mark.asyncio
async def test_html_is_rejected(monkeypatch):
    transport(monkeypatch, content=b"<html>not JSON</html>")
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_forms"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_form", "form_id": "../folders"},
    {"operation": "get_form", "form_id": 0},
    {"operation": "list_forms", "pageSize": 1},
    {"operation": "list_forms", "pageNumber": 0},
    {"operation": "search_submissions"},
    {"operation": "create_submission", "form_id": 12, "fields": []},
    {"operation": "list_forms", "url": "https://evil.test"},
])
def test_invalid_config_is_rejected(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_credential_default_and_secret_normalization():
    credential = native.FormstackTokenCredential(access_token="  " + TOKEN + "  ")
    assert credential.credential_type == "formstack_token"
    assert credential.access_token == TOKEN
    for value in ["Bearer " + TOKEN, "https://example.com/token", "<token>", "bad\ntoken"]:
        with pytest.raises(ValueError):
            native.FormstackTokenCredential(access_token=value)


@pytest.mark.asyncio
async def test_connection_evidence_uses_account_forms(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    calls = transport(monkeypatch, payload={"forms": [{"id": 12, "name": "Customer feedback"}]})
    result = await collect_evidence(node_type="automation-formstack", user_id="test-user", credential_data={"credential_type": "formstack_token", "access_token": TOKEN})
    assert result.reachable is True
    assert "Customer feedback" in str(result)
    assert len(calls) == 1 and calls[0].url.path == "/api/v2025/forms"


@pytest.mark.parametrize("value", [{"value": "Ada"}, {"first": "Ada", "last": "Lovelace"}])
def test_published_submission_union_contradicts_its_own_value_schemas(value):
    from jsonschema import Draft4Validator
    contract = json.loads((Path(__file__).parent / "fixtures/formstack/submission-value-schema.json").read_text())["schema"]
    definitions = contract["components"]["schemas"]
    branch = "SubmissionParsedFieldTextValueApiDto" if "value" in value else "SubmissionParsedFieldNameValueApiDto"
    # Each value conforms to its provider-defined object; the enclosing oneOf rejects it.
    Draft4Validator({"$ref": "#/components/schemas/" + branch, "components": contract["components"]}).validate(value)
    errors = list(Draft4Validator(contract).iter_errors({"id": "45", "value": value}))
    assert errors and any("valid under each" in str(error) for error in errors)
    assert definitions["SubmissionParsedFieldApiDto"]["properties"]["value"]["oneOf"]


@pytest.mark.asyncio
async def test_truncated_provider_error_redacts_before_cutting(monkeypatch):
    transport(monkeypatch, status=401, content=("z" * 1995 + TOKEN).encode())
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_forms"}).execute({})
    assert TOKEN[:5] not in str(exc.value)
