"""Veryfi factory, manual connection and staging admission regressions.

Only local repository storage, encryption and remote HTTP are substituted.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import veryfi_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials as credential_storage, ssrf
from wss.handlers import workflow_handler

CREDENTIAL = {"credential_type": node.TYPES[0], "client_id": "fixtureClient", "api_key": "fixture-key", "environment": "production", "client_secret": None}
CID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def ensure_native_db_pool():
    yield


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.fixture
def seams(monkeypatch):
    row = {"credential_type": node.TYPES[0], "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "documents": [{"id": 17, "status": "processed", "ocr_text": "PRIVATE OCR"}]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    pool = Pool(SimpleNamespace(fetchrow=AsyncMock(side_effect=read)))
    monkeypatch.setattr(credential_storage, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        current = node.credential_value(state["blob"])
        assert request.url.path == node.DOCUMENTS and request.method == "GET"
        assert str(request.url).startswith(node.ROOTS[current.environment] + "/")
        assert request.headers["Authorization"] == node.auth_header(current) and request.headers["CLIENT-ID"] == current.client_id
        size = int(request.url.params["page_size"])
        documents = state["documents"]
        return httpx.Response(200, json={"documents": documents, "meta": {"documents_per_page": size, "page_number": 1, "total_pages": 1, "total_results": len(documents)}})
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_factory_runs_through_staging_admission(seams):
    assert NODE_REGISTRY["automation-veryfi"] is node.VeryfiNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-veryfi", node_data={"config": {"operation": "list_documents"}, "credentials": CREDENTIAL, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"]["items"] == [{"id": "17", "status": "processed"}]
    assert seams.admission.call_args.kwargs["operation"] == "list_documents"
    assert len(seams.calls) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_stored_operation_and_collector_park_before_provider(seams, status):
    seams.admission.return_value = {"id": "fixture-approval", "status": status, "new_request": False}
    result = await run_op.run_node_operation(node_type="automation-veryfi", operation="list_documents", arguments={}, user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await connection_evidence.collect_evidence(node_type="automation-veryfi", credential_id=CID, user_id="fixture-user", pool=seams.pool, organization_id="fixture-org")
    assert evidence.reachable is None and evidence.account_label is None and evidence.samples == []
    assert evidence.noun == "Veryfi document IDs" and seams.calls == []


@pytest.mark.parametrize("legacy", [False, True])
async def test_real_manual_connect_shapes_each_family_and_honest_empty_evidence(seams, legacy):
    if legacy:
        seams.state["blob"] = {**CREDENTIAL, "credential_type": node.TYPES[1], "username": "fixture-user"}
    current = seams.state["blob"]
    seams.state["documents"] = []
    raw = {key: value for key, value in current.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=current["credential_type"], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None and verdict.credential_data == current
    assert verdict.evidence.reachable is True and verdict.evidence.account_label is None
    assert len(seams.calls) == 1 and seams.admission.await_count == 0


@pytest.mark.parametrize("change", [{"client_id": ""}, {"environment": "http://local"}, {"api_key": ""}, {"api_key": "Bearer fixture-key"}, {"client_secret": "secret\r\nheader"}])
async def test_actual_manual_connect_auth_errors_have_no_provider_io(seams, change):
    raw = {key: value for key, value in {**CREDENTIAL, **change}.items() if key != "credential_type"}
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=raw, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


async def test_actual_connect_malformed_document_cannot_verified_identity(seams):
    seams.state["documents"] = [{"status": "processed"}]
    verdict = await credential_connect.validate_for_connect(credential_type=node.TYPES[0], credential_data=CREDENTIAL, user_id="fixture-user", pool=seams.pool)
    assert verdict.evidence.reachable is not True and verdict.verified_metadata() == {} and verdict.evidence.account_label is None
    assert len(seams.calls) == 1


@pytest.mark.parametrize("family", node.TYPES)
async def test_key_freshening_uses_staging_hook_and_preserves_family(family):
    credential = {**CREDENTIAL, "credential_type": family}
    if family == node.TYPES[1]:
        credential["username"] = "fixture-user"
    assert await node.VeryfiNode.freshen_credential(credential, credential_id=CID) == credential


async def test_access_validation_probes_provider_and_rejects_auth_failure(seams):
    assert await node.VeryfiNode.validate_credential_access(CREDENTIAL) == {"valid": True}
    assert len(seams.calls) == 1
    seams.state["documents"] = [{"status": "processed"}]
    verdict = await node.VeryfiNode.validate_credential_access(CREDENTIAL)
    assert verdict["valid"] is False
