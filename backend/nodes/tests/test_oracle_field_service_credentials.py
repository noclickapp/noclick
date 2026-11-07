"""Field Service saved credentials use staging's canonical credential loader."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nodes import oracle_field_service_node as p
from nodes.core.registry import NodeFactory

KEY = {"credential_type": "oracle_field_service_basic", "instance_name": "fixture-env",
       "auth_instance_name": "Fixture.test", "client_id": "fixture-app", "client_secret": "synthetic-secret"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def loader(monkeypatch):
    result = AsyncMock(return_value=deepcopy(KEY))
    monkeypatch.setattr(p, "resolve_credential_with_owner_fallback", result)
    return result


@pytest.mark.asyncio
async def test_saved_credentials_use_canonical_runner_org_workflow_resolution(loader):
    pool = object()
    fresh = await p.OracleFieldServiceNode._load_credential(
        KEY, credential_id="saved", user_id="runner", organization_id="org",
        workflow_id="workflow", pool=pool)
    loader.assert_awaited_once_with("saved", "runner", pool, org_id="org", workflow_id="workflow")
    assert fresh["client_id"] == KEY["client_id"]
    await fresh["_ofsc_reader"].read()
    assert loader.await_count == 2


@pytest.mark.asyncio
async def test_saved_id_without_caller_never_uses_cached_pair(loader):
    node = NodeFactory.create_node("fixture", "automation-oracle-field-service", {
        "config": {"operation": "list_resources"}, "credentials": KEY, "credential_id": "saved"})
    with pytest.raises(ValueError, match="require a caller"):
        await node.execute({})
    loader.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {"credential_type": "foreign_provider"}, {**KEY, "client_secret": ""}])
async def test_unavailable_revoked_foreign_or_invalid_saved_credentials_fail(loader, data):
    loader.return_value = data
    with pytest.raises(ValueError):
        await p.OracleFieldServiceNode.freshen_credential(KEY, credential_id="saved", user_id="runner")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"instance_name": "other-env"}, {"auth_instance_name": "Other.test"},
    {"client_id": "replacement"}, {"client_secret": "replacement"}])
async def test_reader_rejects_changed_deployment_or_grant(loader, change):
    reader = p.Reader("saved", "runner")
    await reader.read()
    loader.return_value.update(change)
    with pytest.raises(ValueError, match="changed during"):
        await reader.read()


@pytest.mark.asyncio
async def test_cached_credential_cannot_replace_current_saved_grant(loader):
    loader.return_value["instance_name"] = "other-env"
    with pytest.raises(ValueError, match="cached credential changed"):
        await p.OracleFieldServiceNode.freshen_credential(KEY, credential_id="saved", user_id="runner")


@pytest.mark.asyncio
async def test_reader_rechecks_revocation_after_initial_load(loader):
    reader = p.Reader("saved", "runner")
    await reader.read()
    loader.return_value = None
    with pytest.raises(ValueError, match="unavailable or revoked"):
        await reader.read()


@pytest.mark.asyncio
async def test_supplied_credentials_need_no_saved_loader(loader):
    fresh = await p.OracleFieldServiceNode.freshen_credential(KEY)
    assert fresh["client_id"] == KEY["client_id"] and "_ofsc_reader" not in fresh
    loader.assert_not_awaited()
