"""Exercise real registry-created nodes against published provider examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import phone_harness_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/phone-harness/documented.json').read_text())
KEY = 'pck_unit_fixture_only'


def node(config):
    return NodeFactory.create_node(node_id='phone-harness-test', node_type=native.NODE_TYPE,
        node_data={'config': config, 'credentials': {'credential_type': 'phone_harness_api_key', 'api_key': KEY}})


def transport(monkeypatch, reply):
    calls = []
    def respond(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_published_json_examples_and_one_request_per_operation(monkeypatch, operation):
    fixture = EXAMPLES[operation]
    config = {'operation': operation}
    if '{sid}' in fixture['path']:
        config['sid'] = 'abc123def456'
    if operation == 'recover_create_request':
        config['request_key'] = 'example-request-key-0001'
    if operation == 'reset_device':
        config['device_id'] = 'iph-622c376ba7'
    if operation == 'revoke_api_key':
        config['key_hash'] = 'b' * 64
    if operation == 'create_session':
        config.update(timeout_seconds=900, idempotency_key='example-request-key-0001')
    status = 202 if operation in {'create_session', 'reset_device'} else 201 if operation in {'create_api_key', 'enable_adb', 'reset_adb'} else 200
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json=fixture['body']))
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert result['data'] == fixture['body']
    assert result['http_status'] == status
    assert len(calls) == 1
    request = calls[0]
    assert request.method == fixture['method']
    assert request.url.host == 'api.phone-harness.com'
    expected_path = fixture['path'].replace('{sid}', 'abc123def456').replace('{id}', 'iph-622c376ba7').replace('{request_key}', 'example-request-key-0001')
    assert request.url.path == expected_path
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    if operation == 'create_session':
        assert json.loads(request.content) == {'timeout_seconds': 900}
        assert request.headers['Idempotency-Key'] == 'example-request-key-0001'
        assert result['data']['state'] == 'provisioning'
    elif operation == 'create_api_key':
        assert json.loads(request.content) == {}
    elif operation == 'revoke_api_key':
        assert json.loads(request.content) == {'key_hash': 'b' * 64}
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_history_cursor_passed_unchanged(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json={'items': [], 'next_cursor': 'next'}))
    result = await node({'operation': 'list_history_page', 'limit': 100, 'cursor': 'a+/= opaque'}).execute({})
    assert dict(calls[0].url.params) == {'limit': '100', 'cursor': 'a+/= opaque'}
    assert result['data']['next_cursor'] == 'next'


@pytest.mark.asyncio
async def test_create_saved_phone_body(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(202, json=EXAMPLES['create_session']['body']))
    await node({'operation': 'create_session', 'platform': 'android', 'kind': 'emulator',
        'profile_id': 'prof-3f9c2a1b7d5e4c6a8b0f1e2d'}).execute({})
    assert json.loads(calls[0].content) == {'platform': 'android', 'kind': 'emulator', 'profile_id': 'prof-3f9c2a1b7d5e4c6a8b0f1e2d'}


@pytest.mark.asyncio
async def test_pending_cleanup_is_not_claimed_released(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(202, json={'released': False, 'cleanup_pending': True}))
    result = await node({'operation': 'end_session', 'sid': 'abc123def456'}).execute({})
    assert result['data'] == {'released': False, 'cleanup_pending': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 409, 429, 500, 302])
async def test_provider_rejection_preserved_without_key_or_retry(monkeypatch, status):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json={'error': 'Provider refused ' + KEY}))
    result = await node({'operation': 'get_account'}).execute({})
    assert result == {'status': 'error', 'error': 'Provider refused [redacted]', 'http_status': status}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_create_timeout_never_retries(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('timeout', request=request)
    calls = transport(monkeypatch, timeout)
    with pytest.raises(httpx.ReadTimeout):
        await node({'operation': 'create_session', 'idempotency_key': 'example-request-key-0001'}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['not JSON', '[]'])
async def test_non_json_content_type_refused(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, text=body))
    with pytest.raises(ValueError, match='JSON'):
        await node({'operation': 'get_account'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'create_session', 'platform': 'android'},
    {'operation': 'create_session', 'timeout_seconds': 0},
    {'operation': 'create_session', 'idempotency_key': 'short'},
    {'operation': 'get_session', 'sid': '../me'},
    {'operation': 'list_history_page', 'limit': 101},
    {'operation': 'revoke_api_key', 'key_hash': 'raw-secret'},
])
def test_invalid_inputs_rejected_before_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_evidence():
    cred = native.PhoneHarnessAPIKeyCredential(api_key='  pck_unit_fixture_only  ')
    assert cred.credential_type == 'phone_harness_api_key'
    assert cred.api_key == KEY
    assert native.PhoneHarnessNode.connection_evidence.identity_operation == 'get_account'
    with pytest.raises(ValidationError):
        native.PhoneHarnessAPIKeyCredential(api_key='Bearer ' + KEY)


@pytest.mark.asyncio
async def test_session_startup_error_is_a_documented_session_field(monkeypatch):
    body = {**EXAMPLES['get_session']['body'], 'state': 'error', 'error': 'Phone startup failed'}
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = await node({'operation': 'get_session', 'sid': 'abc123def456'}).execute({})
    assert result['status'] == 'success'
    assert result['data']['state'] == 'error'
    assert result['data']['error'] == 'Phone startup failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'uid': None}, {'name': 'Only a name'}])
async def test_account_evidence_requires_documented_identity(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError, match='account identity'):
        await node({'operation': 'get_account'}).execute({})
