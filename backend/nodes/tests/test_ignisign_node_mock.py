"""Offline request, connect, mutation and refusal regressions for Ignisign."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import ignisign_node as native
from nodes.core.registry import NodeFactory

KEY = "ignisign-synthetic-key-482"
CREDENTIAL = {
    "credential_type": "ignisign_api_key",
    "api_key": KEY,
    "app_id": "appId_owned",
    "app_env": "DEVELOPMENT",
}
CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures/ignisign/operations.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="ignisign-test",
        node_type="automation-ignisign",
        node_data={"config": config, "credentials": credential or CREDENTIAL},
    )


def intercept(monkeypatch, body=None, status=200, headers=None):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(
            status,
            json=body
            if body is not None
            else {"appId": "appId_owned", "appName": "Owned Application"},
            headers=headers,
        )

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONTRACT)
async def test_every_operation_uses_one_fixed_provider_route(monkeypatch, operation):
    method, path, path_fields, _, body_fields = native.ROUTES[operation]
    config = {"operation": operation, **{name: "owned-id" for name in path_fields}}
    if operation == "create_signer":
        config["signer_profile_id"] = "profile-owned"
    if operation == "create_document":
        config["signature_request_id"] = "request-owned"
    if operation == "create_webhook":
        config["url"] = "https://hooks.example.test/signatures"
    requests = intercept(monkeypatch)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == CONTRACT[operation]["method"] == method
    expected = (
        CONTRACT[operation]["path"]
        .replace("{appId}", "appId_owned")
        .replace("{appEnv}", "DEVELOPMENT")
    )
    for name in path_fields.values():
        expected = expected.replace("{" + name + "}", "owned-id")
    assert request.url.path == expected
    assert request.url.host == "api.ignisign.io"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert KEY not in str(result)
    if body_fields:
        assert request.headers["content-type"].startswith("application/json")
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_wire_body_preserves_false_arrays_and_date_time(monkeypatch):
    requests = intercept(monkeypatch)
    await node(
        {
            "operation": "update_signature_request",
            "signature_request_id": "request-owned",
            "document_ids": ["document-a", "document-b"],
            "signer_ids": ["signer-a"],
            "sign_documents_together": True,
            "individualize_requests": False,
            "expiration_date": "2026-12-01T12:00:00Z",
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "documentIds": ["document-a", "document-b"],
        "signerIds": ["signer-a"],
        "signDocumentsTogether": True,
        "individualizeRequests": False,
        "expirationDate": "2026-12-01T12:00:00Z",
    }


@pytest.mark.asyncio
async def test_search_filter_is_query_and_pagination_is_explicit(monkeypatch):
    requests = intercept(monkeypatch, {"signers": [], "total": 120})
    result = await node(
        {"operation": "search_signers", "filter": "alice + café"}
    ).execute({})
    assert dict(requests[0].url.params) == {"filter": "alice + café"}
    assert requests[0].content == b"" and result["data"]["total"] == 120
    requests = intercept(monkeypatch, {"signers": [], "total": 120})
    await node({"operation": "list_signers", "page": 2}).execute({})
    assert dict(requests[0].url.params) == {"page": "2"} and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_refusal_keeps_provider_text_and_redacts_key(monkeypatch, status):
    requests = intercept(monkeypatch, {"message": "Provider refusal: " + KEY}, status)
    result = await node({"operation": "get_application"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert (
        "Provider refusal" in result["error"]
        and KEY not in str(result)
        and len(requests) == 1
    )


@pytest.mark.asyncio
async def test_connect_identity_and_sensitive_fields(monkeypatch):
    intercept(
        monkeypatch,
        {"appName": "Owned Application", "envSettings": {"apiKey": KEY}, "echo": KEY},
    )
    result = await node({"operation": "get_application"}).execute({})
    assert result["data"]["appName"] == "Owned Application" and KEY not in str(result)
    evidence = native.IgnisignNode.connection_evidence
    assert (
        evidence.identity_operation == "get_application"
        and "appName" in evidence.identity_keys
    )
    assert (
        native.IgnisignCredential.model_validate(
            {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
        ).credential_type
        == "ignisign_api_key"
    )


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_document", "document_id": "../other"},
        {"operation": "update_signer"},
        {"operation": "create_signer"},
        {"operation": "create_document"},
        {
            "operation": "update_signature_request",
            "signature_request_id": "owned",
            "default_signature_method": "QES",
        },
        {
            "operation": "update_signature_request",
            "signature_request_id": "owned",
            "expiration_date": "tomorrow",
        },
    ],
)
def test_bad_required_fields_ids_and_enum_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize(
    "key", ["Bearer secret key", "https://example.test/key", "key\r\nheader", ""]
)
def test_manual_key_rejects_invalid_header_values(key):
    with pytest.raises((ValidationError, ValueError)):
        native.IgnisignCredential.model_validate({**CREDENTIAL, "api_key": key})
