"""Printful manual-token loading against staging credential resolution seams."""
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from nodes.printful_node import PrintfulNode, _credential
from tests.test_printful_node import PRIVATE, OAUTH, USER

CREDENTIAL = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [PRIVATE, OAUTH])
async def test_manual_tokens_validate_without_refresh_or_storage(credential):
    assert await PrintfulNode.freshen_credential(deepcopy(credential)) == _credential(credential)


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [PRIVATE, OAUTH])
async def test_saved_tokens_use_current_family_and_accessible_loader(monkeypatch, credential):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    org = "44444444-4444-4444-8444-444444444444"
    monkeypatch.setattr("wss.handlers.workflow_handler.get_user_org_context", AsyncMock(return_value=org))
    types = AsyncMock(return_value={CREDENTIAL: credential["credential_type"]})
    resolve = AsyncMock(return_value=deepcopy(credential))
    monkeypatch.setattr("utils.credentials.resolve_accessible_credential_types", types)
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolve)
    assert await PrintfulNode.freshen_credential(PRIVATE, pool=pool, user_id=USER, credential_id=CREDENTIAL) == _credential(credential)
    types.assert_awaited_once_with([CREDENTIAL], USER, pool, org)
    resolve.assert_awaited_once_with(CREDENTIAL, USER, pool, org_id=org)


@pytest.mark.asyncio
@pytest.mark.parametrize("family,loaded", [(None, PRIVATE), ("printify_api_key", PRIVATE), (PRIVATE["credential_type"], None), (PRIVATE["credential_type"], OAUTH)])
async def test_saved_tokens_reject_missing_access_and_family_changes(monkeypatch, family, loaded):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("wss.handlers.workflow_handler.get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr("utils.credentials.resolve_accessible_credential_types", AsyncMock(return_value={CREDENTIAL: family}))
    resolve = AsyncMock(return_value=loaded)
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolve)
    with pytest.raises(ValueError):
        await PrintfulNode.freshen_credential(PRIVATE, pool=pool, user_id=USER, credential_id=CREDENTIAL)
    if family not in {PRIVATE["credential_type"], OAUTH["credential_type"]}:
        resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_saved_token_requires_caller():
    with pytest.raises(ValueError, match="authorized caller"):
        await PrintfulNode.freshen_credential(PRIVATE, credential_id=CREDENTIAL)
