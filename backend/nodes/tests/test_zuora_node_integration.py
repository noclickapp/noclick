"""Exercise Zuora credential hooks against staging's refresh contract.
The transport fixture retains native token and metadata validation.
"""
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from nodes import zuora_node as F
from nodes.tests.test_zuora_node_mock import AUTH, cached, world, ensure_native_db_pool

@pytest.mark.asyncio
async def test_fresh_token_does_not_mint_again(world):
    result = await F.ZuoraNode.freshen_credential(cached())
    assert result['access_token'] == cached()['access_token']
    assert not world.calls

@pytest.mark.asyncio
async def test_connect_mints_actual_grant_and_probes(world):
    data = deepcopy(AUTH)
    assert (await F.ZuoraNode.validate_credential_access(data))['valid'] is True
    assert data['tenant_id'] == '42'
    assert [r.url.path for r in world.calls] == ['/oauth/token', '/object-query/accounts']

@pytest.mark.asyncio
async def test_saved_refresh_uses_staging_helper(monkeypatch):
    async def fresh(**kwargs):
        assert kwargs['credential_id'] == 'saved-id'
        assert kwargs['refresh_token_key'] == 'client_secret'
        kwargs['credential'].update(cached())
    helper = AsyncMock(side_effect=fresh)
    monkeypatch.setattr(F, 'ensure_fresh_oauth_token', helper)
    result = await F.ZuoraNode.freshen_credential(deepcopy(AUTH), user_id='owner', credential_id='saved-id')
    assert result['tenant_id'] == '42'
    helper.assert_awaited_once()
