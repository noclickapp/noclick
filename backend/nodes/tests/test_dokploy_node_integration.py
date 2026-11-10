"""Dokploy integration with staging's resolver, discovery and credential hooks."""
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from nodes import dokploy_node as D
from nodes.tests.test_dokploy_node_mock import AUTH, USER, args, world


@pytest.mark.asyncio
async def test_supplied_key_freshening_does_not_rotate(world):
    result = await D.DokployNode.freshen_credential(AUTH)
    assert result == AUTH and result is not AUTH
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'key', 'instance', 'user', 'team'])
async def test_staging_resolver_rechecks_saved_credential_before_followup(world, monkeypatch, change):
    current = deepcopy(AUTH)
    resolve = AsyncMock(side_effect=lambda **kwargs: deepcopy(current))
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    authority = dict(credential_id='saved', user_id=USER, pool=object(), org_id=None, workflow_id='workflow')
    bound = D._BoundCredential(AUTH, authority)
    def mutate(_):
        world.after_request = None
        if change == 'missing': current.clear()
        else:
            key = {'key': 'api_key', 'instance': 'instance_url', 'user': 'user_id', 'team': 'organization_id'}[change]
            current[key] = 'https://other.fixture-company.com' if change == 'instance' else 'changed'
    world.after_request = mutate
    with pytest.raises(ValueError):
        await D.records(bound, args('delete_project'))
    assert [r.url.path for r in world.calls] == ['/api/user.get']
    assert all(call.kwargs == authority for call in resolve.call_args_list)


@pytest.mark.asyncio
async def test_execute_passes_staging_authority_context(world, monkeypatch):
    pool = object()
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr('utils.database_pool.get_native_pool', lambda: pool)
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    from nodes.core.registry import NodeFactory
    node = NodeFactory.create_node(node_id='fixture', node_type=D.NODE_TYPE,
        node_data={'config': args('get_current_user'), 'credentials': AUTH, 'credential_id': 'saved'},
        sio=None, sid=None, user_id=USER)
    result = await node.execute({})
    assert result['identity_verified']
    assert resolve.call_args.kwargs == dict(credential_id='saved', user_id=USER, pool=pool, org_id=None, workflow_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected', [(200, True), (401, False), (403, False), (429, None), (500, None)])
async def test_staging_access_validation_tristate(world, status, expected):
    world.status = status
    result = await D.DokployNode.validate_credential_access(AUTH)
    assert result['valid'] is expected
    assert AUTH['api_key'] not in str(result) and 'private-provider' not in str(result)
    assert len(world.calls) == 1


def test_actual_factory_and_public_provisioning_discovery(world, monkeypatch):
    from nodes.core import registry
    from nodes.core.registry import NodeFactory
    from utils import credential_request_routes as routes
    node = NodeFactory.create_node(node_id='fixture', node_type=D.NODE_TYPE, node_data={'config': args('get_current_user'), 'credentials': AUTH}, sio=None, sid=None, user_id=USER)
    assert isinstance(node, D.DokployNode)
    monkeypatch.setattr(registry, 'NODE_REGISTRY', {D.NODE_TYPE: D.DokployNode})
    routes._credential_definition.cache_clear()
    method = routes._get_credential_method(D.FAMILY)
    assert method['credential_type'] == D.FAMILY and method['oauth_provider'] is None
    assert any(field['name'] == 'api_key' for field in method['credential_fields'])
    assert world.calls == []
