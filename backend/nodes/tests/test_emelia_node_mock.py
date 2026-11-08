"""Pinned provider examples and request boundary tests; no live account is used."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import emelia_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/emelia/documented_examples.json').read_text())
TOKEN = 'synthetic-emelia-api-key-for-tests'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='emelia-fixture', node_type='automation-emelia',
        node_data={'config': config, 'credentials': {'credential_type': 'emelia_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_provider_documented_examples(monkeypatch, operation):
    example = EXAMPLES[operation]
    # Where the provider publishes no media example, use the documented success shape.
    body = example['response']
    if body is None:
        body = {'success': True}
    requests = transport(monkeypatch, body, 201 if operation == 'create_list' else 200)
    result = await node(example['config']).execute({})
    assert result['status'] == 'success', result
    assert result['data'] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example['method']
    assert request.url.host == 'api.emelia.io'
    assert request.headers['Authorization'] == TOKEN
    assert TOKEN not in str(result)
    # Crucial body locations: DELETE has JSON, updateIfExists is query-only,
    # list contact dictionaries are the body itself, not a nested contact field.
    if example['request'] is not None:
        assert json.loads(request.content) == example['request']
    if operation == 'remove_campaign_contact':
        assert set(json.loads(request.content)) == {'id', 'contactId'}
    if operation in {'add_list_contact', 'add_list_contacts_batch'}:
        assert request.url.params['updateIfExists'] == 'false'
        assert 'updateIfExists' not in json.loads(request.content)



@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'message': 'Invalid API key'}), (200, {'success': False}),
    (200, {'error': 'denied'}), (200, {}), (200, ['unexpected']), (200, {'errors': ['denied']})])
async def test_fail_closed_on_errors_and_missing_results(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    result = await node({'operation': 'list_campaigns'}).execute({})
    assert result['status'] == 'error' and result['success'] is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_raw_key_and_redaction_and_evidence(monkeypatch):
    requests = transport(monkeypatch, {'success': True, 'campaigns': [{'_id': '6650f1a2b839d80011c5a0f1', 'name': TOKEN}]})
    result = await node({'operation': 'list_campaigns'}).execute({})
    assert result['items'][0]['name'] == '[redacted]'
    assert requests[0].headers['Authorization'] == TOKEN
    assert native.EmeliaNode.connection_evidence.operation == 'list_campaigns'
    assert native.EmeliaAPIKeyCredential(api_key=TOKEN).credential_type == 'emelia_api_key'


@pytest.mark.parametrize('config', [
    {'operation': 'get_campaign', 'campaign_id': '../bad'},
    {'operation': 'get_list', 'list_id': 'https://other.test'},
    {'operation': 'list_lists', 'page': -1},
    {'operation': 'add_campaign_contact', 'campaign_id': '6650f1a2b839d80011c5a0f1', 'contact': {'firstName': 'Jane'}},
    {'operation': 'add_campaign_contact', 'campaign_id': '6650f1a2b839d80011c5a0f1', 'contact': {'email': 'a@b.com', 'age': 42}},
    {'operation': 'add_list_contact', 'list_id': '6650f1a2b839d80011c5a0f1', 'contact': {'tags': ['bad']}},
    {'operation': 'add_list_contacts_batch', 'list_id': '6650f1a2b839d80011c5a0f1', 'contacts': []},
])
def test_invalid_identifiers_and_contact_payloads(config):
    with pytest.raises((ValueError, ValidationError)):
        native.EmeliaNode.parse_config({'config': config})


@pytest.mark.asyncio
async def test_explicit_pages_remain_single_requests(monkeypatch):
    requests = transport(monkeypatch, {'items': [], 'total': 123, 'page': 3, 'pageSize': 25, 'totalLeads': 9})
    result = await node({'operation': 'list_lists', 'page': 3, 'limit': 25}).execute({})
    assert result['data']['total'] == 123 and result['page'] == 3
    assert dict(requests[0].url.params) == {'page': '3', 'limit': '25'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_unknown_write_outcome_is_not_retried(monkeypatch):
    requests = []
    def fail(request):
        requests.append(request)
        raise httpx.ReadTimeout('timeout', request=request)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kw))
    result = await node({'operation': 'create_list', 'name': 'Prospects'}).execute({})
    assert result['status'] == 'unknown' and result['success'] is False
    assert len(requests) == 1
