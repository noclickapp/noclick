"""Qovery uses staging's common credential resolver, with a per-call binding."""
from unittest.mock import AsyncMock

import pytest

from nodes import qovery_node as p
from utils import credentials

KEY = {
    "credential_type": "qovery_api_token",
    "organization_id": "66666666-6666-4666-8666-666666666666",
    "api_token": "synthetic-machine-token",
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
async def test_saved_credential_uses_common_workflow_and_org_resolution(monkeypatch):
    pool = object()
    resolve = AsyncMock(return_value=KEY)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolve)
    fresh = await p.QoveryNode._freshen_credential(
        KEY, pool=pool, user_id="runner", credential_id="connection",
        workflow_id="workflow", organization_id="organization",
    )
    resolve.assert_awaited_once_with(
        "connection", "runner", pool, org_id="organization", workflow_id="workflow",
    )
    assert p.guard(fresh).model_dump() == KEY
    assert await fresh["_qovery_reader"].read() == p.guard(KEY)


@pytest.mark.asyncio
async def test_saved_credential_requires_caller_and_never_falls_back_to_cached_token(monkeypatch):
    resolve = AsyncMock(return_value=None)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolve)
    with pytest.raises(ValueError, match="require a caller"):
        await p.current("connection", None, pool=object())
    resolve.assert_not_awaited()
    with pytest.raises(ValueError, match="unavailable"):
        await p.QoveryNode.freshen_credential(KEY, pool=object(), user_id="runner", credential_id="connection")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"api_token": "replacement"}, {"organization_id": "77777777-7777-4777-8777-777777777777"}])
async def test_reader_rejects_changed_token_or_authorized_organization(monkeypatch, change):
    resolve = AsyncMock(return_value=dict(KEY))
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolve)
    reader = p.Reader("connection", "runner", pool=object())
    await reader.read()
    resolve.return_value = {**KEY, **change}
    with pytest.raises(ValueError, match="changed during"):
        await reader.read()
    with pytest.raises(ValueError, match="cached credential changed"):
        await p.QoveryNode.freshen_credential(KEY, pool=object(), user_id="runner", credential_id="connection")


@pytest.mark.asyncio
async def test_reader_rejects_revoked_access_or_wrong_provider(monkeypatch):
    resolve = AsyncMock(return_value=KEY)
    monkeypatch.setattr(credentials, "resolve_credential_with_owner_fallback", resolve)
    reader = p.Reader("connection", "runner", pool=object())
    await reader.read()
    resolve.return_value = None
    with pytest.raises(ValueError, match="unavailable"):
        await reader.read()
    resolve.return_value = {**KEY, "credential_type": "other_provider"}
    with pytest.raises(ValueError, match="typed Qovery"):
        await reader.read()
