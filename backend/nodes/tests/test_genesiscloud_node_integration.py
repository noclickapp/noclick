"""Staging factory, connection, credential-resolution and admission seams."""
from unittest.mock import AsyncMock

import pytest

from nodes.core.registry import NodeFactory
from nodes.genesiscloud_node import FAMILY, OPERATIONS, GenesisCloudError, GenesisCloudNode
from nodes.tests.test_genesiscloud_node_mock import INSTANCE, TOKEN, page

ACTOR = '11111111-1111-4111-8111-111111111111'
CID = '22222222-2222-4222-8222-222222222222'


def stored_data():
    return {'credentialIds': {FAMILY: CID}, 'credentials': {'credential_type': FAMILY, 'api_token': TOKEN}, 'config': {'operation': 'list_instances'}}


def test_actual_factory_two_operations_raw_guards_and_pending_references():
    for operation in OPERATIONS:
        data = stored_data(); data['config']['operation'] = operation
        if operation == 'get_instance': data['config']['instance_id'] = INSTANCE
        node = NodeFactory.create_node('n', 'automation-genesiscloud', data, user_id=ACTOR)
        assert isinstance(node, GenesisCloudNode) and node.config.config.operation == operation
    for key, value in [('page', True), ('per_page', '7'), ('include_names', 'false')]:
        data = stored_data(); data['config'][key] = value
        assert GenesisCloudNode.validate_config(data)['valid'] is False
        with pytest.raises(ValueError): GenesisCloudNode.parse_config(data)
    for value in (7, True, 'https://genesiscloud.com/' + INSTANCE, INSTANCE.upper()):
        data = stored_data(); data['config'] = {'operation': 'get_instance', 'instance_id': value}
        assert GenesisCloudNode.validate_config(data)['valid'] is False
        with pytest.raises(ValueError): NodeFactory.create_node('n', 'automation-genesiscloud', data)
    for key, value in [('credential_type', 'foreign'), ('api_token', 7), ('api_token', 'Bearer fixture-token')]:
        data = stored_data(); data['credentials'][key] = value
        with pytest.raises(ValueError): NodeFactory.create_node('n', 'automation-genesiscloud', data)
    data = stored_data(); data['credentials'].pop('credential_type')
    with pytest.raises(ValueError, match='family tag'): NodeFactory.create_node('n', 'automation-genesiscloud', data)
    data = stored_data(); data['config'] = {'operation': 'get_instance', 'instance_id': '{{vars.instance_id}}'}
    assert NodeFactory.create_node('n', 'automation-genesiscloud', data).config.config.instance_id == '{{vars.instance_id}}'
    # A stale field from another operation cannot activate an undocumented route.
    data = stored_data(); data['config']['instance_id'] = 7
    assert NodeFactory.create_node('n', 'automation-genesiscloud', data).config.config.operation == 'list_instances'


@pytest.mark.parametrize('status', ['pending', 'rejected'])
@pytest.mark.asyncio
async def test_stored_evidence_actual_run_op_factory_and_admission_precede_http(monkeypatch, status):
    from nodes.core.connection_evidence import collect_evidence
    import nodes.core.run_op as runner
    import utils.credential_approval as admission
    monkeypatch.setattr(runner, 'resolve_operation_credential', AsyncMock(return_value=stored_data()['credentials']))
    admit = AsyncMock(return_value={'id': CID, 'status': status, 'new_request': False})
    monkeypatch.setattr(admission.CredentialApprovalRepo, 'admit', admit)
    monkeypatch.setattr(GenesisCloudNode, '_request', AsyncMock(side_effect=AssertionError('Pending/rejected cannot request GenesisCloud')))
    evidence = await collect_evidence(node_type='automation-genesiscloud', credential_id=CID, user_id=ACTOR, pool=object())
    assert evidence.reachable is None and not evidence.samples
    assert admit.await_args.kwargs['credential_id'] == CID and admit.await_args.kwargs['operation'] == 'list_instances'


@pytest.mark.asyncio
async def test_actual_manual_connect_protected_catalog_reachability_not_account(monkeypatch):
    from nodes.core.credential_connect import validate_for_connect
    request = AsyncMock(return_value=page([], total_count=0))
    monkeypatch.setattr(GenesisCloudNode, '_request', request)
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={'api_token': TOKEN}, user_id=ACTOR, pool=object())
    assert verdict.ok and verdict.evidence.reachable is True
    assert not verdict.evidence.account_label and request.await_count == 1
    assert request.await_args.args[0] == '/instances'


@pytest.mark.asyncio
async def test_native_saved_map_actual_admission_precedes_execution(monkeypatch):
    import utils.credential_approval as admission
    admit = AsyncMock(return_value={'id': CID, 'status': 'rejected', 'new_request': False})
    monkeypatch.setattr(admission.CredentialApprovalRepo, 'admit', admit)
    monkeypatch.setattr(admission, 'get_native_pool', lambda: object())
    node = NodeFactory.create_node('n', 'automation-genesiscloud', stored_data(), user_id=ACTOR)
    node._request = AsyncMock(side_effect=AssertionError('No HTTP'))
    result = await node.run({})
    assert result['executed'] is False and result['status'] == 'rejected'
    assert admit.await_args.kwargs['credential_id'] == CID
    node._request.assert_not_called()


@pytest.mark.asyncio
async def test_uses_credentials_resolved_by_staging_run_op(monkeypatch):
    import nodes.core.run_op as runner
    import utils.credential_approval as admission
    from nodes.tests.test_genesiscloud_node_mock import transport
    import httpx
    current = {'credential_type': FAMILY, 'api_token': 'current-genesiscloud-token-42'}
    resolve = AsyncMock(return_value=current)
    monkeypatch.setattr(runner, 'resolve_operation_credential', resolve)
    monkeypatch.setattr(admission.CredentialApprovalRepo, 'admit', AsyncMock(return_value=None))
    monkeypatch.setattr(admission, 'get_native_pool', lambda: object())
    def respond(request):
        assert request.headers['Authorization'] == 'Bearer ' + current['api_token']
        return httpx.Response(200, json=page())
    transport(monkeypatch, respond)
    result = await runner.run_node_operation(node_type='automation-genesiscloud', operation='list_instances',
        arguments={}, user_id=ACTOR, pool=object(), credential_id=CID)
    assert result['success'] is True
    resolve.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403])
async def test_connection_evidence_recognizes_provider_auth_rejection(monkeypatch, status):
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(GenesisCloudNode, '_request', AsyncMock(side_effect=GenesisCloudError('Genesis Cloud rejected access.', status)))
    evidence = await collect_evidence(node_type='automation-genesiscloud', user_id=ACTOR,
        credential_data={'credential_type': FAMILY, 'api_token': TOKEN}, pool=object())
    assert evidence.reachable is False
    assert f'HTTP {status}' in evidence.error
