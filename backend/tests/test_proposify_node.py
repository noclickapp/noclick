"""Native factory/admission/collector, V3 parent and ack fixtures."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup
from nodes.core.connection_evidence import collect_evidence
from nodes.proposify_node import ProposifyNode, _credential

TYPE = "automation-proposify"
USER = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"
DOC = "33333333-3333-4333-8333-333333333333"
TEMPLATE = "44444444-4444-4444-8444-444444444444"
EVENT = "55555555-5555-4555-8555-555555555555"
RAW = {"credential_type": "proposify_issued_token", "access_token": "synthetic-proposify-issued-token", "token_type": "Bearer", "scopes": ["read_users", "read_templates", "read_documents", "write_documents"], "client_id": "synthetic-client", "expected_account_id": 71}
DOCUMENT = {"id": DOC, "name": "Fixture draft", "status": "DRAFT", "is_locked": False, "account": {"id": 71}, "data": {"price": 100, "person_id": "PRIVATE-PERSON", "sent_at": "PRIVATE-SENT"}, "signing_url": "https://attacker.invalid/PRIVATE"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.url.scheme == "https" and request.url.host == "connect.proposify.com"
        assert request.headers["Authorization"] == f"Bearer {RAW['access_token']}"
        assert RAW["access_token"] not in str(request.url) and not request.url.params
        default = {"/user": {"data": [{"id": 31, "title": "Fixture role", "email": "PRIVATE-EMAIL", "first_name": "PRIVATE-NAME"}]}, "/template": {"data": [{"id": 41.0, "name": "Legacy fixture"}]}, "/v3/content/Document": {"data": [DOCUMENT]}, "/v3/content/Template": {"data": [{**DOCUMENT, "id": TEMPLATE}]}, f"/v3/document/{DOC}": DOCUMENT, "/v3/document": {"eventId": EVENT, "contentId": DOC}}
        reply = replies.get((request.method, request.url.path), (202 if request.method == "POST" else 200, b"" if request.method == "PATCH" else default.get(request.url.path)))
        if isinstance(reply, Exception): raise reply
        status, payload = reply
        return httpx.Response(status, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.proposify_node.guarded_async_client", client)
    return calls, replies


async def run(operation, credential=None, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW if credential is None else credential), user_id=USER)


@pytest.mark.asyncio
async def test_real_factory_and_empty_protected_collection_do_not_invent_identity(transport):
    calls, replies = transport
    replies[("GET", "/v3/content/Document")] = (200, {"data": []})
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "check_connection", "label": "Fixture", "disabled": False}}, user_id=USER)
    result = await node.execute({})
    assert result["principal_identity_proven"] is False and result["account_binding_verified"] is False
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and not evidence.account_label and not evidence.samples
    assert "PRIVATE" not in json.dumps(asdict(evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": [{"id": "legacy41"}]}, {"data": [{**DOCUMENT, "account": {"id": 72}}]}])
async def test_malformed_or_foreign_protected_data_is_unknown_not_false_proof(transport, payload):
    _, replies = transport
    replies[("GET", "/v3/content/Document")] = (200, payload)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is None and not evidence.account_label


@pytest.mark.asyncio
async def test_id_namespaces_closed_metadata_and_actual_uuid_picker(transport, monkeypatch):
    calls, _ = transport
    legacy = await run("list_legacy_templates")
    assert legacy["data"] == [{"id": 41, "name": "Legacy fixture"}] and legacy["id_namespace"] == "legacy_numeric"
    current = await run("get_v3_document", document_id=DOC)
    assert current["data"]["account_id"] == 71 and "PRIVATE" not in json.dumps(current) and "price" not in current["data"]
    users = await run("list_users")
    assert users["data"] == [{"id": 31, "title": "Fixture role"}]
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value=deepcopy(RAW)))
    monkeypatch.setattr("utils.credential_approval.admit_lookup", AsyncMock(return_value=None))
    freshen = AsyncMock(return_value=deepcopy(RAW))
    monkeypatch.setattr(ProposifyNode, "freshen_credential", freshen)
    lookup = await run_node_lookup(node_type=TYPE, field_name="template_id", credential_id=KEY, user_id=USER)
    freshen.assert_awaited_once()
    assert lookup["options"][0]["value"] == TEMPLATE and lookup["next_page_token"] is None
    with pytest.raises(ValueError): await ProposifyNode.load_field_options("template_id", RAW, page_token="2")


@pytest.mark.asyncio
async def test_create_exact_draft_body_and_202_is_pending_not_completed(transport):
    calls, _ = transport
    result = await run("create_draft_document_from_template", name="Disposable draft", template_id=TEMPLATE, new_document_id=DOC)
    assert [r.url.path for r in calls] == ["/v3/content/Template", "/v3/document"]
    assert json.loads(calls[-1].content) == {"name": "Disposable draft", "fromTemplateId": TEMPLATE, "id": DOC, "content": {"status": "DRAFT"}}
    assert result["data"] == {"eventId": EVENT, "contentId": DOC} and result["pending"] is True and result["document_state_confirmed"] is False
    assert len(calls) == 2  # no invented event-status poll


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"Updated", b'{"private":"discarded"}'])
async def test_patch_200_has_no_invented_body_and_soft_delete_is_patch(transport, body):
    calls, replies = transport
    replies[("PATCH", f"/v3/document/{DOC}")] = (200, body)
    result = await run("rename_draft_document", document_id=DOC, name="Renamed fixture")
    assert result["data"] is None and result["document_state_confirmed"] is False
    assert json.loads(calls[-1].content) == {"name": "Renamed fixture"}
    deleted = await run("soft_delete_draft_document", document_id=DOC)
    assert deleted["soft_delete_acknowledged"] is True and deleted["deletion_verified"] is False
    assert calls[-1].method == "PATCH" and json.loads(calls[-1].content) == {"is_deleted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"status": "ACTIVE"}, {"is_locked": True}, {"id": TEMPLATE}, {"account": {"id": 72}}, {"is_locked": None}])
async def test_exact_editable_draft_account_precedes_any_mutation(transport, change):
    calls, replies = transport
    replies[("GET", f"/v3/document/{DOC}")] = (200, {**DOCUMENT, **change})
    assert (await run("soft_delete_draft_document", document_id=DOC))["status"] == "error"
    assert len(calls) == 1 and calls[0].method == "GET"


@pytest.mark.asyncio
async def test_actual_read_write_scopes_and_account_prerequisite_before_http(transport):
    calls, _ = transport
    result = await run("create_draft_document_from_template", credential={**RAW, "expected_account_id": None}, name="Fixture", template_id=TEMPLATE)
    assert result["executed"] is False and not calls
    result = await run("create_draft_document_from_template", credential={**RAW, "scopes": ["read_documents"]}, name="Fixture", template_id=TEMPLATE)
    assert result["executed"] is False and not calls


@pytest.mark.parametrize("change", [{"credential_type": "other_oauth"}, {"token_type": None}, {"scopes": ["write_documents"]}, {"scope": "read_documents"}, {"refresh_token": ""}, {"base_url": "https://attacker.invalid"}, {"expires_at": 0}])
def test_authoritative_family_and_issued_only_grant_precede_defaults(change):
    with pytest.raises(ValueError): _credential({**RAW, **change})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(403, {"message": "PRIVATE"}), (429, {"message": RAW["access_token"]}), (200, {}), (202, {"eventId": EVENT})])
async def test_create_error_or_malformed_ack_never_echoes_retries_or_claims_complete(transport, status, payload):
    calls, replies = transport
    replies[("POST", "/v3/document")] = (status, payload)
    result = await run("create_draft_document_from_template", name="Fixture", template_id=TEMPLATE)
    assert result["status"] == "error" and "data" not in result and len(calls) == 2
    assert "PRIVATE" not in json.dumps(result) and RAW["access_token"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_known_expiry_and_ambiguous_write_no_retry(transport):
    calls, replies = transport
    assert (await run("list_users", credential={**RAW, "expires_at": "2020-01-01T00:00:00Z"}))["executed"] is False and not calls
    replies[("POST", "/v3/document")] = httpx.ReadTimeout("PRIVATE")
    result = await run("create_draft_document_from_template", name="Fixture", template_id=TEMPLATE)
    assert result["mutation_outcome_unknown"] is True and len(calls) == 2
