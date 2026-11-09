"""Exercise native node requests against the provider's published v3 wire contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import youtrust_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/youtrust/contracts.json").read_text())
TOKEN = "synthetic-youtrust-secret"
R = FIXTURE["signature_request_id"]
S = FIXTURE["signer_id"]
D = FIXTURE["document_id"]
C = FIXTURE["contact_id"]
T = FIXTURE["template_id"]
PERSON = FIXTURE["person"]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment="production"):
    return NodeFactory.create_node(node_id="youtrust-fixture", node_type="automation-youtrust", node_data={
        "config": config, "credentials": {"credential_type": "youtrust_api_token", "api_token": TOKEN, "environment": environment}})


def transport(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Expected paths/methods are literal contract routes, independent of the node's route table.
CASES = [
    ({"operation": "list_signature_requests"}, "GET", "/signature_requests", 200, {"data": [], "meta": {"next_cursor": None}}),
    ({"operation": "get_signature_request", "signature_request_id": R}, "GET", f"/signature_requests/{R}", 200, {"id": R, "status": "draft"}),
    ({"operation": "create_signature_request", "name": "Contract"}, "POST", "/signature_requests", 201, {"id": R, "status": "draft"}),
    ({"operation": "update_signature_request", "signature_request_id": R, "name": "Contract revised"}, "PATCH", f"/signature_requests/{R}", 200, {"id": R, "name": "Contract revised"}),
    ({"operation": "delete_signature_request", "signature_request_id": R}, "DELETE", f"/signature_requests/{R}", 204, None),
    ({"operation": "activate_signature_request", "signature_request_id": R}, "POST", f"/signature_requests/{R}/activate", 201, {"id": R, "status": "ongoing"}),
    ({"operation": "cancel_signature_request", "signature_request_id": R, "reason": "errors_in_document"}, "POST", f"/signature_requests/{R}/cancel", 201, {"id": R, "status": "canceled"}),
    ({"operation": "list_signers", "signature_request_id": R}, "GET", f"/signature_requests/{R}/signers", 200, [{"id": S}]),
    ({"operation": "get_signer", "signature_request_id": R, "signer_id": S}, "GET", f"/signature_requests/{R}/signers/{S}", 200, {"id": S}),
    ({"operation": "create_signer", "signature_request_id": R, **PERSON}, "POST", f"/signature_requests/{R}/signers", 201, {"id": S}),
    ({"operation": "update_signer", "signature_request_id": R, "signer_id": S, **PERSON}, "PATCH", f"/signature_requests/{R}/signers/{S}", 200, {"id": S}),
    ({"operation": "delete_signer", "signature_request_id": R, "signer_id": S}, "DELETE", f"/signature_requests/{R}/signers/{S}", 204, None),
    ({"operation": "send_signer_reminder", "signature_request_id": R, "signer_id": S}, "POST", f"/signature_requests/{R}/signers/{S}/send_reminder", 201, None),
    ({"operation": "list_documents", "signature_request_id": R}, "GET", f"/signature_requests/{R}/documents", 200, [{"id": D, "nature": "signable_document"}]),
    ({"operation": "get_document", "signature_request_id": R, "document_id": D}, "GET", f"/signature_requests/{R}/documents/{D}", 200, {"id": D}),
    ({"operation": "delete_document", "signature_request_id": R, "document_id": D}, "DELETE", f"/signature_requests/{R}/documents/{D}", 204, None),
    ({"operation": "list_contacts"}, "GET", "/contacts", 200, {"data": [], "meta": {"next_cursor": None}}),
    ({"operation": "get_contact", "contact_id": C}, "GET", f"/contacts/{C}", 200, {"id": C}),
    ({"operation": "create_contact", **PERSON}, "POST", "/contacts", 201, {"id": C}),
    ({"operation": "update_contact", "contact_id": C, **PERSON}, "PATCH", f"/contacts/{C}", 200, {"id": C}),
    ({"operation": "delete_contact", "contact_id": C}, "DELETE", f"/contacts/{C}", 204, None),
    ({"operation": "list_templates"}, "GET", "/templates", 200, {"data": [], "meta": {"next_cursor": None}}),
    ({"operation": "get_template", "template_id": T}, "GET", f"/templates/{T}", 200, {"id": T}),
    ({"operation": "list_workspaces"}, "GET", "/workspaces", 200, {"data": [], "meta": {"next_cursor": None}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,status,body", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_native_wire_contract(monkeypatch, config, method, path, status, body):
    requests = transport(monkeypatch, status, body)
    result = await node(config).execute({})
    assert result["success"] is True and result["http_status"] == status
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == "/v3" + path
    assert req.url.host == "api.yousign.app"
    assert req.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if method in {"GET", "DELETE"} or config["operation"] == "send_signer_reminder":
        assert req.content == b""
    elif config["operation"] == "create_signer":
        assert json.loads(req.content) == {"info": PERSON, "signature_level": "electronic_signature", "signature_authentication_mode": "otp_email"}
    elif config["operation"] == "update_signer":
        assert json.loads(req.content) == {"info": PERSON}
    elif config["operation"] == "create_signature_request":
        assert json.loads(req.content) == {"name": "Contract", "delivery_mode": "none", "ordered_signers": False}
    elif config["operation"] == "cancel_signature_request":
        assert json.loads(req.content) == {"reason": "errors_in_document"}
    elif config["operation"] == "activate_signature_request":
        assert json.loads(req.content) == {}
    elif config["operation"] in {"create_contact", "update_contact"}:
        assert json.loads(req.content) == PERSON
    elif config["operation"] == "update_signature_request":
        assert json.loads(req.content) == {"name": "Contract revised"}


@pytest.mark.asyncio
async def test_pagination_filters_and_sandbox(monkeypatch):
    requests = transport(monkeypatch, 200, {"data": [{"id": R, "name": "Owned contract"}], "meta": {"next_cursor": "next+token/="}})
    result = await node({"operation": "list_signature_requests", "after": "previous+token/=", "limit": 5,
                         "status": "done", "external_id": "order-42", "q": "Contract + café"}, "sandbox").execute({})
    assert requests[0].url.host == "api-sandbox.yousign.app"
    assert dict(requests[0].url.params) == {"after": "previous+token/=", "limit": "5", "status[eq]": "done", "external_id[eq]": "order-42", "q": "Contract + café"}
    assert result["has_more"] is True and result["next_cursor"] == "next+token/="
    assert result["data"][0]["name"] == "Owned contract"


@pytest.mark.asyncio
async def test_template_creation_and_cancellation_body(monkeypatch):
    requests = transport(monkeypatch, 201, {"id": R})
    await node({"operation": "create_signature_request", "name": "Contract", "template_id": T, "delivery_mode": "email"}).execute({})
    assert json.loads(requests[0].content) == {"name": "Contract", "template_id": T, "delivery_mode": "email", "ordered_signers": False}
    await node({"operation": "cancel_signature_request", "signature_request_id": R, "reason": "other", "custom_note": "Replaced contract"}).execute({})
    assert json.loads(requests[1].content) == {"reason": "other", "custom_note": "Replaced contract"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_do_not_claim_success_or_leak_token(monkeypatch, status):
    requests = transport(monkeypatch, status, {"detail": "Rejected token " + TOKEN})
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_contacts"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {}, {"errors": []}, {"data": [], "meta": {"next_cursor": "previous"}}, {"data": {}, "meta": {"next_cursor": None}}])
async def test_bad_pages_fail(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        await node({"operation": "list_contacts", "after": "previous"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_signature_request", "signature_request_id": "../bad"},
    {"operation": "get_signer", "signature_request_id": R},
    {"operation": "list_templates", "limit": 100},
    {"operation": "create_contact", **PERSON, "email": "wrong"},
    {"operation": "create_signature_request", "name": "Contract", "template_id": "z" * 36},
])
def test_config_refuses_invalid_ids_and_provider_bounds(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_connect_credential_default_and_connection_evidence():
    creds = native.YoutrustAPITokenCredential(api_token=TOKEN)
    assert creds.credential_type == "youtrust_api_token"
    assert native.YoutrustAPITokenCredential.model_fields["credential_type"].is_required() is False
    assert native.YoutrustNode.connection_evidence.operation == "list_contacts"
    for value in ["", "Bearer abc", "https://example.com/token"]:
        with pytest.raises((ValueError, ValidationError)):
            native.YoutrustAPITokenCredential(api_token=value)
