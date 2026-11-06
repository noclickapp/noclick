"""Aprimo admission and current-row binding regressions."""
import copy
from contextlib import asynccontextmanager

import httpx
import pytest

from nodes.tests.test_aprimo_node_integration import ACTOR, CID, CREDENTIAL, ROOT, make, root, transport


@pytest.mark.asyncio
async def test_saved_native_credential_map_reaches_real_admission_before_transport(monkeypatch):
    from repositories.credential_approvals import CredentialApprovalRepo
    from utils import credential_approval
    calls = []
    async def admit(self, **kwargs):
        calls.append(kwargs)
        return {"id": CID, "status": "pending", "new_request": False}
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admit)
    monkeypatch.setattr(credential_approval, "get_native_pool", lambda: object())
    seen = transport(monkeypatch, lambda r: pytest.fail("Must halt before HTTP"))
    result = await make(saved=True).run({})
    assert result["executed"] is False and seen == []
    assert len(calls) == 1 and calls[0]["credential_id"] == CID.replace("-", "")


class Connection:
    def __init__(self, row): self.row = row; self.queries = []
    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        assert "resource_shares" in query and "credentials c" in query
        return copy.deepcopy(self.row)


class Pool:
    def __init__(self, connection): self.connection = connection
    @asynccontextmanager
    async def acquire(self): yield self.connection


def authority(monkeypatch, *, raw=None, row_changes=None):
    from repositories.organization import OrgRepo
    from utils import database_pool, encryption
    row = {"id": CID, "owner_id": ACTOR, "organization_id": None, "credential_type": "aprimo_bearer", "credential": "opaque-fixture", "token_version": 1, "updated_at": "fixture-version", "metadata": {}, "revoked_at": None, **(row_changes or {})}
    connection = Connection(row); pool = Pool(connection)
    async def primary(self, conn, user): assert user == ACTOR; return None
    class Encryption:
        def decrypt_credential(self, ciphertext): return dict(raw or {**CREDENTIAL, "access_token": "fixture-current-token"})
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", primary)
    monkeypatch.setattr(database_pool, "get_native_pool", lambda: pool)
    monkeypatch.setattr(encryption, "get_encryption", lambda: Encryption())
    return connection


@pytest.mark.asyncio
async def test_actual_repository_current_token_wins_stale_attachment(monkeypatch):
    connection = authority(monkeypatch)
    seen = transport(monkeypatch, lambda r: httpx.Response(200, json=root()))
    result = await make(saved=True).execute({})
    assert result["data"]["id"] == ROOT
    assert all(r.headers["Authorization"] == "Bearer fixture-current-token" for r in seen)
    assert len(connection.queries) >= 3


@pytest.mark.parametrize("row_changes,raw", [
    ({"credential_type": "foreign_bearer"}, None), ({"revoked_at": "revoked"}, None),
    ({"metadata": {"connection_healthy": False}}, None), ({}, {**CREDENTIAL, "credential_type": "foreign_bearer"}),
    ({}, {**CREDENTIAL, "tenant": "other-tenant"}), ({}, {**CREDENTIAL, "classification_id": "e" * 32}),
])
@pytest.mark.asyncio
async def test_foreign_revoked_or_rebound_current_rows_refuse_before_http(monkeypatch, row_changes, raw):
    authority(monkeypatch, row_changes=row_changes, raw=raw)
    seen = transport(monkeypatch, lambda r: pytest.fail("Must refuse transport"))
    with pytest.raises(ValueError): await make(saved=True).execute({})
    assert seen == []


@pytest.mark.asyncio
async def test_current_row_version_change_after_provider_read_refuses_output(monkeypatch):
    connection = authority(monkeypatch)
    def handler(request):
        connection.row["token_version"] = 2
        return httpx.Response(200, json=root())
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="authority changed"):
        await make(saved=True).execute({})


@pytest.mark.asyncio
async def test_missing_current_row_without_workflow_has_no_owner_fallback(monkeypatch):
    connection = authority(monkeypatch); connection.row = None
    seen = transport(monkeypatch, lambda r: pytest.fail("Missing current row must refuse HTTP"))
    with pytest.raises(ValueError, match="missing"):
        await make(saved=True).execute({})
    assert seen == [] and len(connection.queries) == 1


@pytest.mark.asyncio
async def test_actor_change_during_read_refuses_result(monkeypatch):
    node = make()
    def handler(request):
        node.user_id = "33333333-3333-4333-8333-333333333333"
        return httpx.Response(200, json=root())
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="actor"):
        await node.run({})
