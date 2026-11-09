"""Daylite request serialization and provider-example response tests.

Fixtures use the pinned contract and current Notes documentation; transport is mocked.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import daylite_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/daylite/responses.json').read_text())
TOKEN = 'test-daylite-access-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='daylite-test', node_type='automation-daylite', node_data={
        'config': config, 'credentials': {'credential_type': 'daylite_personal_token', 'access_token': TOKEN}})


def mock_client(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_published_responses_and_exact_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    config = {'operation': operation}
    if '{id}' in fixture['path']:
        config['record_id'] = 1000
    if operation in {'create_task', 'update_task'}:
        config.update(title='Call customer', due='2026-11-10')
    if operation in {'create_contact', 'update_contact'}:
        config.update(first_name='Mark', emails=[{'label': 'work', 'address': 'mark@example.test'}])
    if operation in {'create_company', 'update_company', 'create_project', 'update_project', 'create_opportunity', 'update_opportunity'}:
        config['name'] = 'Example'
    if operation in {'create_note', 'update_note'}:
        config.update(title='Meeting notes', details='Follow up tomorrow')
    requests = mock_client(monkeypatch, fixture['status'], fixture['body'])
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url).startswith(native.BASE_URL)
    assert request.method == fixture['method']
    assert request.url.path == '/v1' + fixture['path'].replace('{id}', '1000')
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert result['status'] == 'success'
    assert TOKEN not in str(result)
    if fixture['status'] != 204:
        assert result['items' if isinstance(fixture['body'], list) else 'data'] == fixture['body']
    if request.method in {'POST', 'PATCH'}:
        assert json.loads(request.content) == {k: v for k, v in config.items() if k not in {'operation', 'record_id'}}
    elif operation.startswith('list_') and operation != 'list_projects':
        assert dict(request.url.params) == {'include_trash': 'false'}


@pytest.mark.asyncio
async def test_http_rejection_not_success(monkeypatch):
    mock_client(monkeypatch, 401, {'error': 'Unauthorized'})
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'list_contacts'}).execute({})


@pytest.mark.asyncio
async def test_error_envelope_not_success(monkeypatch):
    mock_client(monkeypatch, 200, {'error': {'message': 'Denied'}})
    assert (await node({'operation': 'list_contacts'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('value', ['Bearer secret', 'line\nbreak', ''])
def test_invalid_token(value):
    with pytest.raises(ValidationError):
        native.DaylitePersonalToken(access_token=value)


def test_manual_credential_default_and_numeric_route():
    assert native.DaylitePersonalToken(access_token=TOKEN).credential_type == 'daylite_personal_token'
    for invalid in ['../info', 0, -1]:
        with pytest.raises(ValidationError):
            native.GetContact(record_id=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize('config, response', [
    ({'operation': 'list_contacts'}, {}),
    ({'operation': 'get_contact', 'record_id': 1000}, []),
    ({'operation': 'list_contacts'}, 'unexpected'),
    ({'operation': 'list_contacts'}, ['unexpected']),
])
async def test_unexpected_response_shape_cannot_prove_connection(monkeypatch, config, response):
    mock_client(monkeypatch, 200, response)
    with pytest.raises(ValueError, match='unexpected JSON response'):
        await node(config).execute({})


@pytest.mark.asyncio
async def test_unexpected_empty_read_cannot_prove_connection(monkeypatch):
    mock_client(monkeypatch, 204, None)
    with pytest.raises(ValueError, match='unexpected empty response'):
        await node({'operation': 'list_contacts'}).execute({})
