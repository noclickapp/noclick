"""RentCast's published examples through the actual node and credential seam."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import rentcast_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/rentcast/published_examples.json').read_text())
TOKEN = 'rentcast-synthetic-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='rentcast-test', node_type='automation-rentcast',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'rentcast_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_published_contract_examples(monkeypatch, case):
    requests = transport(monkeypatch, case['response'])
    result = await node({'operation': case['operation'], **case['config']}).execute({})
    assert result['status'] == 'success'
    assert result['operation'] == case['operation']
    assert result['items' if isinstance(case['response'], list) else 'data'] == case['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET'
    expected = case['path'].replace('{id}', quote(case['config'].get('property_id', ''), safe=''))
    assert request.url.raw_path.split(b'?')[0].decode() == '/v1' + expected
    assert request.url.host == 'api.rentcast.io'
    assert request.headers['X-Api-Key'] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    assert request.content == b''
    assert all(k not in request.url.params for k in ('operation', 'property_id', 'zip_code', 'comp_count'))
    for key, value in case['config'].items():
        if key != 'property_id':
            assert request.url.params[native.WIRE_NAMES.get(key, key)] == str(value)


def test_discovery_and_manual_credential():
    assert NODE_REGISTRY['automation-rentcast'] is native.RentCastNode
    shaped, errors, _ = shape_credential('rentcast_api_key', {'api_key': '  ' + TOKEN + '  '})
    assert not errors and shaped['api_key'] == TOKEN
    assert native.RentCastAPIKeyCredential.model_validate(shaped).credential_type == 'rentcast_api_key'
    assert not native.RentCastAPIKeyCredential.model_fields['credential_type'].is_required()
    assert native.RentCastNode.connection_evidence.proves == 'reachability'
    with pytest.raises(ValidationError):
        native.RentCastAPIKeyCredential(api_key='https://app.rentcast.io/app/api')
    with pytest.raises(ValidationError):
        native.RentCastAPIKeyCredential(credential_type='other_key', api_key=TOKEN)


@pytest.mark.asyncio
async def test_boolean_filters_and_page_boundary(monkeypatch):
    requests = transport(monkeypatch, [{'id': 'record'}], headers={'X-Total-Count': '3'})
    result = await node({'operation': 'search_properties', 'zip_code': '29611',
        'limit': 1, 'offset': 1, 'include_total_count': True, 'bedrooms': '2:4'}).execute({})
    assert result['next_offset'] == 2 and result['total_count'] == 3 and result['offset'] == 1
    assert dict(requests[0].url.params) == {'zipCode': '29611', 'limit': '1', 'offset': '1', 'includeTotalCount': 'true', 'bedrooms': '2:4'}


@pytest.mark.asyncio
async def test_empty_page_and_false_boolean(monkeypatch):
    transport(monkeypatch, [])
    result = await node({'operation': 'search_sale_listings', 'state': 'TX'}).execute({})
    assert result['items'] == [] and result['next_offset'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_http_errors_never_succeed_and_redact_key(monkeypatch, status):
    transport(monkeypatch, {'message': 'rejected ' + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_random_properties'}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('list_random_properties', {}), ('get_market_statistics', []), ('get_property', {'id': 'wrong'}), ('get_market_statistics', {'error': 'bad'})])
async def test_wrong_response_shapes_fail(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': operation, **({'zip_code': '29611'} if 'market' in operation else {'property_id': 'record'} if operation == 'get_property' else {})}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'search_properties'},
    {'operation': 'search_properties', 'city': 'Austin'},
    {'operation': 'search_properties', 'latitude': 30, 'longitude': -97},
    {'operation': 'search_properties', 'zip_code': '29611', 'radius': 5},
    {'operation': 'get_value_estimate'},
    {'operation': 'get_value_estimate', 'latitude': 30},
    {'operation': 'get_rent_estimate', 'address': 'example', 'property_type': 'Land'},
    {'operation': 'get_property', 'property_id': '../markets'},
    {'operation': 'list_random_properties', 'limit': 501},
    {'operation': 'get_market_statistics', 'zip_code': '123'},
    {'operation': 'get_market_statistics', 'zip_code': '29611', 'unknown': 'value'},
])
def test_invalid_inputs_are_rejected(config):
    assert native.RentCastNode.validate_config({'config': config})['valid'] is False
