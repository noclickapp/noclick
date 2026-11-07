"""Responsys integration with staging's credential and connection seams."""
from unittest.mock import AsyncMock

import pytest

from nodes.core import connection_evidence as ce, credential_connect as cc, run_op
from tests.test_responsys_node import CID, ENDPOINT, TOKEN, USER, credential, node, transport  # noqa: F401


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_stored_run_and_collector_stop_at_admission(monkeypatch, transport, status):
    from repositories.credential_approvals import CredentialApprovalRepo
    resolve = AsyncMock(return_value=credential())
    monkeypatch.setattr(run_op, "resolve_operation_credential", resolve)
    admit = AsyncMock(return_value={"id": CID, "status": status, "new_request": False})
    monkeypatch.setattr(CredentialApprovalRepo, "admit", admit)
    kwargs = dict(node_type="automation-responsys", credential_id=CID, user_id=USER, pool=object())
    result = await run_op.run_node_operation(**kwargs, operation="list_folders", arguments={})
    assert result["executed"] is False and result["_halt_downstream"] is True
    assert admit.call_args.kwargs["operation"] == "list_folders"
    assert admit.call_args.kwargs["arguments"] == {"limit": 200, "offset": 0}
    evidence = await ce.collect_evidence(**kwargs)
    assert evidence.reachable is None and not evidence.samples and evidence.account_label is None
    assert transport[0] == []


async def test_actual_manual_connect_uses_native_factory_and_account_evidence(monkeypatch, transport):
    _, replies = transport
    replies[("GET", "/rest/api/v1.3/settings/account")] = {"name": "Owned Account", "endpoint": ENDPOINT}
    monkeypatch.setattr(cc, "_collect_evidence", ce.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type="responsys_auth_token", credential_data=credential(), user_id=USER)
    assert verdict.ok and verdict.node_type == "automation-responsys"
    assert verdict.evidence.reachable is True
    assert any(sample.label == "Owned Account" for sample in verdict.evidence.samples) or verdict.evidence.account_label == "Owned Account"
    assert node("get_account_settings").connection_evidence.proves == "account"


@pytest.mark.parametrize("persisted", [True, False])
async def test_successor_uses_staging_loader_and_versioned_update(monkeypatch, transport, persisted):
    from utils import credential_loader, credentials

    load = AsyncMock(return_value=credential(token_version=3))
    save = AsyncMock(return_value=(int(persisted), None))
    monkeypatch.setattr(credential_loader, "load_credential", load)
    monkeypatch.setattr(credentials, "update_credential_data_detailed", save)
    calls, replies = transport
    successor = "fixture-rotated-token-902"
    replies[("POST", "/rest/api/v1.3/auth/token")] = {"authToken": successor, "endPoint": ENDPOINT, "issuedAt": "1464258268624"}
    n = node("refresh_auth_token", selected=True)
    if persisted:
        result = await n.execute({})
        assert result["data"] == {"refreshed": True, "persisted": True}
        assert calls[-1].headers["Authorization"] == successor
    else:
        with pytest.raises(ValueError, match="persistence lost"):
            await n.execute({})
        assert all(r.method != "GET" for r in calls)
    load.assert_awaited_once_with(None, USER, CID, raise_on_error=True)
    assert save.call_args.kwargs["expected_token_version"] == 3
    assert save.call_args.kwargs["expected_credential_type"] == "responsys_auth_token"
    assert save.call_args.kwargs["new_data"]["auth_token"] == successor
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert calls[0].headers["Authorization"] == TOKEN
    assert calls[0].content == b"auth_type=token"
