"""Signable's published examples through the registered node and real HTTP client."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import signable_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/signable/documented_responses.json").read_text())
KEY = "synthetic-signable-api-key"
CREDENTIAL = {"credential_type": "signable_api_key", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="signable-test", node_type="automation-signable",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, status, body, mime="application/json"):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, **({"content": body} if isinstance(body, bytes) else {"json": body}),
            headers={"Content-Type": mime})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_published_examples_exact_method_route_and_payload(monkeypatch, operation):
    f = FIXTURES[operation]
    body = f["body"] if f["body"] is not None else b"%PDF-1.4\nfixture"
    requests = transport(monkeypatch, f["status"], body, f["mime"])
    result = await node(f["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == f["method"]
    assert req.url.host == "api.signable.co.uk"
    route = f["path"]
    values = {k: v for k, v in f["config"].items() if k != "operation"}
    for name in tuple(values):
        if "{" + name + "}" in route:
            route = route.replace("{" + name + "}", str(values.pop(name)))
    assert req.url.path == "/v1" + route
    assert req.headers["authorization"] == "Basic " + base64.b64encode((KEY + ":x").encode()).decode()
    if operation.startswith("list_"):
        assert dict(req.url.params) == {"offset": "0", "limit": "10"}
        assert result["items"] == f["body"]["envelopes" if operation == "list_contact_envelopes" else operation[5:]]
    elif values and f["method"] != "GET":
        sent = json.loads(req.content)
        for k, v in values.items():
            assert sent[k] == v
        assert all(v is not None for v in sent.values())
    assert result["data"] == body
    if operation == "create_envelope":
        assert json.loads(req.content)["is_draft"] is False
        assert result["http_status"] == 202 and result["delivery_verified"] is False


@pytest.mark.asyncio
async def test_filters_pagination_and_no_following_provider_next(monkeypatch):
    body = {**FIXTURES["list_envelopes"]["body"], "next": "https://untrusted.example/next"}
    requests = transport(monkeypatch, 200, body)
    result = await node({"operation": "list_envelopes", "offset": 20, "limit": 25,
        "envelope_status": "signed", "q": "Contract + café"}).execute({})
    assert result["data"]["next"] == body["next"] and len(requests) == 1
    assert dict(requests[0].url.params) == {"offset": "20", "limit": "25", "envelope_status": "signed", "q": "Contract + café"}


@pytest.mark.asyncio
async def test_draft_url_document_and_partial_contact_update(monkeypatch):
    requests = transport(monkeypatch, 202, FIXTURES["create_envelope"]["body"])
    await node({"operation": "create_envelope", "envelope_title": "Agreement", "is_draft": True,
        "envelope_parties": [{"party_name": "Alex", "party_email": "alex@example.com"}],
        "envelope_documents": [{"document_title": "Agreement", "document_url": "https://example.com/agreement.pdf"}]}).execute({})
    assert json.loads(requests[0].content)["is_draft"] is True
    assert "party_id" not in json.loads(requests[0].content)["envelope_parties"][0]
    requests = transport(monkeypatch, 200, FIXTURES["update_contact"]["body"])
    await node({"operation": "update_contact", "contact_id": 123, "contact_email": "new@example.com"}).execute({})
    assert json.loads(requests[0].content) == {"contact_email": "new@example.com"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_failure_is_not_success_and_secret_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, status, {"message": "Denied " + KEY})
    result = await node({"operation": "list_contacts"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_embedded_error_and_malformed_lists(monkeypatch):
    transport(monkeypatch, 200, {"http": 401, "message": "Authentication failed"})
    assert (await node({"operation": "list_contacts"}).execute({}))["status"] == "error"
    transport(monkeypatch, 200, {"http": 200})
    with pytest.raises(ValueError, match="missing its records"):
        await node({"operation": "list_contacts"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "update_contact", "contact_id": 1},
    {"operation": "update_envelope_party", "envelope_fingerprint": "abc", "party_id": 1},
    {"operation": "list_contacts", "limit": 51},
    {"operation": "list_contacts", "offset": -1},
    {"operation": "create_contact", "contact_name": "Alex"},
])
def test_required_fields_and_empty_update_validation(config):
    with pytest.raises(ValueError):
        native.SignableNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_credential_default_and_connection_evidence():
    assert native.SignableAPIKeyCredential(api_key=KEY).credential_type == "signable_api_key"
    assert native.SignableNode.connection_evidence.operation == "list_contacts"
    assert len(native.ROUTES) == 21
