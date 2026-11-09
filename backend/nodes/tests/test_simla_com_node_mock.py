"""Offline native-factory checks against Simla.com's Bot API contract."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import simla_com_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'simla-fixture-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='simla-test', node_type='automation-simla-com',
        node_data={'config': config, 'credentials': credentials or {
            'credential_type': 'simla_com_bot_token', 'bot_token': TOKEN}})


def transport(monkeypatch, data, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=data)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ({'operation': 'update_bot', 'name': 'Demo bot'}, 'PATCH', '/my/info', {'name': 'Demo bot'}),
    ({'operation': 'assign_dialog', 'dialog_id': 1, 'user_id': 1}, 'PATCH', '/dialogs/1/assign', {'user_id': 1}),
    ({'operation': 'unassign_dialog', 'dialog_id': 1}, 'PATCH', '/dialogs/1/unassign', None),
    ({'operation': 'close_dialog', 'dialog_id': 1}, 'DELETE', '/dialogs/1/close', None),
    ({'operation': 'add_dialog_tags', 'dialog_id': 1, 'tags': [{'name': 'Important', 'color_code': 'blue'}]}, 'PATCH', '/dialogs/1/tags/add', {'tags': [{'name': 'Important', 'color_code': 'blue'}]}),
    ({'operation': 'remove_dialog_tags', 'dialog_id': 1, 'tags': [{'name': 'Important'}]}, 'PATCH', '/dialogs/1/tags/delete', {'tags': [{'name': 'Important'}]}),
    ({'operation': 'create_dialog', 'chat_id': 1, 'user_id': 43}, 'POST', '/chats/1/dialogs', {'user_id': 43}),
    ({'operation': 'send_message', 'chat_id': 123, 'content': 'Hello!'}, 'POST', '/messages', {'chat_id': 123, 'content': 'Hello!', 'scope': 'public', 'type': 'text'}),
    ({'operation': 'edit_message', 'message_id': 100, 'content': 'Hello!'}, 'PATCH', '/messages/100', {'content': 'Hello!'}),
    ({'operation': 'delete_message', 'message_id': 100}, 'DELETE', '/messages/100', None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES)
async def test_simla_com_writes_make_one_exact_request(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, {'message_id': 1, 'time': '2026-11-09T00:00:00Z'} if config['operation'] == 'send_message' else {})
    result = await node(config).execute({})
    assert result['acknowledged'] and not result['delivery_verified']
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and str(req.url) == native.BASE_URL + path
    assert req.headers['X-Bot-Token'] == TOKEN
    assert (json.loads(req.content) if req.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', [op for op in native.ROUTES if op.startswith('list_')])
async def test_simla_com_lists_preserve_page_and_bounds(monkeypatch, operation):
    requests = transport(monkeypatch, [{'id': 1, 'name': 'My channel'}])
    result = await node({'operation': operation, 'limit': 1, 'since_id': 1, 'until_id': 9}).execute({})
    assert result['data'][0]['id'] == 1 and result['may_have_more'] and not result['complete']
    assert len(requests) == 1 and requests[0].method == 'GET'
    assert requests[0].url.path == '/api/bot/v1' + native.ROUTES[operation][1]
    assert dict(requests[0].url.params) == {'limit': '1', 'since_id': '1', 'until_id': '9'}
    assert requests[0].headers['X-Bot-Token'] == TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 500])
async def test_simla_com_errors_never_succeed_or_echo_token(monkeypatch, status):
    requests = transport(monkeypatch, {'errors': ['rejected ' + TOKEN]}, status)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_channels'}).execute({})
    assert TOKEN not in str(exc.value) and 'rejected' in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_simla_com_rejects_nonlist_and_redacts_output(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match='list response'):
        await node({'operation': 'list_channels'}).execute({})
    transport(monkeypatch, [{'id': 1, 'name': TOKEN}])
    assert TOKEN not in str(await node({'operation': 'list_channels'}).execute({}))


def test_simla_com_credentials_default_and_input_guards():
    assert native.SimlaComBotTokenCredential(bot_token=TOKEN).credential_type == 'simla_com_bot_token'
    for token in ['https://example.com/token', 'header with spaces']:
        with pytest.raises(ValidationError):
            native.SimlaComBotTokenCredential(bot_token=token)
    for cls, args in [(native.AssignDialog, {'dialog_id': 1}),
                      (native.SendMessage, {'chat_id': 0, 'content': 'Hello!'}),
                      (native.AddDialogTags, {'dialog_id': 1, 'tags': []})]:
        with pytest.raises(ValidationError):
            cls(**args)
