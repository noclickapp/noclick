"""Exercise REI Pebble through the real node factory with documented examples.

Requests stay offline while tests cover routing, bodies, pagination and rejection handling.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import rei_pebble_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/rei-pebble/operations.json').read_text())
TOKEN = 'synthetic-pebble-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config):
    node = NodeFactory.create_node(node_id='pebble-test', node_type='automation-rei-pebble',
        node_data={'config': config, 'credentials': {'credential_type': 'rei_pebble_api_key', 'api_key': TOKEN}})
    node.emit = AsyncMock()
    return node


def transport(monkeypatch, reply):
    requests = []
    def handler(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_rei_pebble_documented_operation(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=fixture['response']))
    node = make_node({'operation': operation, **fixture['config']})
    result = await node.execute({})
    assert result == fixture['response']
    node.emit.assert_awaited_once_with(result)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    assert request.url.host == 'app.pebblerei.com'
    expected_path = fixture['path']
    for field in fixture['path_fields']:
        expected_path = expected_path.replace('{'+field+'}', fixture['config'][field])
    assert request.url.path == expected_path
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    if fixture['body_fields']:
        assert json.loads(request.content) == {k:v for k,v in fixture['config'].items() if k in fixture['body_fields']}
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_rei_pebble_page_filters_false_and_empty_results(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={'entries': [], 'page_number': 2, 'total_pages': 3}))
    result = await make_node({'operation': 'list_contacts', 'page': 2, 'has_email': False, 'name': 'Jane'}).execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'has_email': 'false', 'name': 'Jane'}
    assert result['entries'] == [] and result['total_pages'] == 3


@pytest.mark.asyncio
async def test_rei_pebble_explicit_nullable_task_date(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=FIXTURES['create_task']['response']))
    await make_node({'operation': 'create_task', 'task_list_id': 'p6rg7', 'text': 'Call the seller', 'due_date': None}).execute({})
    assert json.loads(requests[0].content)['due_date'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'errors': 'Key rejected'}), (422, {'errors': {'name': ['required']}}), (302, {}), (429, {})])
async def test_rei_pebble_errors_are_not_success_or_retried(monkeypatch, status, body):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json=body))
    node = make_node({'operation': 'get_current_user'})
    with pytest.raises(ValueError, match=f'HTTP {status}'):
        await node.execute({})
    assert len(requests) == 1
    node.emit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': None}, {'data': {}}, {'data': {}, 'errors': ['bad']}])
async def test_rei_pebble_bad_envelopes(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await make_node({'operation': 'get_current_user'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'complete_task', 'id': '../secrets'},
    {'operation': 'create_property', 'county_id': 'harris_tx'},
    {'operation': 'list_tasks', 'sort': 'due_date'},
    {'operation': 'list_contacts', 'page': 0},
    {'operation': 'create_deal', 'board_id': 'p6rg7', 'stage_id': 'k6ab7'},
])
def test_rei_pebble_rejects_invalid_config(config):
    with pytest.raises((ValidationError, ValueError)):
        make_node(config)


def test_rei_pebble_manual_credential_default():
    value = native.REIPebbleAPIKey(api_key=TOKEN)
    assert value.credential_type == 'rei_pebble_api_key'
    assert native.REIPebbleNode.connection_evidence.identity_operation == 'get_current_user'


@pytest.mark.asyncio
async def test_rei_pebble_documented_array_filters(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=FIXTURES['list_properties']['response']))
    await make_node({'operation': 'list_properties', 'ids': ['868k7', '56jg7'], 'county_ids': ['harris_tx']}).execute({})
    assert requests[0].url.params.get_list('ids[]') == ['868k7', '56jg7']
    assert requests[0].url.params.get_list('county_ids[]') == ['harris_tx']


@pytest.mark.asyncio
async def test_rei_pebble_omits_blank_nested_fields(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=FIXTURES['create_contact']['response']))
    await make_node({'operation': 'create_contact', 'name': 'First Last', 'address': {'city': None, 'state': 'DC'}}).execute({})
    assert json.loads(requests[0].content)['address'] == {'state': 'DC'}
