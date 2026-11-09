"""Clicksign transport-boundary tests; no live account or credentials."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import clicksign_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-clicksign-token-42"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment="sandbox"):
    return NodeFactory.create_node(node_id="clicksign-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"credential_type": "clicksign_access_token", "access_token": TOKEN, "environment": environment}})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("environment,host", [("sandbox", "sandbox.clicksign.com"), ("production", "app.clicksign.com")])
async def test_connect_reads_account_envelopes_and_raw_token(monkeypatch, environment, host):
    requests = transport(monkeypatch, {"data": [{"id": "env-1", "type": "envelopes", "attributes": {"name": "Contract"}}], "links": {"next": "https://evil.test/"}})
    result = await node({"operation": "list_envelopes"}, environment).execute({})
    assert result["status"] == "success" and result["items"][0]["name"] == "Contract"
    assert len(requests) == 1
    assert requests[0].url.host == host
    assert requests[0].headers["Authorization"] == TOKEN
    assert requests[0].headers["Content-Type"] == "application/vnd.api+json"
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_envelope_create_and_activation_jsonapi(monkeypatch):
    requests = transport(monkeypatch, {"data": {"id": "env-1", "type": "envelopes"}}, 201)
    await node({"operation": "create_envelope", "name": "Contract", "folder_id": "folder-1", "auto_close": False}).execute({})
    assert json.loads(requests[0].content) == {"data": {"type": "envelopes", "attributes": {"name": "Contract", "auto_close": False}, "relationships": {"folder": {"data": {"type": "folders", "id": "folder-1"}}}}}
    await node({"operation": "update_envelope", "envelope_id": "env-1", "status": "running"}).execute({})
    assert requests[-1].method == "PATCH"
    assert json.loads(requests[-1].content) == {"data": {"id": "env-1", "type": "envelopes", "attributes": {"status": "running"}}}


@pytest.mark.asyncio
async def test_upload_and_signer_requirements(monkeypatch):
    requests = transport(monkeypatch, {"data": {"type": "documents", "id": "doc-1"}}, 201)
    await node({"operation": "upload_document", "envelope_id": "env-1", "filename": "contract.txt", "content_base64": "data:text/plain;base64,SGVsbG8="}).execute({})
    assert requests[0].url.path == "/api/v3/envelopes/env-1/documents"
    assert json.loads(requests[0].content)["data"]["attributes"]["content_base64"] == "data:text/plain;base64,SGVsbG8="
    await node({"operation": "create_qualification_requirement", "envelope_id": "env-1", "document_id": "doc-1", "signer_id": "signer-1", "role": "party"}).execute({})
    data = json.loads(requests[-1].content)["data"]
    assert data["attributes"] == {"role": "party", "action": "agree"}
    assert data["relationships"] == {"document": {"data": {"type": "documents", "id": "doc-1"}}, "signer": {"data": {"type": "signers", "id": "signer-1"}}}


@pytest.mark.asyncio
async def test_filters_notifications_and_delete(monkeypatch):
    requests = transport(monkeypatch, {"data": []})
    await node({"operation": "list_envelopes", "status": "running", "name": "Signed + approved", "sort": "-name"}).execute({})
    assert dict(requests[0].url.params) == {"filter[status]": "running", "filter[name]": "Signed + approved", "sort": "-name"}
    requests = transport(monkeypatch, {"data": {"type": "notifications", "id": "notification-1"}})
    await node({"operation": "notify_signer", "envelope_id": "env-1", "signer_id": "signer-1", "message": "Please sign"}).execute({})
    assert requests[0].url.path.endswith("/signers/signer-1/notifications")
    assert json.loads(requests[0].content) == {"data": {"type": "notifications", "attributes": {"message": "Please sign"}}}
    transport(monkeypatch, status=204)
    assert (await node({"operation": "delete_document", "envelope_id": "env-1", "document_id": "doc-1"}).execute({}))["deleted"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_failures_preserve_provider_rejection_but_redact_secret(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": [{"detail": "Access Token inválido " + TOKEN}]}, status)
    result = await node({"operation": "list_envelopes"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert "Access Token inválido" in result["error"] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"errors": []}, {"data": {}}, {"data": None}])
async def test_invalid_list_response_is_not_connection_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_envelopes"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_every_operation_has_one_fixed_contract_request(monkeypatch):
    cases = json.loads((Path(__file__).parent / "fixtures/clicksign/requests.json").read_text())
    assert set(cases) == set(native.ROUTES) and len(cases) == 25
    for operation, case in cases.items():
        method, path, kind, _, _ = native.ROUTES[operation]
        body = {"data": [] if operation.startswith("list_") else {"type": kind, "id": "resource-1"}}
        requests = transport(monkeypatch, body, 204 if method == "DELETE" else 200)
        result = await node(case).execute({})
        assert result["status"] == "success", (operation, result)
        assert len(requests) == 1 and requests[0].method == method
        assert requests[0].url.path == "/api/v3" + path.format(**case)


def test_manual_credential_default_and_invalid_hosts_ids():
    assert native.ClicksignAccessTokenCredential(access_token=TOKEN).credential_type == "clicksign_access_token"
    for env in ["https://evil.test", "evil", "https://sandbox.clicksign.com"]:
        with pytest.raises(ValidationError):
            native.ClicksignAccessTokenCredential(access_token=TOKEN, environment=env)
    for resource in ["../documents", "https://evil.test", "env/other", "env?secret=1"]:
        with pytest.raises((ValidationError, ValueError)):
            node({"operation": "get_envelope", "envelope_id": resource})
    with pytest.raises(ValidationError):
        native.ClicksignAccessTokenCredential(access_token="Bearer " + TOKEN)

@pytest.mark.asyncio
async def test_current_docs_metadata_is_object(monkeypatch):
    requests = transport(monkeypatch, {"data": {"type": "documents", "id": "doc-1"}})
    result = await node({"operation": "update_document", "envelope_id": "env-1", "document_id": "doc-1", "metadata": {"key": "value"}}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content)["data"]["attributes"]["metadata"] == {"key": "value"}


@pytest.mark.asyncio
async def test_provider_examples_with_invalid_json_are_rejected(monkeypatch):
    examples = json.loads((Path(__file__).parent / "fixtures/clicksign/malformed_provider_examples.json").read_text())
    for operation, example in examples.items():
        # These exact published strings have metadata {"key": "value": }.
        with pytest.raises(json.JSONDecodeError):
            json.loads(example)
        def client(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=example)), **kwargs)
        monkeypatch.setattr(native, "guarded_async_client", client)
        cfg = {"operation": operation, "envelope_id": "env-1"}
        cfg.update({"document_id": "doc-1", "status": "closed"} if operation == "update_document" else {"filename": "contract.txt", "content_base64": "data:text/plain;base64,SGVsbG8="})
        assert (await node(cfg).execute({}))["status"] == "error"

@pytest.mark.asyncio
async def test_requests_match_current_provider_schemas_where_pin_is_stale(monkeypatch):
    from jsonschema import Draft202012Validator
    fixtures = json.loads((Path(__file__).parent / "fixtures/clicksign/current_documented_requests.json").read_text())
    cases = json.loads((Path(__file__).parent / "fixtures/clicksign/requests.json").read_text())
    for operation, documented in fixtures.items():
        requests = transport(monkeypatch, {"data": {"type": "documents", "id": "doc-1"}})
        cfg = cases[operation]
        if operation in {"upload_document", "update_document"}:
            cfg["metadata"] = {"key": "value"}
        await node(cfg).execute({})
        Draft202012Validator(documented["schema"]).validate(json.loads(requests[0].content))
