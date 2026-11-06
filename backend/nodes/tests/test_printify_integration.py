"""Actual factory/run/connect/current-row/admission seams with local boundaries.

SQL is recorded, never sent to a database. Provider calls are MockTransport.
No real account, entitlement, E2E or publication proof is claimed.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import printify_node as node
from nodes.core import credential_connect, connection_evidence, run_op
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from repositories.credential_approvals import CredentialApprovalRepo
from utils import credentials, ssrf
from wss.handlers import workflow_handler

TOKEN = "fixture-printify-bearer-7de693"
CREDENTIAL = {"credential_type": "printify_pat", "personal_access_token": TOKEN, "brand": "printify"}
CID = "11111111-1111-4111-8111-111111111111"


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
    row = {"credential_type": "printify_pat", "owner_id": "fixture-user", "token_version": 7, "updated_at": datetime(2026, 10, 6, tzinfo=timezone.utc), "approval_revision": 3, "revoked_at": None, "credential": b"local-cipher"}
    calls, sql, state = [], [], {"row": row, "blob": deepcopy(CREDENTIAL), "shops": [{"id": 42, "title": "Fixture merchant shop", "sales_channel": "disconnected"}]}
    async def read(statement, *args):
        sql.append((statement, args))
        return state["row"]
    async def read_types(statement, *args):
        row = await read(statement, *args)
        return [{"id": CID, "credential_type": row["credential_type"]}] if row and row["revoked_at"] is None else []
    conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=read), fetch=AsyncMock(side_effect=read_types))
    pool = Pool(conn)
    monkeypatch.setattr(credentials, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(state["blob"])))
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="fixture-org"))
    admission = AsyncMock(return_value=None)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admission)
    monkeypatch.setattr(ssrf, "assert_url_allowed", AsyncMock())
    monkeypatch.setattr(node, "allow_private_hosts", lambda: False)
    async def provider(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return httpx.Response(200, json=state["shops"])
    actual = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: actual(transport=httpx.MockTransport(provider), **kwargs))
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    return SimpleNamespace(row=row, state=state, sql=sql, pool=pool, calls=calls, admission=admission)


async def test_actual_registration_factory_and_stored_run_resolve_current_token(seams):
    assert NODE_REGISTRY["automation-printify"] is node.PrintifyNode
    instance = NodeFactory.create_node(node_id="fixture", node_type="automation-printify", node_data={"config": {"operation": "list_shops"}, "credentials": {**CREDENTIAL, "personal_access_token": "stale-fixture-token"}, "credential_id": CID, "_approval_pool": seams.pool}, user_id="fixture-user", organization_id="fixture-org")
    result = await instance.run({})
    assert result["data"]["items"][0]["title"] == "Fixture merchant shop"
    assert len(seams.calls) == 1
    seams.admission.assert_awaited_once()
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "list_shops" and args["arguments"] == {}
    assert args["credential_id"] == CID and TOKEN not in repr(args)
    assert any("credential_type" in statement and "revoked_at" in statement for statement, _ in seams.sql)


async def test_typed_unsaved_connect_uses_actual_native_operation_and_injects_hidden_family(seams):
    verdict = await credential_connect.validate_for_connect(credential_type="printify_pat", credential_data={"personal_access_token": " " + TOKEN + " "}, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors == {} and verdict.rejection is None
    assert verdict.credential_data["credential_type"] == "printify_pat"
    assert verdict.evidence.reachable is True and verdict.evidence.samples[0].label == "Fixture merchant shop"
    assert verdict.evidence.account_label is None and verdict.evidence.answers_field is None
    assert seams.admission.await_count == 0 and len(seams.calls) == 1


async def test_empty_shop_connect_does_not_invent_merchant_identity(seams):
    seams.state["shops"] = []
    evidence = await connection_evidence.collect_evidence(node_type="automation-printify", credential_data=CREDENTIAL, user_id="fixture-user")
    assert evidence.reachable is True and evidence.samples == [] and evidence.account_label is None
    assert len(seams.calls) == 1


@pytest.mark.parametrize("credential", [{"personal_access_token": "https://token.example.test"}, {"personal_access_token": "YOUR_API_KEY"}, {"personal_access_token": "has control\ninside"}, {"personal_access_token": TOKEN, "brand": "https://attacker.example.test"}])
async def test_manual_shape_errors_never_call_provider(seams, credential):
    verdict = await credential_connect.validate_for_connect(credential_type="printify_pat", credential_data=credential, user_id="fixture-user", pool=seams.pool)
    assert verdict.field_errors and verdict.evidence is None and seams.calls == []


@pytest.mark.parametrize("kind", [None, "slack_oauth", "api_key"])
async def test_current_authoritative_wrong_family_denies_stale_valid_blob(seams, kind):
    seams.row["credential_type"] = kind
    with pytest.raises(ValueError, match="Current Printify authority"):
        await node.PrintifyNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool)
    assert seams.calls == [] and seams.admission.await_count == 0


@pytest.mark.parametrize("denial", ["absent", "revoked"])
async def test_current_authority_null_or_revocation_precedes_provider(seams, denial):
    if denial == "absent":
        seams.state["row"] = None
    else:
        seams.row["revoked_at"] = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        await node.PrintifyNode.freshen_credential(CREDENTIAL, credential_id=CID, user_id="fixture-user", pool=seams.pool)
    assert seams.calls == []


async def test_real_canonical_picker_and_parent_argument_admission(seams):
    result = await run_op.run_node_lookup(node_type="automation-printify", field_name="shop_id", user_id="fixture-user", credential_id=CID, pool=seams.pool, organization_id="fixture-org")
    assert result["options"] == [{"value": "42", "label": "Fixture merchant shop", "metadata": {}}]
    args = seams.admission.call_args.kwargs
    assert args["operation"] == "__lookup__" and args["arguments"] == {"field_name": "shop_id", "context": None, "page_token": None, "search": None}
    assert len(seams.calls) == 1


async def test_stored_refresh_uses_callers_current_organization(seams):
    result = await node.PrintifyNode.freshen_credential(
        {**CREDENTIAL, "personal_access_token": "stale-fixture-token"},
        credential_id=CID, user_id="fixture-user", pool=seams.pool,
    )
    assert result["personal_access_token"] == TOKEN
    workflow_handler.get_user_org_context.assert_awaited_once_with(seams.pool.conn, "fixture-user")
    assert all(args[2] == "fixture-org" for _, args in seams.sql)
    assert seams.calls == []


async def test_post_connect_validates_through_native_shop_read(seams):
    result = await node.PrintifyNode.validate_credential_access(CREDENTIAL)
    assert result == {"valid": True}
    assert len(seams.calls) == 1
    assert seams.calls[0].url.path == "/v1/shops.json"


async def test_post_connect_expired_token_never_calls_provider(seams):
    result = await node.PrintifyNode.validate_credential_access({
        "credential_type": "printify_oauth_access_token", "brand": "printify",
        "access_token": TOKEN, "expires_at": "2000-01-01T00:00:00+00:00",
    })
    assert result["valid"] is False and "expired" in result["error"]
    assert seams.calls == []
