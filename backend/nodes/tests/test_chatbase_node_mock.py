"""Exercise Chatbase's fixed routes, manual credentials, evidence and error paths."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import chatbase_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/chatbase/contract.json').read_text())
KEY = 'chatbase-fixture-secret-key'
CREDENTIAL = {'credential_type': 'chatbase_api_key', 'api_key': KEY}


def node(config):
    return NodeFactory.create_node(node_id='chatbase-test', node_type='automation-chatbase',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, body=None, status=200, content=None, media='application/json'):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, **({'content': content} if content is not None else {'json': body}),
            headers={'content-type': media})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.parametrize('case', FIXTURE['operations'], ids=lambda c: c['operation'])
async def test_chatbase_contract_requests_through_factory(monkeypatch, case):
    requests = transport(monkeypatch, case['response'], case['response_status'])
    result = await node(case['config']).execute({})
    assert result == {'status': 'success', 'data': case['response']}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.scheme == 'https' and request.url.host == 'www.chatbase.co'
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    assert KEY not in str(request.url) and KEY not in str(result)
    if case['body'] is None:
        assert not request.content
    else:
        assert json.loads(request.content) == case['body']


@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_chatbase_provider_rejections_preserve_message_without_key(monkeypatch, status):
    requests = transport(monkeypatch, {'error': {'code': 'DENIED', 'message': 'Rejected ' + KEY}}, status)
    result = await node({'operation': 'list_agents'}).execute({})
    assert result == {'status': 'error', 'status_code': status, 'error': 'Rejected [redacted]'}
    assert len(requests) == 1


@pytest.mark.parametrize('body', [{'success': False}, {'error': 'Denied'}, None, 'invalid', []])
async def test_chatbase_invalid_connection_page_never_succeeds(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_agents'}).execute({})


async def test_chatbase_cursor_preserved_and_agent_choices(monkeypatch):
    payload = {'data': [{'id': 'agent-a', 'name': 'Support Bot'}, {'id': 'agent-b', 'name': 'Sales Bot'}],
        'pagination': {'cursor': 'opaque+/cursor==', 'hasMore': True, 'total': 3}}
    requests = transport(monkeypatch, payload)
    result = await native.ChatbaseNode.load_field_options('agent_id', CREDENTIAL, page_token='prior+/cursor==', search='support')
    assert result == {'options': [{'value': 'agent-a', 'label': 'Support Bot'}], 'next_page_token': 'opaque+/cursor=='}
    assert requests[0].url.params['cursor'] == 'prior+/cursor=='
    assert requests[0].url.params['limit'] == '100'
    assert native.ChatbaseNode.connection_evidence.field == 'agent_id'


async def test_chatbase_rejected_key_cannot_become_empty_agent_choices(monkeypatch):
    transport(monkeypatch, {'error': {'message': 'Authentication required'}}, 401)
    with pytest.raises(ValueError, match='Authentication required'):
        await native.ChatbaseNode.load_field_options('agent_id', CREDENTIAL)


@pytest.mark.parametrize('identifier', ['..', '.', 'a/b', 'a?x=1', 'a#x', 'a\\b'])
async def test_chatbase_path_cannot_change_route(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match='resource ID'):
        await node({'operation': 'get_agent', 'agent_id': identifier}).execute({})
    assert requests == []


async def test_chatbase_chat_is_nonstreaming_and_redacts_echo(monkeypatch):
    requests = transport(monkeypatch, {'data': {'reply': KEY, KEY: 'echo'}})
    result = await node({'operation': 'chat', 'agent_id': 'agent-a', 'message': 'Hello'}).execute({})
    assert json.loads(requests[0].content) == {'message': 'Hello', 'stream': False}
    assert KEY not in json.dumps(result)


async def test_chatbase_network_error_does_not_retry_write(monkeypatch):
    calls = []
    def client(**kwargs):
        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout('timeout with ' + KEY, request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='inspect the provider') as error:
        await node({'operation': 'create_agent', 'name': 'Support Bot'}).execute({})
    assert KEY not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize('content,media', [(b'<html>oops</html>', 'text/html'), (b'not json', 'application/json')])
async def test_chatbase_non_json_is_not_success(monkeypatch, content, media):
    transport(monkeypatch, content=content, media=media)
    with pytest.raises(ValueError, match='JSON'):
        await node({'operation': 'list_agents'}).execute({})


def test_chatbase_manual_credential_has_default_type_and_one_input():
    data, errors, resolved = shape_credential('chatbase_api_key', {'api_key': '  ' + KEY + '  '})
    assert resolved and not errors and data['api_key'] == KEY
    assert native.ChatbaseAPIKeyCredential(api_key=KEY).credential_type == 'chatbase_api_key'
    assert {name for name, field in native.ChatbaseAPIKeyCredential.model_fields.items() if field.is_required()} == {'api_key'}


@pytest.mark.parametrize('key', ['', 'Bearer some-key', 'https://example.com/token'])
def test_chatbase_invalid_key_refused(key):
    with pytest.raises(ValidationError):
        native.ChatbaseAPIKeyCredential(api_key=key)
