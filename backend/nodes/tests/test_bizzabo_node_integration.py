"""Bizzabo with staging's canonical credential resolver and connect hooks."""
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from nodes import bizzabo_node as B
from nodes.tests.test_bizzabo_node_mock import AUTH, TOKEN, USER, args, world
CID = '00000000-0000-4000-8000-000000000042'
ORG = '00000000-0000-4000-8000-000000000003'
WF = '00000000-0000-4000-8000-000000000004'

@pytest.mark.asyncio
async def test_saved_credential_uses_canonical_workflow_resolver(monkeypatch, world):
    pool = object()
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    data = await B.bound_credential(AUTH, pool=pool, user_id=USER, credential_id=CID, organization_id=ORG, workflow_id=WF)
    assert (await B.records(data, args('get_account')))['account_id'] == '42'
    assert resolve.await_count >= 4
    for call in resolve.await_args_list:
        assert call.args == (CID, USER, pool)
        assert call.kwargs == {'org_id': ORG, 'workflow_id': WF}
    assert TOKEN not in str(dict(data))

@pytest.mark.asyncio
@pytest.mark.parametrize('changed', [None, {**AUTH, 'credential_type': 'slack_oauth'}, {**AUTH, 'client_secret': 'changed-client-secret'}, {**AUTH, 'account_id': '43'}])
async def test_saved_access_or_binding_change_during_grant_refuses_api(monkeypatch, world, changed):
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    data = await B.bound_credential(AUTH, pool=object(), user_id=USER, credential_id=CID)
    world.after_request = lambda req: setattr(resolve, 'return_value', changed)
    with pytest.raises(ValueError, match='current authority or public-origin policy refused'):
        await B.records(data, args('get_account'))
    assert [r.url.path for r in world.calls] == ['/oauth/token']
    assert data.token is None

@pytest.mark.asyncio
async def test_bound_credential_cannot_be_flattened_or_used_without_actor(monkeypatch, world):
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', AsyncMock(return_value=deepcopy(AUTH)))
    data = await B.bound_credential(AUTH, pool=object(), user_id=USER, credential_id=CID)
    with pytest.raises(ValueError, match='authority was lost'): await B.records(dict(data), args('get_account'))
    with pytest.raises(ValueError, match='authorized principal'): await B.bound_credential(AUTH, credential_id=CID)
    assert world.calls == []

@pytest.mark.asyncio
async def test_execute_honors_credential_ids_mapping(monkeypatch, world):
    from nodes.core.registry import NodeFactory
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    monkeypatch.setattr('utils.database_pool.get_native_pool', lambda: object())
    node = NodeFactory.create_node(node_id='fixture', node_type=B.NODE_TYPE, node_data={'config': args('get_account'), 'credentials': AUTH, 'credentialIds': {B.FAMILY: CID}}, sio=None, sid=None, user_id=USER)
    assert (await node.execute({}))['identity_verified'] is True
    assert resolve.await_args.args[:2] == (CID, USER)

@pytest.mark.asyncio
async def test_freshen_hook_resolves_current_actor_org(monkeypatch, world):
    from types import SimpleNamespace
    class Conn:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
    pool = SimpleNamespace(acquire=lambda: Conn())
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    monkeypatch.setattr('repositories.organization.OrgRepo.get_primary_org_id', AsyncMock(return_value=ORG))
    monkeypatch.setattr('utils.credentials.resolve_credential_with_owner_fallback', resolve)
    data = await B.BizzaboNode.freshen_credential(AUTH, pool=pool, user_id=USER, credential_id=CID)
    assert isinstance(data, B._BoundCredential)
    assert resolve.await_args.kwargs == {'org_id': ORG, 'workflow_id': None}
    assert world.calls == []

@pytest.mark.asyncio
@pytest.mark.parametrize('status,valid', [(200, True), (401, False), (403, False), (500, None)])
async def test_staging_connect_hook_checks_protected_account(world, status, valid):
    world.status = status
    result = await B.BizzaboNode.validate_credential_access(AUTH)
    assert result['valid'] is valid
    assert AUTH['client_secret'] not in str(result) and TOKEN not in str(result)
    assert [r.url.path for r in world.calls] == ['/oauth/token', '/v1/account']

def test_factory_refuses_foreign_raw_family_and_schema_has_no_fake_oauth(world):
    from nodes.core.registry import NodeFactory
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id='fixture', node_type=B.NODE_TYPE, node_data={'config': args('get_account'), 'credentials': {**AUTH, 'credential_type': 'slack_oauth'}}, sio=None, sid=None, user_id=USER)
    assert B.BizzaboNode.validate_config({'config': args('get_account'), 'credentials': {**AUTH, 'credential_type': 'slack_oauth'}})['valid'] is False
    schema = B.BizzaboNode.get_config_schema()['$defs']['BizzaboClientCredentialsCredential']
    assert schema['properties']['credential_type']['const'] == B.FAMILY
    assert schema['properties']['client_secret']['ui:sensitive'] is True
    assert not schema.get('x-oauth-provider')
