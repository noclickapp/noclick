"""Exercise Vybit's native node through the operation runner using provider examples.

HTTP stays local so writes, warnings, pagination and connection failures are deterministic.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import vybit_notifications_node as vybit
from nodes.core.run_op import run_node_operation
from utils import ssrf

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/vybit-notifications/contract_examples.json').read_text())['cases']
AUTH = {'credential_type': 'vybit_notifications_api_key', 'api_key': 'fixture-vybit-key'}
USER = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        calls.append(request)
        assert request.url.host == 'api.vybit.net'
        assert request.headers['X-API-Key'] == AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(vybit, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, config=None):
    return await run_node_operation(node_type='automation-vybit-notifications', operation=operation,
        arguments=config or {}, credential_data=AUTH, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', EXAMPLES, ids=lambda c: c['operation'])
async def test_vybit_notifications_contract_operations(transport, case):
    calls, replies = transport
    replies.append((case['status'], case['body']))
    result = await run(case['operation'], case['config'])
    assert result['data'] == case['body']
    assert len(calls) == 1 and replies == []
    request = calls[0]
    assert request.method == case['method']
    path = case['path']
    for name, value in case['config'].items():
        camel = ''.join(word.title() if i else word for i, word in enumerate(name.split('_')))
        path = path.replace('{' + camel + '}', str(value))
    assert request.url.path == '/v1' + path
    if request.method == 'GET':
        for key in ('offset', 'limit', 'search'):
            if key in case['config']:
                assert request.url.params[key] == str(case['config'][key])
    if request.method in {'PATCH', 'POST'}:
        payload = json.loads(request.content)
        assert not ({'operation', 'key', 'reminder_id'} & payload.keys())
        for key in ('image_url', 'link_url', 'sound_key', 'time_zone', 'run_once', 'trigger_type', 'trigger_settings', 'send_permissions'):
            if key in case['config']:
                camel = ''.join(word.title() if i else word for i, word in enumerate(key.split('_')))
                assert payload[camel] == case['config'][key]


@pytest.mark.asyncio
async def test_vybit_notifications_patch_preserves_explicit_null_without_clearing_unsupplied_fields(transport):
    calls, replies = transport
    replies.append((200, {'key': 'abc123def456', 'message': None}))
    await run('update_vybit_partial', {'key': 'abc123def456', 'message': None})
    assert json.loads(calls[0].content) == {'message': None}


@pytest.mark.asyncio
async def test_vybit_notifications_trigger_warning_is_not_delivery(transport):
    calls, replies = transport
    body = {'result': 0, 'warn': 'Vybit is off and will not be triggered'}
    replies.append((201, body))
    assert (await run('trigger_vybit', {'key': 'abc123def456'})) == {'data': body}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_vybit_notifications_pagination_is_explicit_and_does_not_fetch_more(transport):
    calls, replies = transport
    replies.append((200, [{'key': 'one'}, {'key': 'two'}]))
    result = await run('list_vybits', {'offset': 2, 'limit': 2})
    assert result['next_offset'] == 4
    assert len(calls) == 1
    replies.append((200, []))
    assert (await run('list_vybits', {'offset': 4, 'limit': 2}))['next_offset'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_vybit_notifications_provider_failures_preserve_message_without_leaking_key(transport, status):
    calls, replies = transport
    replies.append((status, {'error': 'rejected ' + AUTH['api_key']}))
    with pytest.raises(ValueError) as error:
        await run('get_profile')
    assert 'rejected' in str(error.value) and str(status) in str(error.value)
    assert AUTH['api_key'] not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_vybit_notifications_profile_must_identify_account(transport):
    _, replies = transport
    replies.append((200, {}))
    with pytest.raises(ValueError, match='incomplete account profile'):
        await run('get_profile')


@pytest.mark.parametrize('config', [
    {'operation': 'get_vybit', 'key': '../profile'},
    {'operation': 'get_vybit', 'key': 'a?b'},
    {'operation': 'list_vybits', 'limit': 101},
    {'operation': 'create_reminder', 'key': 'a', 'cron': '* * * * *'},
    {'operation': 'create_vybit', 'name': 'Alert', 'trigger_type': 'schedule'},
])
def test_vybit_notifications_invalid_input(config):
    assert not vybit.VybitNotificationsNode.validate_config({'config': config, 'credentials': AUTH})['valid']


def test_vybit_notifications_manual_credential_has_default_type():
    assert vybit.VybitNotificationsCredential(api_key=' user-key ').model_dump() == {
        'credential_type': 'vybit_notifications_api_key', 'api_key': 'user-key'}
