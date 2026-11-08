"""Exercise every native operation against provider-authored response examples.

The fixture pins its source contract, while request assertions cover the factory,
authentication, query/body split, pagination and reply envelope independently.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import lagrowthmachine_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _rows_from_operation, _identity_label

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/lagrowthmachine/documented.json').read_text())
TOKEN = 'synthetic-lgm-api-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **changes):
    return NodeFactory.create_node(node_id='lgm-test', node_type='automation-lagrowthmachine',
        node_data={'config': config, 'credentials': {'credential_type': 'lagrowthmachine_api_key', 'api_key': TOKEN, **changes}})


def transport(monkeypatch, response):
    seen = []
    def handle(request):
        seen.append(request)
        return response
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['operation'])
async def test_lagrowthmachine_documented_operations(monkeypatch, case):
    seen = transport(monkeypatch, httpx.Response(200, json=case['response']))
    result = await node(case['config']).execute({})
    assert result == {'status': 'success', 'data': case['response']}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == case['method']
    assert request.url.scheme == 'https' and request.url.host == 'apiv2.lagrowthmachine.com'
    assert request.url.path == '/flow' + case['path']
    assert dict(request.url.params) == {k: str(v) for k, v in case['query'].items()}
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if case['body'] is None:
        assert request.content == b''
    else:
        assert json.loads(request.content) == case['body']
    assert TOKEN not in str(result)


@pytest.mark.parametrize('config', [
    {'operation': 'search_lead'}, {'operation': 'upsert_lead'},
    {'operation': 'search_lead', 'firstname': 'John'},
    {'operation': 'get_campaign', 'campaign_id': '../me'},
    {'operation': 'list_campaigns', 'limit': 26},
    {'operation': 'list_audience_leads', 'audience_id': '64b7f0c2a1d3000000000005', 'skip': -1},
    {'operation': 'update_campaign_status', 'campaign_id': '65a1b2c3d4e5f60718293a4b', 'status': 'CANCELED'},
    {'operation': 'reply_email', 'identityId': '6650a1b2c3d4e5f6a7b8c901', 'leadId': '6650a1b2c3d4e5f6a7b8c903'},
])
def test_lagrowthmachine_rejects_invalid_config(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize('key', ['https://example.com/key', '<token>', 'Bearer something', 'abc\r\ndef'])
def test_lagrowthmachine_secret_shape(key):
    with pytest.raises(ValidationError):
        native.LagrowthmachineAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body', [(401, {'error': 'Invalid apikey'}), (429, {'error': 'Rate limit exceeded'}), (200, {'error': 'Invalid apikey'}), (200, {}), (200, [])])
async def test_lagrowthmachine_errors_and_no_retries(monkeypatch, code, body):
    seen = transport(monkeypatch, httpx.Response(code, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_audiences'}).execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_lagrowthmachine_connection_evidence_and_reflected_secret(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'statusCode': 200, 'audiences': [{'id': 'a', 'name': 'Acme prospects'}]}))
    result = await node({'operation': 'list_audiences'}).execute({})
    assert _rows_from_operation(result)[0]['name'] == 'Acme prospects'
    transport(monkeypatch, httpx.Response(200, json={'id': 'owner', 'email': 'john.doe@acme.com'}))
    result = await node({'operation': 'get_me'}).execute({})
    assert _identity_label(result, native.LagrowthmachineNode.connection_evidence.identity_keys) == 'john.doe@acme.com'
    transport(monkeypatch, httpx.Response(401, json={'error': 'Invalid apikey ' + TOKEN}))
    with pytest.raises(ValueError, match='Invalid apikey') as exc:
        await node({'operation': 'get_me'}).execute({})
    assert TOKEN not in str(exc.value)
