"""Offline SmartEmailing wire-contract and manual-credential regressions.

Exercises all operations through the native factory without a provider account.
Fixtures retain provider example values and separately label synthetic edge cases.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import smartemailing_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/smartemailing/requests.json').read_text())
CASES = FIXTURE['cases']
CREDENTIAL = {'username': 'fixture-user@example.com', 'api_key': 'synthetic-smartemailing-key'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='smartemailing-test', node_type='automation-smartemailing',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})


def transport(monkeypatch, response):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


def acknowledgement(operation, method):
    payload = {'status': 'ok' if method in {'GET', 'PUT'} else 'created'}
    if operation == 'import_contacts':
        payload.update(meta={}, contacts_map=[{'emailaddress': 'martin@smartemailing.cz', 'contact_id': 123}], double_opt_in_map=[])
    elif operation == 'get_account_info':
        payload['data'] = {'account_id': 2, 'username': 'martin@smartemailing.cz', 'company': 'Smartemailing s.r.o.'}
    elif operation.startswith('list_'):
        payload.update(data=[], meta={'total_count': 0, 'displayed_count': 0, 'offset': 0, 'limit': 100})
    elif operation == 'send_transactional_emails':
        payload.update(meta=[], data=[{'recipient': 'martin@smartemailing.cz', 'id': 'bb56f6cb1da34c42a70855e6179e0fa0'}])
    elif operation == 'trigger_events':
        payload.update(meta=[], data={'events': [{'emailaddress': 'someone@smartemailing.cz', 'id': '11ef3d003a1e96e28724eeb406d8477d', 'name': 'filled-form'}]})
    elif operation != 'change_email_address':
        payload['data'] = {'id': 1, 'name': 'Fruit'}
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_smartemailing_operations_use_exact_wire_contract(monkeypatch, case):
    code = 201 if case['method'] == 'POST' else 200
    payload = acknowledgement(case['operation'], case['method'])
    calls = transport(monkeypatch, lambda request: httpx.Response(code, json=payload))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['http_status'] == code
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.host == 'app.smartemailing.cz'
    assert request.url.path == '/api/v3' + case['path']
    assert request.headers['Authorization'] == 'Basic ' + base64.b64encode((CREDENTIAL['username'] + ':' + CREDENTIAL['api_key']).encode()).decode()
    if request.method == 'GET':
        assert dict(request.url.params) == case['expected']
        assert request.content == b''
    else:
        assert json.loads(request.content) == case['expected']
    if case['operation'] == 'send_transactional_emails':
        assert result['queued'] and result['delivery_verified'] is False
    if case['operation'] == 'trigger_events':
        assert result['automation_completion_verified'] is False


@pytest.mark.asyncio
async def test_smartemailing_page_is_bounded_and_preserves_meta(monkeypatch):
    payload = {'status': 'ok', 'meta': {'total_count': 21, 'displayed_count': 2, 'offset': 0, 'limit': 2},
               'data': [{'id': 1, 'name': 'First'}, {'id': 2, 'name': 'Second'}]}
    calls = transport(monkeypatch, payload)
    result = await node({'operation': 'list_contact_lists', 'limit': 2}).execute({})
    assert result['data'] == payload['data'] and result['meta'] == payload['meta']
    assert result['next_offset'] == 2 and len(calls) == 1
    payload['meta']['total_count'] = 2
    assert (await node({'operation': 'list_contact_lists', 'limit': 2}).execute({}))['next_offset'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 301, 401, 403, 422, 429, 500])
async def test_smartemailing_error_envelopes_preserve_provider_message_and_redact_key(monkeypatch, status):
    calls = transport(monkeypatch, lambda request: httpx.Response(status, json={'status': 'error', 'message': 'Authentication Failed ' + CREDENTIAL['api_key']}))
    result = await node({'operation': 'get_account_info'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['message'] == 'Authentication Failed [redacted]' and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'status': 'ok'}, {'status': 'ok', 'data': 'wrong'}])
async def test_smartemailing_malformed_read_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    try:
        result = await node({'operation': 'get_account_info'}).execute({})
    except ValueError:
        return
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_smartemailing_path_segments_cannot_change_route(monkeypatch):
    calls = transport(monkeypatch, {'status': 'ok', 'data': {}})
    await node({'operation': 'get_contact', 'emailaddress': 'test+tag@example.com?select=secret#x'}).execute({})
    assert not calls[0].url.query and not calls[0].url.fragment
    assert '%3F' in str(calls[0].url) and '%23' in str(calls[0].url)


def test_smartemailing_manual_credential_defaults_and_shapes():
    credential = native.SmartEmailingCredential.model_validate(CREDENTIAL)
    assert credential.credential_type == 'smartemailing_api_key'
    assert native.SmartEmailingCredential.model_validate({**CREDENTIAL, 'username': ' user@example.com '}).username == 'user@example.com'
    for fields in [{'username': 'a:b'}, {'api_key': 'https://example.com/key'}, {'api_key': '<token>'}]:
        with pytest.raises(ValidationError):
            native.SmartEmailingCredential.model_validate({**CREDENTIAL, **fields})


@pytest.mark.parametrize('config', [
    {'operation': 'import_contacts', 'data': []},
    {'operation': 'trigger_events', 'events': []},
    {'operation': 'create_email', 'title': 'No body'},
    {'operation': 'create_contact_list', 'name': 'My list', 'sendername': 'Martin'},
    {'operation': 'get_contact_list', 'id': 0},
    {'operation': 'list_contacts', 'limit': 501},
    {'operation': 'send_transactional_emails', 'sender_credentials': {'from': 'sender@example.com', 'reply_to': 'sender@example.com', 'sender_name': 'Sender'}, 'tag': 'transactional', 'email_id': 14, 'tasks': [{'recipient': {'emailaddress': 'recipient@example.com'}}] * 6},
])
def test_smartemailing_rejects_invalid_or_oversized_writes(config):
    with pytest.raises(ValueError):
        node(config)
