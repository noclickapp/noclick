"""Exercise Moskit's real factory and HTTP boundary with synthetic CRM records.

These regressions pin each operation's method, route, body and API-key handling.
No provider account or live mutation is needed.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import moskit_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-moskit-key-42'
CREDENTIAL = {'credential_type': 'moskit_api_key', 'api_key': TOKEN}
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/moskit/operations.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='moskit-test', node_type='automation-moskit', node_data={
        'config': config, 'credentials': credential or CREDENTIAL,
    })


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURES, ids=lambda case: case['config']['operation'])
async def test_every_operation_one_documented_request(monkeypatch, case):
    listing = case['config']['operation'].startswith('list_')
    deleting = case['method'] == 'DELETE'
    response = httpx.Response(204) if deleting else httpx.Response(200, json=[{'id': 7, 'name': 'Fixture'}] if listing else {'id': 7, 'name': 'Fixture'}, headers={'X-Ollow-Listing-Next-Page-Token': 'next-owned-page'} if listing else {})
    requests = transport(monkeypatch, response)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url).split('?')[0] == native.BASE_URL + case['path']
    assert request.headers['apikey'] == TOKEN
    assert TOKEN not in str(result) and TOKEN not in str(request.url)
    assert dict(request.url.params) == ({'quantity': '50'} if listing else {})
    if 'body' in case:
        assert request.headers['content-type'] == 'application/json'
        assert json.loads(request.content) == case['body']
    else:
        assert not request.content
    if listing:
        assert result['has_more'] and result['next_page_token'] == 'next-owned-page'
    if deleting:
        assert result['deleted'] and result['http_status'] == 204


@pytest.mark.asyncio
async def test_pagination_and_empty_account_evidence(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json=[]))
    result = await node({'operation': 'list_contacts', 'next_page_token': 'opaque+/=', 'quantity': 5, 'sort': 'name', 'order': 'asc'}).execute({})
    assert dict(requests[0].url.params) == {'quantity': '5', 'nextPageToken': 'opaque+/=', 'sort': 'name', 'order': 'asc'}
    assert result['data'] == [] and not result['has_more']
    assert native.MoskitNode.connection_evidence.operation == 'list_contacts'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, 'API key invalid'), (403, 'permission denied'), (429, 'rate limited'), (500, TOKEN), (302, 'redirect')])
async def test_provider_rejections_are_errors_without_retry(monkeypatch, status, body):
    requests = transport(monkeypatch, httpx.Response(status, text=body))
    result = await node(FIXTURES[2]['config']).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1
    if status == 401:
        assert result['error'] == body


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, None, 'bad', [1], {'error': 'failure'}])
async def test_wrong_list_envelopes_fail(monkeypatch, payload):
    transport(monkeypatch, httpx.Response(200, json=payload))
    assert (await node({'operation': 'list_contacts'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_write_timeout_does_not_retry_or_claim_success(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('lost response', request=request)
    requests = transport(monkeypatch, timeout)
    result = await node(FIXTURES[2]['config']).execute({})
    assert result['status'] == 'error' and len(requests) == 1
    assert 'inspect writes before retrying' in result['error']


@pytest.mark.parametrize('config', [
    {'operation': 'list_contacts', 'start': 0, 'next_page_token': 'token'},
    {'operation': 'get_contact', 'contact_id': -1},
    {'operation': 'get_contact', 'contact_id': '../users'},
    {'operation': 'create_contact', 'name': 'Missing owner'},
    {'operation': 'list_contacts', 'quantity': 101},
    {'operation': 'list_contacts', 'arbitrary_route': '/users'},
])
def test_invalid_config_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_wrong_family():
    assert native.MoskitAPIKeyCredential(api_key=TOKEN).credential_type == 'moskit_api_key'
    assert native.MoskitAPIKeyCredential(api_key='  '+TOKEN+'  ').api_key == TOKEN
    for key in ['https://example.com/key', 'paste your api key here', 'a\nb']:
        with pytest.raises(ValueError):
            native.MoskitAPIKeyCredential(api_key=key)
    with pytest.raises(ValueError):
        node({'operation': 'list_contacts'}, {'credential_type': 'other_key', 'api_key': TOKEN})
