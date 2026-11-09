"""Sure Send requests through the real factory; all account data is synthetic."""
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import sure_send_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-suresend-api-token'
ID = '123e4567-e89b-12d3-a456-426614174000'
IDENTITY = {'account': {'id': ID, 'name': 'Fixture Team'}, 'user': {'id': ID, 'email': 'fixture@example.com'}, 'tokenScope': 'team'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='sure-send-fixture', node_type='automation-sure-send',
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_token': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
async def test_sure_send_identity_authentication_and_manual_credential(monkeypatch):
    parsed = native.SureSendAPITokenCredential(api_token=TOKEN)
    assert parsed.credential_type == 'sure_send_api_token'
    requests = transport(monkeypatch, IDENTITY)
    out = await node({'operation': 'get_identity'}).execute({})
    assert out['name'] == 'Fixture Team' and out['data'] == IDENTITY
    assert requests[0].url == 'https://api.suresend.ai/api/partner/identity'
    assert requests[0].headers['Authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(out)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body', [
    ('create_person', {'name': 'John Doe', 'emails': [{'value': 'john@example.com'}]}, 'POST', '/people', {'name': 'John Doe', 'emails': [{'value': 'john@example.com', 'type': 'work', 'status': 'active', 'isPrimary': True}]}),
    ('update_person', {'id': ID, 'firstName': 'Jane'}, 'PUT', '/people/' + ID, {'firstName': 'Jane'}),
    ('apply_person_tags', {'id': ID, 'tags': ['buyer']}, 'POST', '/people/' + ID + '/tags/apply', {'tags': ['buyer']}),
    ('remove_person_tags', {'id': ID, 'tags': ['buyer']}, 'POST', '/people/' + ID + '/tags/delete', {'tags': ['buyer']}),
    ('create_tag', {'name': 'Buyer', 'color': '#3B82F6'}, 'POST', '/tags', {'tag': {'name': 'Buyer', 'color': '#3B82F6'}}),
    ('create_note', {'personId': ID, 'body': 'Follow up'}, 'POST', '/notes', {'personId': ID, 'body': 'Follow up', 'isHtml': False, 'isPinned': False}),
    ('update_note', {'id': ID, 'isPinned': False}, 'PUT', '/notes/' + ID, {'isPinned': False}),
    ('create_task', {'personId': ID, 'name': 'Call'}, 'POST', '/tasks', {'personId': ID, 'name': 'Call'}),
    ('update_task', {'id': ID, 'isCompleted': True}, 'PUT', '/tasks/' + ID, {'isCompleted': True}),
    ('create_appointment', {'personId': ID, 'title': 'Showing', 'startsAt': '2025-10-15T14:00:00Z'}, 'POST', '/appointments', {'personId': ID, 'title': 'Showing', 'startsAt': '2025-10-15T14:00:00Z'}),
    ('enroll_in_automation', {'automation_id': ID, 'personId': ID}, 'POST', '/automations/' + ID + '/enrollments', {'personId': ID}),
])
async def test_sure_send_writes_exact_documented_body(monkeypatch, operation, config, method, path, body):
    requests = transport(monkeypatch, {'id': ID}, status=201)
    result = await node({'operation': operation, **config}).execute({})
    req = requests[0]
    assert len(requests) == 1 and req.method == method and req.url.path == '/api/partner' + path
    assert json.loads(req.content) == body and result['data'] == {'id': ID}
    if operation == 'update_person':
        assert dict(req.url.params) == {'mergeTags': 'true', 'mergeEmails': 'true', 'mergePhones': 'true'}


@pytest.mark.asyncio
@pytest.mark.parametrize('resource', ['people', 'notes', 'tasks', 'appointments', 'automations', 'tags', 'text_messages', 'email_messages'])
async def test_sure_send_one_page_preserves_meta(monkeypatch, resource):
    body = {'meta': {'total_count': 51, 'current_page': 2, 'total_pages': 3, 'per_page': 25}, resource: []}
    requests = transport(monkeypatch, body)
    out = await node({'operation': 'list_' + resource, 'page': 2}).execute({})
    assert out['data'] == body and out['page'] == 2 and len(requests) == 1
    assert dict(requests[0].url.params) == {'page': '2', 'limit': '25'}


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['text', 'email'])
@pytest.mark.parametrize('send', [False, True])
async def test_sure_send_sending_is_explicit_query_not_body(monkeypatch, kind, send):
    requests = transport(monkeypatch, {'id': ID}, status=201)
    cfg = {'operation': 'create_' + kind + '_message', 'personId': ID, 'body': 'Hello', 'send': send}
    if kind == 'email': cfg['subject'] = 'Follow up'
    out = await node(cfg).execute({})
    assert dict(requests[0].url.params) == {'send': str(send).lower()}
    assert 'send' not in json.loads(requests[0].content)
    assert out['send_requested'] is send and out['delivery_verified'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,path', [('get_person', 'people'), ('get_note', 'notes'), ('get_task', 'tasks')])
async def test_sure_send_detail_exact_id(monkeypatch, operation, path):
    requests = transport(monkeypatch, {'id': ID})
    await node({'operation': operation, 'id': ID}).execute({})
    assert requests[0].url.path == '/api/partner/' + path + '/' + ID


@pytest.mark.asyncio
async def test_sure_send_provider_rejection_and_no_retry(monkeypatch):
    requests = transport(monkeypatch, {'errorMessage': 'Invalid token ' + TOKEN}, status=401)
    out = await node({'operation': 'get_identity'}).execute({})
    assert out['status'] == 'error' and out['http_status'] == 401
    assert out['error'] == 'Invalid token [redacted]' and len(requests) == 1


@pytest.mark.asyncio
async def test_sure_send_rejects_error_envelope_and_incomplete_identity(monkeypatch):
    for body in ({'errorMessage': 'Rejected'}, {}):
        transport(monkeypatch, body)
        with pytest.raises(ValueError):
            await node({'operation': 'get_identity'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_person', 'id': '../teams'},
    {'operation': 'create_appointment', 'personId': ID, 'title': 'Call', 'startsAt': '2025-10-15T14:00:00'},
    {'operation': 'create_person', 'name': 'Jane', 'emails': [{'value': 'not-an-email'}]},
    {'operation': 'list_people', 'limit': 101},
    {'operation': 'update_task', 'id': ID},
    {'operation': 'update_person', 'id': ID},
    {'operation': 'create_text_message', 'personId': ID, 'body': 'Hello', 'send': 'true'},
])
def test_sure_send_invalid_config_never_requests(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)
