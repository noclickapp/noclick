"""Exercise the native factory and HTTP contract without provider credentials."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import get_the_referral_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/get-the-referral/operations.json').read_text())
TOKEN = 'gtr-synthetic-test-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='gtr-test', node_type='automation-get-the-referral',
        node_data={'config': config, 'credentials': {'credential_type': 'get_the_referral_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response, status=200):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=response) if response is not None else httpx.Response(status)

    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_each_operation_exact_request_and_response(monkeypatch, operation):
    fixture = FIXTURES[operation]
    config = dict(fixture['config'])
    if fixture['method'] == 'PATCH':
        config['firstname'] = 'Updated'
    if operation.startswith('list_'):
        config['page'] = 2
        config['page_size'] = 10
    if operation == 'create_lead':
        config.update(is_lead_from_crm=False, note='Follow up', crm_lead_id='crm-42')
    if operation == 'update_lead_status':
        config.update(lead_status='3', amount=0, job_id='job-42')
    requests = transport(monkeypatch, fixture['response'])
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    assert str(request.url).split('?')[0] == native.BASE_URL + fixture['path']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if operation.startswith('list_'):
        assert request.url.params['page'] == '2' and request.url.params['page_size'] == '10'
        assert result['pagination'] == fixture['response']['pagination']
    if fixture['body_fields']:
        expected = {key: config[key] for key in fixture['body_fields'] if key in config}
        assert json.loads(request.content) == expected
    else:
        assert request.content == b''
    if operation == 'update_lead_status':
        assert result['data']['id'] == '123' and result['data']['status_id'] == '3'
    if operation == 'delete_contact':
        assert result['deletion_acknowledged'] is True
    elif isinstance(fixture['response'], list):
        assert result['data'] == fixture['response']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 422, 429, 500])
async def test_errors_preserve_provider_rejection_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'API key rejected ' + TOKEN}, status)
    result = await node({'operation': 'list_advocates'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'API key rejected' in result['error'] and TOKEN not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{}, [], {'error': 'Denied'}, {'success': False}, {'advocates': 'bad'}])
async def test_invalid_list_and_error_envelope_are_not_evidence(monkeypatch, response):
    transport(monkeypatch, response)
    assert (await node({'operation': 'list_advocates'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_connection_read_returns_account_specific_advocates(monkeypatch):
    advocate = {'id': '12', 'type': 'advocate', 'attributes': {'firstname': 'Nina', 'email': 'nina@example.com'}}
    transport(monkeypatch, {'advocates': [advocate], 'pagination': {'currentPage': '1', 'lastPage': 1}})
    result = await node({'operation': native.GetTheReferralNode.connection_evidence.operation}).execute({})
    assert result['data'] == [advocate]


@pytest.mark.asyncio
async def test_empty_update_refused_before_network(monkeypatch):
    requests = transport(monkeypatch, [])
    with pytest.raises(ValueError, match='at least one field'):
        await node({'operation': 'update_lead', 'lead_id': '123'}).execute({})
    assert not requests


@pytest.mark.parametrize('identifier', ['../leads', '1/contacts', '12?x=y', 'https://evil.test'])
def test_path_injection_refused(identifier):
    with pytest.raises(ValidationError):
        native.GetLeadConfig(lead_id=identifier)


def test_hand_connection_type_default_and_required_key():
    credential = native.GetTheReferralAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'get_the_referral_api_key'
    with pytest.raises(ValidationError):
        native.GetTheReferralAPIKeyCredential(api_key='Bearer ' + TOKEN)


@pytest.mark.asyncio
async def test_write_response_redacts_password_and_api_key(monkeypatch):
    transport(monkeypatch, [{'id': '123', 'attributes': {'password': 'Sensitive password', 'note': TOKEN}}])
    config = {**FIXTURES['create_advocate']['config'], 'password': 'Sensitive password'}
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert TOKEN not in str(result) and 'Sensitive password' not in str(result)
