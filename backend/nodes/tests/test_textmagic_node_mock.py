"""Exercise Textmagic requests through discovery using an intercepted HTTP transport.

The fixture pins endpoint identities to the published v2 contract; these tests
cover wire bodies, pagination, manual authentication and provider failures.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import textmagic_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CONTRACT = json.loads((Path(__file__).parent / 'fixtures/textmagic/operations.json').read_text())
CREDENTIAL = {"credential_type": "textmagic_api_key", "username": "charles.conway", "api_key": "test-private-api-key"}
CONTACT = {"phone": "447860021130", "lists": "10541,18599", "first_name": "Charles", "last_name": "Conway", "email": "charles@example.com", "company_name": "Example Ltd.", "favorited": False}
TEMPLATE = {"name": "New template name", "content": "New template content"}


def node(config):
    return NodeFactory.create_node(node_id="textmagic-test", node_type="automation-textmagic", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', CONTRACT['operations'], ids=lambda e: e['operation'])
async def test_textmagic_all_native_routes_and_basic_auth(monkeypatch, entry):
    op = entry['operation']
    config = {"operation": op}
    if '{id}' in entry['path']:
        config['id'] = 515
    if op in ('create_contact', 'update_contact'):
        config.update(CONTACT)
    if op in ('create_template', 'update_template'):
        config.update(TEMPLATE)
    if op == 'create_contact_list':
        config.update(name='Private list', shared=False)
    if op == 'add_contacts_to_list':
        config['contacts'] = '318,454,30091'
    if op == 'send_message':
        config.update(text='Hello, how are you?', phones='447860021130,447860021131', sender='Test sender id', sending_date_time='2030-05-27 13:02:33', sending_timezone='America/Buenos_Aires', reference_id=1)
    method = entry['method']
    if op.startswith('list_'):
        body = {"page": 1, "pageCount": 10, "limit": 10, "resources": [{"id": 515}]}
    elif op == 'get_account':
        body = {"id": 305, "username": "charles.conway", "email": "charles@example.com"}
    else:
        body = {"id": 515, "href": "/api/v2/entity_name/1"}
    status = 200 if method == 'GET' else 204 if method == 'DELETE' else 201
    requests = transport(monkeypatch, body if status != 204 else None, status)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'rest.textmagic.com'
    assert request.url.path == entry['path'].replace('{id}', '515')
    assert request.headers['Authorization'] == 'Basic ' + base64.b64encode(b'charles.conway:test-private-api-key').decode()
    if method == 'GET':
        assert not request.content
        assert dict(request.url.params) == ({'page': '1', 'limit': '10'} if op.startswith('list_') else {})
    elif method != 'DELETE':
        actual = json.loads(request.content)
        assert 'id' not in actual and 'operation' not in actual
        if op in ('create_contact', 'update_contact'):
            assert actual == {'phone': CONTACT['phone'], 'lists': CONTACT['lists'], 'firstName': 'Charles', 'lastName': 'Conway', 'email': CONTACT['email'], 'companyName': 'Example Ltd.', 'favorited': False}
        elif op in ('create_template', 'update_template'):
            assert actual == TEMPLATE
        elif op == 'send_message':
            assert actual == {'text': 'Hello, how are you?', 'phones': '447860021130,447860021131', 'from': 'Test sender id', 'sendingDateTime': '2030-05-27 13:02:33', 'sendingTimezone': 'America/Buenos_Aires', 'referenceId': 1, 'partsCount': 6, 'cutExtra': False}
            assert result['accepted'] and result['delivery_verified'] is False
        elif op == 'add_contacts_to_list':
            assert actual == {'contacts': '318,454,30091'}
        else:
            assert actual == {'name': 'Private list', 'shared': False}
    else:
        assert not request.content and result['deletion_acknowledged']
    if op.startswith('list_'):
        assert result['items'] == body['resources'] and result['next_page'] == 2
    assert CREDENTIAL['api_key'] not in str(result)


@pytest.mark.asyncio
async def test_textmagic_last_page_and_empty_page_preserve_metadata(monkeypatch):
    requests = transport(monkeypatch, {'page': 3, 'pageCount': 3, 'limit': 20, 'resources': []})
    result = await node({'operation': 'list_contacts', 'page': 3, 'limit': 20}).execute({})
    assert result['status'] == 'success' and result['items'] == [] and result['next_page'] is None
    assert dict(requests[0].url.params) == {'page': '3', 'limit': '20'}
    assert result['data']['pageCount'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_textmagic_provider_errors_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Provider rejected ' + CREDENTIAL['api_key']}, status)
    result = await node({'operation': 'get_account'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Provider rejected [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_textmagic_async_send_does_not_claim_delivery(monkeypatch):
    transport(monkeypatch, None, 202)
    result = await node({'operation': 'send_message', 'text': 'Hello', 'phones': '447860021130'}).execute({})
    assert result == {'status': 'success', 'http_status': 202, 'accepted': True, 'delivery_verified': False}


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'resources': []}, {'page': '1', 'pageCount': 2, 'limit': 10, 'resources': []}, {'errors': ['failed']}])
async def test_textmagic_malformed_page_is_not_empty_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'list_contacts'}).execute({}))['status'] == 'error'


def test_textmagic_discovery_manual_credentials_and_required_contact_membership():
    assert NODE_REGISTRY['automation-textmagic'] is native.TextmagicNode
    assert native.TextmagicAPIKeyCredential(username='charles.conway', api_key='test-private-api-key').credential_type == 'textmagic_api_key'
    assert native.TextmagicNode.connection_evidence.identity_operation == 'get_account'
    for config in [dict(operation='create_contact', phone='447860021130'), dict(operation='update_contact', id=1, lists='10541'), dict(operation='get_message', id='../1'), dict(operation='send_message', text='Hello', phones='invalid'), dict(operation='list_contacts', page=0)]:
        with pytest.raises(ValueError):
            native.TextmagicNode.parse_config({'config': config, 'credentials': CREDENTIAL})
