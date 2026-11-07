"""Actual connect, admission, factory and current-row authority regressions."""
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from nodes import vectara_node as v
from nodes.core import connection_evidence as ce, credential_connect as cc
from nodes.core.registry import NodeFactory
from nodes.vectara_node import VectaraAuthorityRepo
from repositories.organization import OrgRepo
from repositories.credential_approvals import CredentialApprovalRepo
from tests.test_vectara_node import transport, CORPUS, KEY

CID = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
BLOB = {"credential_type": v.FAMILY, "api_key": KEY, "corpus_key": "owned"}


async def test_real_connect_uses_bound_read_and_never_claims_account_identity(monkeypatch, transport):
    cc._class_index.cache_clear()
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    transport[1].append((200, CORPUS))
    verdict = await cc.validate_for_connect(credential_type=v.FAMILY, credential_data=BLOB, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert v.VectaraNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.account_label is None
    assert transport[0][0][1] == v.API + "/corpora/owned"
    assert KEY not in str(verdict.evidence)


@pytest.mark.parametrize("status,hint", [(401,"rejected"),(403,"permissions")])
async def test_real_connect_preserves_auth_vs_permission_rejections(monkeypatch, transport, status, hint):
    cc._class_index.cache_clear()
    monkeypatch.setattr(cc,"_collect_evidence",ce.collect_evidence)
    transport[1].append((status,{"raw_provider_secret":KEY}))
    verdict=await cc.validate_for_connect(credential_type=v.FAMILY,credential_data=BLOB,user_id=USER)
    assert not verdict.ok and verdict.evidence.reachable is False
    assert hint in verdict.hint and KEY not in verdict.rejection


@pytest.fixture
def current(monkeypatch):
    row = {"id": CID, "owner_id": USER, "credential_type": v.FAMILY,
           "credential": dict(BLOB), "metadata": {}, "revoked_at": None,
           "token_version": 1, "updated_at": "fixture-version-1"}
    calls = []
    class Connection:
        async def fetchrow(self, sql, *args):
            calls.append((sql, args)); return deepcopy(row)
    class Pool:
        @asynccontextmanager
        async def acquire(self): yield Connection()
    pool = Pool()
    async def primary(self, conn, user): return None
    async def admitted(self, **kwargs): return None
    class Encryption:
        def decrypt_credential(self, value): return dict(value)
    import utils.database_pool as db
    import utils.encryption as encryption
    monkeypatch.setattr(db, "get_native_pool", lambda: pool)
    monkeypatch.setattr(encryption, "get_encryption", lambda: Encryption())
    monkeypatch.setattr(OrgRepo, "get_primary_org_id", primary)
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admitted)
    return row, calls


def saved(**extra):
    return NodeFactory.create_node("saved", "automation-vectara", {
        "config": {"operation": "get_corpus"}, "credentialIds": {v.FAMILY: CID},
        "credentials": {**BLOB, **extra}, "_approval_pool": object(),
    }, user_id=USER)


async def test_actual_repository_and_current_row_win_stale_attached_key(current, transport):
    current[0]["credential"]["api_key"] = "current-native-fixture-key"
    transport[1].append((200, CORPUS))
    result = await saved().run({})
    assert result["status"] == "success"
    assert transport[0][0][2]["headers"]["x-api-key"] == "current-native-fixture-key"
    sql, args = current[1][0]
    assert "resource_shares" in sql and args == (CID, USER, None)


@pytest.mark.parametrize("change", ["foreign", "revoked", "corpus", "missing"])
async def test_current_family_revoke_parent_and_id_rejections(current, transport, change):
    row = current[0]
    if change == "foreign": row["credential_type"] = "foreign_api_key"
    elif change == "revoked": row["revoked_at"] = "fixture-revoked"
    elif change == "corpus": row["credential"]["corpus_key"] = "other"
    else: row.clear()
    with pytest.raises(v.VectaraError): await saved().run({})
    assert transport[0] == []


async def test_current_version_change_before_acceptance_is_refused(current, transport):
    original = VectaraAuthorityRepo.accessible
    count = 0
    async def change(self, *args):
        nonlocal count
        count += 1
        if count == 4: current[0]["token_version"] += 1
        return await original(self, *args)
    from unittest.mock import patch
    transport[1].append((200, CORPUS))
    with patch.object(VectaraAuthorityRepo, "accessible", change):
        with pytest.raises(v.VectaraError): await saved().run({})
    assert len(transport[0]) == 1


@pytest.mark.parametrize("creds", [{"api_key": KEY, "corpus_key": "owned"}, {**BLOB, "credential_type": "foreign_api_key"}])
def test_known_selected_rows_require_native_tag_before_common_reconciliation(creds):
    data = {"config": {"operation": "get_corpus"}, "credential_id": CID, "credentials": creds}
    assert v.VectaraNode.validate_config(data)["valid"] is False
    with pytest.raises(ValueError): NodeFactory.create_node("invalid", "automation-vectara", data)
