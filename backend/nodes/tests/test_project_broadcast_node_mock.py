"""Exercise Project Broadcast's native node through fixture HTTP.

These tests pin request routing, payloads, pagination and account evidence,
including rejection and transport failures without sending live messages.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import project_broadcast_node as pb
from nodes.core.registry import NodeFactory
from utils import ssrf

KEY = 'fixture-api-key-for-project-broadcast'
AUTH = {'credential_type': 'project_broadcast_api_key', 'api_key': KEY}
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/project-broadcast/responses.json').read_text())


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'app.projectbroadcast.com'
        assert request.headers['x-api-key'] == KEY
        assert KEY not in str(request.url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(pb, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **config):
    node = NodeFactory.create_node(node_id='pb-test', node_type='automation-project-broadcast',
        node_data={'config': {'operation': operation, **config}, 'credentials': deepcopy(AUTH)})
    return await node.execute({})


CASES = [
    ('test_connection', {}, 'GET', '/auth/keytest', None, 'identity'),
    ('search_contacts', {'term': 'Jane', 'tag': 'Lead', 'archived': False, 'paging': {'page': 2, 'pageSize': 10}}, 'POST', '/contacts/search', {'term': 'Jane', 'tag': 'Lead', 'archived': False, 'paging': {'page': 2, 'pageSize': 10}}, 'contacts'),
    ('create_contact', {'phoneNumber': '+15551234567', 'firstName': 'Jane', 'doNotMessage': False}, 'POST', '/contacts', {'phoneNumber': '+15551234567', 'firstName': 'Jane', 'doNotMessage': False}, 'contact'),
    ('get_contact', {'contact': 'jane@example.test'}, 'GET', '/contacts/jane%40example.test', None, 'contact'),
    ('update_contact', {'contact_id': 'c1', 'firstName': 'Janet'}, 'PUT', '/contacts/c1', {'firstName': 'Janet'}, 'contact'),
    ('delete_contact', {'contact_id': 'c1'}, 'DELETE', '/contacts/c1', None, 'empty'),
    ('archive_contact', {'contact_id': 'c1'}, 'PUT', '/contacts/c1/archive', None, 'contact'),
    ('unarchive_contact', {'contact_id': 'c1'}, 'PUT', '/contacts/c1/unarchive', None, 'contact'),
    ('send_message', {'contact_id': 'c1', 'text': 'Hello', 'runAt': '2026-12-01T10:00:00Z'}, 'POST', '/contacts/c1/send', {'text': 'Hello', 'runAt': '2026-12-01T10:00:00Z'}, 'message'),
    ('create_broadcast', {'contacts': ['c1'], 'templateId': 't1'}, 'POST', '/broadcasts', {'contacts': ['c1'], 'templateId': 't1'}, 'broadcast'),
    ('search_campaigns', {}, 'POST', '/campaigns/search', {'paging': {'page': 1, 'pageSize': 50}}, 'campaigns'),
    ('get_campaign', {'campaign_id': 'a1'}, 'GET', '/campaigns/a1', None, 'campaign'),
    ('add_contact_to_campaign', {'campaign_id': 'a1', 'contact_id': 'c1', 'eventDate': '2026-12-01'}, 'PUT', '/campaigns/a1/contacts/c1/add', {'eventDate': '2026-12-01'}, 'campaign'),
    ('remove_contact_from_campaign', {'campaign_id': 'a1', 'contact_id': 'c1'}, 'PUT', '/campaigns/a1/contacts/c1/remove', None, 'campaign'),
    ('search_templates', {'contentType': 'MessageTemplate'}, 'POST', '/templates/search', {'contentType': 'MessageTemplate', 'paging': {'page': 1, 'pageSize': 50}}, 'templates'),
    ('search_keywords', {}, 'POST', '/keywords/search', {'paging': {'page': 1, 'pageSize': 50}}, 'keywords'),
    ('get_custom_fields', {}, 'GET', '/customFields', None, 'fields'),
    ('get_contact_custom_fields', {'contact_id': 'c1'}, 'GET', '/contacts/c1/customFields', None, 'values'),
    ('update_contact_custom_field', {'contact_id': 'c1', 'custom_field_id': 'f1', 'value': 'New'}, 'PUT', '/contacts/c1/customFields/f1', {'value': 'New', 'requireValidCustomFields': True}, 'value'),
    ('add_tag_to_contacts', {'tag': 'Warm / Lead', 'contactIds': ['c1']}, 'PUT', '/tags/Warm%20%2F%20Lead/contacts/add', {'contactIds': ['c1']}, 'tag'),
    ('remove_tag_from_contacts', {'tag': 'Lead', 'contactIds': ['c1']}, 'PUT', '/tags/Lead/contacts/remove', {'contactIds': ['c1']}, 'tag'),
    ('get_credits', {}, 'GET', '/user/credits', None, 'credits'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,body,response', CASES, ids=[c[0] for c in CASES])
async def test_project_broadcast_requests(transport, operation, config, method, path, body, response):
    requests, replies = transport
    payload = b'' if response == 'empty' else FIXTURE[response]
    replies.append((200, payload))
    result = await run(operation, **config)
    assert result['status'] == 'success'
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.raw_path.decode() == '/api/v1' + path
    assert (json.loads(requests[0].content) if requests[0].content else None) == body
    if response != 'empty':
        assert result['data'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 409, 429, 500])
async def test_project_broadcast_rejections_preserve_provider_text_and_redact(transport, status):
    requests, replies = transport
    replies.append((status, {'error': 'Rejected key ' + KEY}))
    result = await run('test_connection')
    assert result == {'status': 'error', 'http_status': status, 'error': 'Rejected key [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_project_broadcast_does_not_retry_message(transport):
    requests, replies = transport
    replies.append(httpx.ReadTimeout('timed out'))
    with pytest.raises(ValueError, match='check its outcome'):
        await run('send_message', contact_id='c1', text='Hello')
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [b'<html>login</html>', [], {}, {'error': 'Invalid key'}])
async def test_project_broadcast_bad_identity(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    if isinstance(payload, dict) and 'error' in payload:
        assert (await run('test_connection'))['status'] == 'error'
    else:
        with pytest.raises(ValueError):
            await run('test_connection')


@pytest.mark.asyncio
async def test_project_broadcast_custom_field_clear(transport):
    requests, replies = transport
    replies.append((200, {'_id': 'f1', 'value': ''}))
    await run('update_contact_custom_field', contact_id='c1', custom_field_id='f1', value='')
    assert json.loads(requests[0].content) == {'value': '', 'requireValidCustomFields': True}


@pytest.mark.parametrize('operation,config', [
    ('send_message', {'contact_id': 'c1'}),
    ('create_broadcast', {'contacts': [], 'text': 'Hello'}),
    ('search_contacts', {'paging': {'page': 1, 'pageSize': 101}}),
    ('get_contact', {'contact': '..'}),
    ('send_message', {'contact_id': 'c1', 'text': 'Hello', 'runAt': 'tomorrow'}),
])
def test_project_broadcast_invalid_config(operation, config):
    assert not pb.ProjectBroadcastNode.validate_config({'config': {'operation': operation, **config}, 'credentials': AUTH})['valid']


def test_project_broadcast_manual_credential_and_evidence():
    credential = pb.ProjectBroadcastAPIKey(api_key=KEY)
    assert credential.credential_type == AUTH['credential_type']
    assert pb.ProjectBroadcastNode.connection_evidence.identity_operation == 'test_connection'
    assert pb.ProjectBroadcastNode.connection_evidence.identity_keys == ('name', 'phoneNumber')
    with pytest.raises(ValidationError):
        pb.ProjectBroadcastAPIKey(api_key='https://example.com/key')
