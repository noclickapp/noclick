"""Published LINE examples through the real node factory; all credentials synthetic."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import line_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/line/messaging-examples.json').read_text())
TOKEN = 'synthetic-line-channel-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='line-fixture', node_type='automation-line', node_data={
        'config': config, 'credentials': {'channel_access_token': TOKEN}})

def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_published_examples_route_auth_body(monkeypatch, operation):
    example = EXAMPLES[operation]
    config = example['config']
    calls = transport(monkeypatch, example['body'])
    result = await node(config).execute({})
    assert result['success'] and result['data'] == example['body']
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example['method']
    assert request.url.host == 'api.line.me'
    path = example['path']
    for key, wire in {'user_id':'userId','room_id':'roomId','group_id':'groupId','rich_menu_id':'richMenuId'}.items():
        path = path.replace('{' + wire + '}', config.get(key, ''))
    assert request.url.path == path
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if 'text' in config:
        body = json.loads(request.content)
        assert body['messages'] == [{'type':'text', 'text': config['text']}]
        assert body['notificationDisabled'] is False
        if 'to' in config: assert body['to'] == config['to']
        if 'reply_token' in config: assert body['replyToken'] == config['reply_token']
    else:
        assert request.content == b''
    if example['method'] != 'GET':
        assert result['accepted'] is True and result['effect_verified'] is False
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_pagination_is_explicit_single_page(monkeypatch):
    calls = transport(monkeypatch, {'userIds': ['U1'], 'next': 'opaque-next'})
    result = await node({'operation':'list_followers','start':'opaque-before','limit':1}).execute({})
    assert dict(calls[0].url.params) == {'start':'opaque-before','limit':'1'}
    assert len(calls) == 1 and result['next_page_token'] == 'opaque-next'

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302,400,401,403,429,500])
async def test_failure_never_reports_acceptance_or_leaks_token(monkeypatch,status):
    calls = transport(monkeypatch, {'message': 'Rejected ' + TOKEN}, status)
    result = await node(EXAMPLES['push_message']['config']).execute({})
    assert result['status'] == 'error' and result['success'] is False
    assert result['write_outcome'] == 'unverified' and TOKEN not in str(result)
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_malformed_identity_is_not_connection_proof(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match='could not be read'):
        await node({'operation':'get_bot_info'}).execute({})

@pytest.mark.asyncio
async def test_timeout_does_not_retry_write(monkeypatch):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret ' + TOKEN, request=request)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs))
    with pytest.raises(ValueError, match='inspect any write') as error:
        await node(EXAMPLES['push_message']['config']).execute({})
    assert len(calls) == 1 and TOKEN not in str(error.value)

@pytest.mark.parametrize('token', ['https://example.com','<token>','Bearer abc','abc\r\nHeader: x'])
def test_bad_manual_tokens_rejected(token):
    with pytest.raises(ValidationError):
        native.LineTokenCredential(channel_access_token=token)

def test_credential_has_default_and_unicode_limit_is_utf16():
    credential = native.LineTokenCredential(channel_access_token='  ' + TOKEN + '  ')
    assert credential.credential_type == 'line_channel_access_token'
    assert credential.channel_access_token == TOKEN
    with pytest.raises(ValidationError):
        native.LineBroadcastMessageConfig(text='😀' * 2501)
    assert native.LineBroadcastMessageConfig(text='Hello\nworld').text == 'Hello\nworld'


@pytest.mark.asyncio
async def test_accidentally_echoed_token_is_redacted_everywhere(monkeypatch):
    transport(monkeypatch, {'userIds': [], 'next': TOKEN})
    result = await node({'operation': 'list_followers'}).execute({})
    assert TOKEN not in str(result)
    assert result['next_page_token'] == '[redacted]'
