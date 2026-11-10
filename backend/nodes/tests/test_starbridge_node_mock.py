"""Route, wire encoding, failure and poll lifecycle coverage for Starbridge."""
from unittest.mock import AsyncMock
from pathlib import Path
import json
import httpx
import pytest
from nodes.starbridge_node import StarbridgeNode, StarbridgeCredential
from nodes.core.registry import NodeFactory


CONTRACT = json.loads((Path(__file__).parent / "fixtures/starbridge/contract_routes.json").read_text())["operations"]

def node(config):
    return NodeFactory.create_node(node_id='starbridge-test', node_type='automation-starbridge',
        node_data={'config': config, 'credentials': {'credential_type': 'starbridge_api_token', 'api_token': 'test-starbridge-secret'}})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CONTRACT))
async def test_contract_routes(operation, monkeypatch):
    spec = CONTRACT[operation]
    config = {'operation': operation}
    for p in spec['parameters']:
        if p.get('required'):
            config[p['name']] = ('00000000-0000-4000-8000-000000000001' if p['name'] in {'bridgeId', 'fileId'} else 'sample /id') if p['in'] == 'path' else 'Sample buyer'
    if operation == 'set_bridge_row_status':
        config['newStatus'] = 'Saved'
    n = node(config)
    n._request = AsyncMock(return_value={'contract': 'response'})
    result = await n.execute({})
    args, kwargs = n._request.call_args
    assert args[0] == spec['method']
    expected = spec['path']
    for p in spec['parameters']:
        if p['in'] == 'path':
            expected = expected.replace('{' + p['name'] + '}', '00000000-0000-4000-8000-000000000001' if p['name'] in {'bridgeId', 'fileId'} else 'sample%20%2Fid')
    assert args[1] == expected
    if operation == 'set_bridge_row_status':
        assert kwargs['body'] == {'newStatus': 'Saved'}
    assert result['data'] == {'contract': 'response'}


@pytest.mark.asyncio
async def test_wire_auth_arrays_and_errors(monkeypatch):
    async def request(client, method, url, **kwargs):
        assert url == 'https://dashboard.starbridge.ai/api/external/bridge'
        assert kwargs['headers']['Authorization'] == 'Bearer test-starbridge-secret'
        assert ('filterType', 'RFP,Meeting') in kwargs['params']
        return httpx.Response(401, json={'error': 'private response'}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    with pytest.raises(ValueError, match='HTTP 401') as error:
        await node({'operation': 'list_bridges', 'filterType': ['RFP', 'Meeting']}).execute({})
    assert 'private response' not in str(error.value)
    assert 'test-starbridge-secret' not in str(error.value)


ROW = {'rowId': 'e8471191-58eb-4896-b187-6764bd4e026f', 'bridgeId': 'cc36caa2-f780-4eee-86ef-840fc8c3f450',
       'name': 'School procurement', 'createdAt': '2026-01-01T00:00:00Z', 'updatedAt': '2026-01-02T00:00:00Z',
       'status': 'Processed', 'columns': {}, 'url': 'https://dashboard.starbridge.ai'}


@pytest.mark.asyncio
async def test_poll_baseline_changes_and_agent_context():
    n = node({'operation': 'on_new_or_updated_row', 'bridgeId': ROW['bridgeId']})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changed, output = mutator(state)
        if changed is not None:
            state = changed
        return output
    n._update_node_state = update
    n._request = AsyncMock(return_value={'result': [dict(ROW)], 'totalPages': 1})
    assert (await n.execute({}))['rows'] == []
    assert (await n.execute({}))['rows'] == []
    changed = dict(ROW, updatedAt='2026-01-03T00:00:00Z')
    n._request.return_value = {'result': [changed], 'totalPages': 1}
    out = await n.execute({})
    assert out['rows'] == [changed]
    assert n.trigger_emitted_event(out)
    text = StarbridgeNode.resolve_agent_event(out)['text']
    assert ROW['rowId'] in text and ROW['bridgeId'] in text and ROW['name'] in text
    assert (await n.execute({}))['rows'] == []
    assert n._request.call_args.kwargs['body']['sorts'] == [{'column': 'rowUpdatedAt', 'direction': 'DESC'}]


def test_manual_credential_default():
    assert StarbridgeCredential(api_token='sb_local_92c873e4').credential_type == 'starbridge_api_token'
