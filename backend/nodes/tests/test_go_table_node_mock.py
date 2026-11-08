"""Exercise real Go Table factory nodes with synthetic HTTP responses."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import go_table_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/go-table/operations.json').read_text())
TOKEN = 'synthetic-go-table-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='go-table-test', node_type='automation-go-table',
        node_data={'config': config, 'credentials': {'credential_type': 'go_table_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_go_table_every_operation_uses_published_route(monkeypatch, operation):
    fixture = FIXTURES[operation]
    config = fixture['config']
    body = {'id': 12345, 'name': 'Owned restaurant'}
    if operation.startswith('list_'):
        key = 'notes' if operation == 'list_reservation_notes' else operation[5:]
        body = {key: [body], 'meta': {'current_page': 1, 'total_pages': 3}}
    requests = transport(monkeypatch, body, fixture['response_status'])
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    assert request.url.host == 'gotable.app'
    assert request.url.path == fixture['path'].format(**config)
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if operation.startswith('list_'):
        assert result['items'][0]['id'] == 12345 and result['next_page'] == 2
    if operation == 'create_reservation':
        assert json.loads(request.content) == {'date': '2026-10-26', 'time': '18:00', 'party_size': 2}
        assert dict(request.url.params) == {'role': 'restaurant', 'skip_email': 'false', 'skip_sms': 'false'}
    if operation == 'create_reservation_note':
        assert json.loads(request.content) == {'content': 'Lorem ipsum dolor sit amet.', 'author_id': 12345}


@pytest.mark.asyncio
async def test_go_table_query_filters_and_false_patch(monkeypatch):
    requests = transport(monkeypatch, {'id': 98765, 'subscribed': False})
    await node({'operation': 'update_guest', 'restaurant_id': 12345, 'guest_id': 98765, 'subscribed': False}).execute({})
    assert json.loads(requests[0].content) == {'subscribed': False}
    requests = transport(monkeypatch, {'guests': [], 'meta': {'current_page': 2, 'total_pages': 2}})
    result = await node({'operation': 'list_guests', 'restaurant_id': 12345, 'query': 'John + café', 'page': 2, 'per_page': 100}).execute({})
    assert dict(requests[0].url.params) == {'query': 'John + café', 'page': '2', 'per_page': '100'}
    assert result['next_page'] is None
    requests = transport(monkeypatch, {'days': []})
    await node({'operation': 'get_restaurant_availability', 'restaurant_id': 12345, 'from_date': '2026-10-26', 'till': '2026-10-27'}).execute({})
    assert dict(requests[0].url.params) == {'from': '2026-10-26', 'till': '2026-10-27'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_go_table_rejection_preserves_provider_text_without_secret(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Denied ' + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_restaurants'}).execute({})
    assert 'Denied' in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'restaurants': {}}, {'errors': ['Denied']}, []])
async def test_go_table_invalid_evidence_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_restaurants'}).execute({})


def test_go_table_credential_default_and_input_validation():
    assert native.GoTableAPITokenCredential(api_token=TOKEN).credential_type == 'go_table_api_token'
    for config in [
        {'operation': 'create_reservation', 'restaurant_id': 12345, 'party_size': 2},
        {'operation': 'get_guest', 'restaurant_id': '../bad', 'guest_id': 1},
        {'operation': 'list_restaurants', 'per_page': 101},
        {'operation': 'create_reservation_note', 'restaurant_id': 12345, 'reservation_id': 12345, 'content': 'Note'},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(config)
    for token in ['Bearer token', 'https://gotable.app', 'bad\nvalue']:
        with pytest.raises(ValidationError):
            native.GoTableAPITokenCredential(api_token=token)
