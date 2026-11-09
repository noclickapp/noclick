"""Offline regressions for SMSAPI routes, wire encodings and failure semantics."""
import json
from pathlib import Path
from urllib.parse import parse_qs
import httpx
import pytest
from pydantic import ValidationError
from nodes import smsapi_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-smsapi-token'
ID = '0f0f0f0f0f0f0f0f0f0f0f0f'
PROFILE = json.loads((Path(__file__).parent / 'fixtures/smsapi/profile.json').read_text())

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='smsapi-test', node_type='automation-smsapi', node_data={
        'config': config, 'credentials': {'credential_type': 'smsapi_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, payload, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ('get_profile', {}, 'GET', '/profile', PROFILE),
    ('list_sendernames', {}, 'GET', '/sms/sendernames', {'size': 0, 'collection': []}),
    ('get_sendername', {'sender': 'My Brand'}, 'GET', '/sms/sendernames/My%20Brand', {'sender': 'My Brand'}),
    ('list_templates', {}, 'GET', '/sms/templates', {'size': 0, 'collection': []}),
    ('get_template', {'template_id': 'abc'}, 'GET', '/sms/templates/abc', {'id': 'abc'}),
    ('create_template', {'name': 'Welcome', 'template': 'Hello + café'}, 'POST', '/sms/templates', {'id': 'abc'}),
    ('update_template', {'template_id': 'abc', 'name': 'Welcome', 'template': 'Hello'}, 'PUT', '/sms/templates/abc', {'id': 'abc'}),
    ('delete_template', {'template_id': 'abc'}, 'DELETE', '/sms/templates/abc', None),
    ('list_contacts', {}, 'GET', '/contacts', {'size': 0, 'collection': []}),
    ('get_contact', {'contact_id': ID}, 'GET', '/contacts/' + ID, {'id': ID}),
    ('create_contact', {'phone_number': '44123456789', 'email': 'john.doe@example.com'}, 'POST', '/contacts', {'id': ID}),
    ('update_contact', {'contact_id': ID, 'first_name': 'Jane'}, 'PUT', '/contacts/' + ID, {'id': ID}),
    ('delete_contact', {'contact_id': ID}, 'DELETE', '/contacts/' + ID, None),
    ('list_groups', {}, 'GET', '/contacts/groups', {'size': 0, 'collection': []}),
    ('get_group', {'group_id': ID}, 'GET', '/contacts/groups/' + ID, {'id': ID}),
    ('create_group', {'name': 'Example Group'}, 'POST', '/contacts/groups', {'id': ID}),
    ('update_group', {'group_id': ID, 'name': 'Example Group'}, 'PUT', '/contacts/groups/' + ID, {'id': ID}),
    ('delete_group', {'group_id': ID}, 'DELETE', '/contacts/groups/' + ID, None),
    ('add_contact_to_group', {'group_id': ID, 'contact_id': ID}, 'PUT', '/contacts/groups/' + ID + '/members/' + ID, {'id': ID}),
    ('get_group_member', {'group_id': ID, 'contact_id': ID}, 'GET', '/contacts/groups/' + ID + '/members/' + ID, {'id': ID}),
    ('remove_contact_from_group', {'group_id': ID, 'contact_id': ID}, 'DELETE', '/contacts/groups/' + ID + '/members/' + ID, None),
    ('send_sms', {'to': '44123456789', 'message': 'Hello + café', 'sender': 'Brand', 'test': True, 'idx': 'order-42', 'check_idx': True}, 'POST', '/sms.do', {'count': 1, 'list': [{'id': '7074294081650020450', 'status': 'QUEUE'}]}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,payload', CASES)
async def test_operation_has_one_exact_provider_request(monkeypatch, operation, config, method, path, payload):
    status = 204 if payload is None else 201 if operation.startswith('create_') else 200
    requests = transport(monkeypatch, payload, status)
    result = await node({'operation': operation, **config}).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split('?')[0] == native.BASE + path
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if operation == 'send_sms':
        body = parse_qs(request.content.decode())
        assert body['from'] == ['Brand'] and 'sender' not in body
        assert body['test'] == ['1'] and body['check_idx'] == ['1']
        assert body['format'] == ['json'] and body['message'] == ['Hello + café']
        assert result['delivery_verified'] is False and result['test'] is True
    elif operation == 'delete_group':
        assert parse_qs(request.content.decode()) == {'delete_contacts': ['false']}
    elif method in {'POST', 'PUT'} and config.get('name'):
        assert parse_qs(request.content.decode())['name'] == [config['name']]
    if operation == 'list_contacts':
        assert dict(request.url.params) == {'limit': '50', 'offset': '0'}
        assert result['complete'] is False and result['next_offset'] is None


@pytest.mark.asyncio
async def test_contacts_pagination_is_explicit_and_not_followed(monkeypatch):
    requests = transport(monkeypatch, {'size': 20, 'collection': [{'id': ID}]})
    result = await node({'operation': 'list_contacts', 'limit': 1, 'offset': 10, 'q': 'John + Doe'}).execute({})
    assert result['next_offset'] == 11 and len(requests) == 1
    assert dict(requests[0].url.params) == {'limit': '1', 'offset': '10', 'q': 'John + Doe'}


@pytest.mark.asyncio
@pytest.mark.parametrize('config', [
    {'operation': 'get_template', 'template_id': '..'},
    {'operation': 'get_sendername', 'sender': '.'},
])
async def test_dot_segments_cannot_change_the_selected_route(monkeypatch, config):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match='path segment'):
        await node(config).execute({})
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(401, {'message': 'Unauthorized'}), (403, {'message': 'Forbidden'}), (429, {'message': 'Rate limit'}), (302, None), (200, {'error': 13, 'message': 'Invalid token'}), (200, []), (200, {})])
async def test_provider_errors_and_bad_identity_fail(monkeypatch, status, payload):
    transport(monkeypatch, payload, status)
    with pytest.raises(ValueError):
        await node({'operation': 'get_profile'}).execute({})


@pytest.mark.asyncio
async def test_ambiguous_write_is_never_retried(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout('untrusted ' + TOKEN))
    with pytest.raises(ValueError, match='write outcome is unknown') as error:
        await node({'operation': 'send_sms', 'to': '44123456789', 'message': 'Hello'}).execute({})
    assert len(requests) == 1 and TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_redaction_and_async_deletion_acknowledgment(monkeypatch):
    transport(monkeypatch, {**PROFILE, 'debug': TOKEN})
    result = await node({'operation': 'get_profile'}).execute({})
    assert TOKEN not in str(result)
    transport(monkeypatch, None, 202)
    result = await node({'operation': 'delete_group', 'group_id': ID}).execute({})
    assert result['accepted'] and not result['completion_verified']


def test_manual_credential_defaults_and_strict_resource_ids():
    assert native.SMSAPITokenCredential(api_token=TOKEN).credential_type == 'smsapi_api_token'
    for value in ['Bearer abc', 'https://example.com/token', '<token>']:
        with pytest.raises(ValidationError):
            native.SMSAPITokenCredential(api_token=value)
    for config in [{'operation': 'get_contact', 'contact_id': '../profile'},
                   {'operation': 'update_contact', 'contact_id': ID},
                   {'operation': 'send_sms', 'to': 'bad', 'message': 'Hello'}]:
        with pytest.raises(ValueError):
            native.SMSAPINode.parse_config({'config': config})
