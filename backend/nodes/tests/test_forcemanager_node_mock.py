"""Exercise every advertised operation with the provider's v4 examples."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nodes import forcemanager_node as fm
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/forcemanager/operations.json').read_text())
CREDENTIAL = {'credential_type': 'forcemanager_session_key', 'session_key': 'fixture-session-key-123'}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def respond(request):
        requests.append(request)
        status, body, content_type = replies.pop(0)
        return httpx.Response(status, json=body, headers={'Content-Type': content_type})

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as instance:
            yield instance

    monkeypatch.setattr(fm, 'guarded_async_client', client)
    return requests, replies


async def run(config):
    node = NodeFactory.create_node(node_id='forcemanager-test', node_type='automation-forcemanager',
                                  node_data={'config': config, 'credentials': CREDENTIAL})
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_documented_operation(operation, transport):
    case = CASES[operation]
    requests, replies = transport
    replies.append((200, case['response'], 'application/json'))
    result = await run(case['config'])
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url.copy_with(query=None)) == fm.BASE_URL + case['path']
    assert request.headers['X-Session-Key'] == CREDENTIAL['session_key']
    assert request.headers['Content-Type'] == 'application/json'
    if case['method'] in {'POST', 'PUT'}:
        assert json.loads(request.content) == {k: v for k, v in case['config'].items() if k not in {'operation', 'record_id'}}
    if operation.startswith('list_'):
        assert result['items'] == case['response']
        assert request.url.params['page'] == '0'
        assert request.headers['Count'] == '50'
    else:
        assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_filters_and_explicit_pagination(transport):
    requests, replies = transport
    replies.append((200, [], 'application/json'))
    result = await run({'operation': 'list_accounts', 'page': 2, 'count': 10,
                        'where': "name LIKE 'Acme%'", 'order': 'name', 'lang': 'en'})
    assert result['next_page'] is None
    assert dict(requests[0].url.params) == {'page': '2', 'where': "name LIKE 'Acme%'", 'order': 'name', 'lang': 'en'}
    assert requests[0].headers['Count'] == '10'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,content_type', [
    (401, {'error': 'fixture-session-key-123'}, 'application/json'),
    (429, {'error': 'rate limited'}, 'application/json'),
    (302, {}, 'application/json'),
    (200, {}, 'text/html'),
    (200, {'error': 'failure'}, 'application/json'),
    (200, {'Message': 'failure'}, 'application/json'),
    (200, [{'name': 'Missing ID'}], 'application/json'),
])
async def test_failures_are_not_success_or_secret_echoes(transport, status, body, content_type):
    transport[1].append((status, body, content_type))
    result = await run({'operation': 'list_accounts'})
    assert result['status'] == 'error'
    assert CREDENTIAL['session_key'] not in json.dumps(result)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'id': 999}, {'Message': 'entity created'}, {'id': 1, 'Message': 'error'}])
async def test_write_requires_documented_acknowledgement(transport, body):
    transport[1].append((200, body, 'application/json'))
    result = await run(CASES['create_account']['config'])
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_mismatched_record_rejected(transport):
    transport[1].append((200, {'id': 2}, 'application/json'))
    assert (await run({'operation': 'get_account', 'record_id': 1}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'get_account', 'record_id': '../users'},
    {'operation': 'get_account', 'record_id': 0},
    {'operation': 'list_accounts', 'page': -1},
    {'operation': 'list_accounts', 'count': 1001},
    {'operation': 'update_account', 'record_id': 1},
    {'operation': 'update_account', 'record_id': 1, 'name': 'Unsupported by pinned PUT schema'},
    {'operation': 'create_account', 'name': 'Missing branch and owner'},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        fm.ForcemanagerNode.parse_config({'config': config, 'credentials': CREDENTIAL})


@pytest.mark.parametrize('key', ['https://example.com/key', '{{ secret }}', 'abc\r\nInjected: yes'])
def test_invalid_key(key):
    with pytest.raises(ValueError):
        fm.ForcemanagerSessionKeyCredential(session_key=key)


def test_manual_credential_default_and_evidence():
    assert fm.ForcemanagerSessionKeyCredential(session_key='fixture-session-key-123').credential_type == 'forcemanager_session_key'
    assert fm.ForcemanagerNode.connection_evidence.operation == 'list_accounts'
    assert len(fm.OPERATIONS) == 25
