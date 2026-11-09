"""Offline requests through the real factory; no provider account is needed."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import cert_seal_node as cs
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "cert_seal_api_key", "api_key": "csk_live_fixture_not_a_real_key"}
RECIPIENT = {"id": "r1", "batchId": "b1", "data": {}, "emailStatus": "pending", "createdAt": "2026-04-12T00:00:00Z"}
BATCH = {"id": "b1", "workspaceId": "w1", "title": "2026 Spring Cohort", "designId": "d1", "recipientCount": 1, "archivedAt": None, "createdAt": "2026-04-12T00:00:00Z", "updatedAt": "2026-04-12T00:00:00Z"}
PAGE = {"nextCursor": "opaque-next", "hasMore": True}
CERT = {"recipient": RECIPIENT, "batch": {"id": "b1", "title": BATCH["title"]}, "design": {"id": "d1", "name": "Graduation", "templateJson": {}}, "variables": {"name": "Jane Doe"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "services.certseal.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(cs, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **config):
    node = NodeFactory.create_node(node_id="fixture", node_type="automation-cert-seal",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})
    return await node.execute({})


CASES = [
    ("list_batches", {"status": "all", "cursor": "opaque previous", "limit": 10}, "GET", "/batches", 200, {"batches": [BATCH], "pagination": PAGE}),
    ("create_batch", {"title": "2026 Spring Cohort", "design_id": "d1", "email_template_id": "e1", "course_name": "Advanced TypeScript", "issuer_name": "Acme Academy"}, "POST", "/batches", 201, {"batch": BATCH}),
    ("get_batch", {"batch_id": "b1"}, "GET", "/batches/b1", 200, {"batch": BATCH}),
    ("archive_batch", {"batch_id": "b1"}, "POST", "/batches/b1/archive", 200, {"batch": BATCH}),
    ("unarchive_batch", {"batch_id": "b1"}, "POST", "/batches/b1/unarchive", 200, {"batch": BATCH}),
    ("list_recipients", {"batch_id": "b1", "email_status": "sent"}, "GET", "/batches/b1/recipients", 200, {"recipients": [RECIPIENT], "pagination": PAGE}),
    ("create_recipient", {"batch_id": "b1", "name": "Jane Doe", "email": "jane@example.com", "issue_date": "2026-04-12", "data": {"score": "94%"}, "send": True}, "POST", "/batches/b1/recipients", 201, {"recipient": RECIPIENT}),
    ("create_recipients_bulk", {"batch_id": "b1", "recipients": [{"name": "Jane Doe", "email": "jane@example.com"}], "send": True}, "POST", "/batches/b1/recipients/bulk", 201, {"recipients": [RECIPIENT], "created": 1}),
    ("get_recipient", {"batch_id": "b1", "recipient_id": "r1"}, "GET", "/batches/b1/recipients/r1", 200, {"recipient": RECIPIENT}),
    ("update_recipient", {"batch_id": "b1", "recipient_id": "r1", "name": "Jane S. Doe", "email": None}, "PATCH", "/batches/b1/recipients/r1", 200, {"recipient": RECIPIENT}),
    ("delete_recipient", {"batch_id": "b1", "recipient_id": "r1"}, "DELETE", "/batches/b1/recipients/r1", 200, {"ok": True}),
    ("send_recipient", {"batch_id": "b1", "recipient_id": "r1"}, "POST", "/batches/b1/recipients/r1/send", 202, {"recipient": {**RECIPIENT, "emailStatus": "queued"}}),
    ("revoke_recipient", {"batch_id": "b1", "recipient_id": "r1", "reason": "Issued in error"}, "POST", "/batches/b1/recipients/r1/revoke", 200, {"recipient": RECIPIENT}),
    ("reinstate_recipient", {"batch_id": "b1", "recipient_id": "r1"}, "POST", "/batches/b1/recipients/r1/reinstate", 200, {"recipient": RECIPIENT}),
    ("get_certificate_by_code", {"certificate_id": "CERT-2026-003843-K7M2QXHP"}, "GET", "/certificates/CERT-2026-003843-K7M2QXHP", 200, CERT),
    ("get_certificate_by_token", {"share_token": "opaque-share-token"}, "GET", "/certificates/by-token/opaque-share-token", 200, CERT),
    ("list_designs", {}, "GET", "/designs", 200, {"designs": [], "pagination": PAGE}),
]


@pytest.mark.parametrize("operation,config,method,path,status,payload", CASES, ids=[x[0] for x in CASES])
async def test_cert_seal_contract(transport, operation, config, method, path, status, payload):
    requests, replies = transport
    replies.append((status, payload))
    result = await run(operation, **config)
    assert result == {"status": "success", **payload}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    if operation == "list_batches":
        assert dict(request.url.params) == {"status": "all", "cursor": "opaque previous", "limit": "10"}
    elif operation == "list_recipients":
        assert dict(request.url.params) == {"emailStatus": "sent", "limit": "25"}
    elif operation == "create_batch":
        assert json.loads(request.content) == {"title": config["title"], "designId": "d1", "emailTemplateId": "e1", "courseName": "Advanced TypeScript", "issuerName": "Acme Academy"}
    elif operation == "create_recipient":
        assert json.loads(request.content) == {"name": "Jane Doe", "email": "jane@example.com", "issueDate": "2026-04-12", "data": {"score": "94%"}, "send": True}
    elif operation == "create_recipients_bulk":
        assert json.loads(request.content) == {"recipients": [{"name": "Jane Doe", "email": "jane@example.com"}], "send": True}
    elif operation == "update_recipient":
        assert json.loads(request.content) == {"name": "Jane S. Doe", "email": None}
    elif operation == "revoke_recipient":
        assert json.loads(request.content) == {"reason": "Issued in error"}
    else:
        assert not request.content


@pytest.mark.parametrize("status,error", [(401, "Invalid API key"), (409, "Batch is archived; unarchive it before modifying recipients."), (429, "Rate limit exceeded. Retry after 30 seconds.")])
async def test_cert_seal_provider_errors_are_verbatim_without_retry(transport, status, error):
    requests, replies = transport
    replies.append((status, {"error": "ERROR", "message": error}))
    with pytest.raises(ValueError, match=error):
        await run("send_recipient", batch_id="b1", recipient_id="r1")
    assert len(requests) == 1


async def test_cert_seal_bad_success_shape(transport):
    transport[1].append((200, {"batches": None}))
    with pytest.raises(ValueError, match="unexpected list"):
        await run("list_batches")


async def test_cert_seal_identifiers_cannot_change_the_route(transport):
    transport[1].append((200, {"batch": BATCH}))
    await run("get_batch", batch_id="x/y?z#fragment")
    assert transport[0][0].url.raw_path == b"/api/v1/batches/x%2Fy%3Fz%23fragment"
    with pytest.raises(ValueError):
        await run("get_batch", batch_id="..")
    assert len(transport[0]) == 1


def test_cert_seal_manual_credential_and_constraints():
    assert cs.CertSealAPIKey(api_key="  csk_live_fixture  ").model_dump() == {"credential_type": "cert_seal_api_key", "api_key": "csk_live_fixture"}
    for key in ("Bearer abc", "https://example.com/token"):
        with pytest.raises(ValueError):
            cs.CertSealAPIKey(api_key=key)
    with pytest.raises(ValidationError):
        cs.CreateRecipientsBulk(batch_id="b1", recipients=[])
    with pytest.raises(ValidationError):
        cs.RevokeRecipient(batch_id="b1", recipient_id="r1", reason="x" * 501)


@pytest.mark.parametrize("status,payload,reachable", [
    (200, {"batches": [BATCH], "pagination": PAGE}, True),
    (401, {"error": "INVALID_API_KEY", "message": "Invalid API key"}, False),
    (429, {"error": "RATE_LIMITED", "message": "Rate limit exceeded. Retry after 30 seconds."}, None),
])
async def test_cert_seal_connect_evidence(transport, monkeypatch, status, payload, reachable):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    async def admitted_operation(**kwargs):
        assert kwargs["operation"] == "list_batches" and kwargs["credential_data"] == AUTH
        return await run(kwargs["operation"], **kwargs["arguments"])
    monkeypatch.setattr(run_op, "run_node_operation", admitted_operation)
    transport[1].append((status, payload))
    result = await collect_evidence(node_type="automation-cert-seal", user_id="fixture", credential_data=AUTH)
    assert result.reachable is reachable
    if reachable is True:
        assert result.samples[0].label == BATCH["title"]
    elif reachable is False:
        assert result.error == "Invalid API key (HTTP 401)"
    assert len(transport[0]) == 1
