"""Native node execution with published request examples and intercepted HTTP."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import tik_hub_node as provider
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/tik-hub/operations.json').read_text())
TOKEN = 'synthetic-tikhub-token'
AUTH = {'credential_type': 'tik_hub_api_token', 'api_token': TOKEN}
ACCOUNT = {
    'code': 200,
    'router': '/api/v1/tikhub/user/get_user_info',
    'api_key_data': {'api_key_name': 'Develop Test', 'api_key_scopes': ['/api/v1/tikhub/user/'],
                     'created_at': '2024-05-22T06:07:12.495520', 'expires_at': None, 'api_key_status': 1},
    'user_data': {'email': 'example@example.com', 'balance': 100, 'free_credit': 100,
                  'email_verified': True, 'account_disabled': False, 'is_active': True},
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.tikhub.io'
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(provider.httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, config=None, auth=AUTH):
    return NodeFactory.create_node(node_id='tik-hub-test', node_type='automation-tik-hub',
        node_data={'config': {'operation': operation, **(config or {})}, 'credentials': auth})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_tik_hub_documented_operations(transport, operation):
    case = CASES[operation]
    payload = ACCOUNT if operation == 'get_account' else {'code': 200, 'data': {'items': [], 'cursor': 15, 'has_more': True}}
    transport[1].append((200, payload))
    result = await node(operation, case['config']).execute({})
    request, = transport[0]
    assert request.method == case['method'] and request.url.path == case['path']
    if request.method == 'POST':
        assert json.loads(request.content) == case['config']['urls']
        assert not request.url.query
    else:
        for key, value in case['config'].items():
            if value != '':
                assert request.url.params[key] == str(value)
            else:
                assert key not in request.url.params
        assert not request.content
    assert result['status'] == 'success'
    if operation == 'get_account':
        assert result['name'] == 'example@example.com' and result['data'] == ACCOUNT['user_data']
    else:
        assert result['data'] == payload
    assert not transport[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_tik_hub_http_errors_fail(transport, status):
    transport[1].append((status, {'message': 'Denied'}))
    with pytest.raises(httpx.HTTPStatusError):
        await node('get_account').execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'code': 403, 'message': 'Denied'}, {'code': 200, 'user_data': {}}])
async def test_tik_hub_unconfirmed_account_fails(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await node('get_account').execute({})


@pytest.mark.asyncio
async def test_tik_hub_rejection_redacts_token(transport):
    transport[1].append((200, {'code': 401, 'message': 'Rejected ' + TOKEN}))
    with pytest.raises(ValueError) as error:
        await node('get_daily_usage').execute({})
    assert TOKEN not in str(error.value)


def test_tik_hub_credentials_and_batch_bounds():
    assert NODE_REGISTRY['automation-tik-hub'] is provider.TikHubNode
    assert provider.TikHubCredential(api_token='  real-example-key  ').api_token == 'real-example-key'
    assert provider.TikHubCredential(api_token=TOKEN).credential_type == 'tik_hub_api_token'
    for invalid in ['Bearer secret', 'https://example.com/token', '<token>', '']:
        with pytest.raises(ValidationError):
            provider.TikHubCredential(api_token=invalid)
    with pytest.raises(ValidationError):
        provider.ExtractTiktokUserIdsConfig(urls=['https://www.tiktok.com/@tiktok'] * 11)
    with pytest.raises(ValidationError):
        provider.GetTiktokVideoConfig(itemId='')
    with pytest.raises(ValidationError):
        provider.ListTiktokPostsConfig(secUid='example-user', count=16)
