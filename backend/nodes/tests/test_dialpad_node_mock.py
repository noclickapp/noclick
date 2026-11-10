"""Exercise every Dialpad operation through real HTTP serialization and parsing.

Fixtures record official source URLs and distinguish verbatim examples from
schema-derived envelopes. These tests never contact Dialpad or create resources.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from nodes.dialpad_node import DialpadAPIKeyCredential, DialpadNode, DialpadNodeConfig

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/dialpad/responses.json').read_text())


def node(config):
    return DialpadNode(node_id='dialpad-test', node_type='automation-dialpad', node_data={},
                       config=DialpadNodeConfig(config=config, credentials={'api_key': 'dialpad-test-key'}),
                       sio=Mock(), sid='test', workflow_id='test', user_id='test')


async def execute(config, body, status=200, raw=None):
    requests = []
    def handle(request):
        requests.append(request)
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    original = httpx.AsyncClient
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        result = await node(config).execute({})
    return result, requests


# Sources: https://dialpad.com/static/openapi/platform-v1.0.json and
# https://developers.dialpad.com/docs/contact-events (each fixture includes its source and derivation).
@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_every_documented_operation(operation):
    case = FIXTURES[operation]
    result, requests = await execute(case['config'], case['body'])
    assert result['status'] == 'success', result
    assert result['action'] == operation
    assert result['data'] == (case['body'] if case['body'] is not None else {})
    assert result['timing_ms']['api_request'] >= 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    expected_path = case['path'].replace('{id}', str(case['config'].get('id', '')))
    assert request.url.path == expected_path
    assert request.url.host == 'dialpad.com'
    assert request.headers['Authorization'] == 'Bearer dialpad-test-key'
    assert 'apikey' not in request.url.params
    expected = {k: v for k, v in case['config'].items() if k not in ('operation', 'id')}
    if request.method == 'GET':
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in expected.items()}
        assert request.content == b''
    else:
        for key in ('phones', 'emails', 'to_numbers', 'labels', 'urls'):
            if key in expected:
                expected[key] = [item.strip() for item in expected[key].split(',') if item.strip()]
        if 'to_number' in expected:
            expected['to'] = {'number': expected.pop('to_number')}
        assert (json.loads(request.content) if request.content else {}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500])
async def test_provider_errors_preserved(status):
    result, _ = await execute({'operation': 'list_users'}, None, status, raw=b'{"error":"Token rejected"}')
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert result['error'] == '{"error":"Token rejected"}'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'error': 'Invalid key'}, {'errors': ['Forbidden']}, {'success': False}, {'status': 'failed'}, {'message': 'unexpected'}, {'items': ['not a user']}, [], None])
async def test_connection_probe_rejects_invalid_response(body):
    result, _ = await execute({'operation': 'list_users'}, body)
    assert result['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'items': []}, {'items': None}, {'items': [], 'cursor': 'next-page'}])
async def test_documented_empty_and_paginated_collections(body):
    result, _ = await execute({'operation': 'list_users'}, body)
    assert result['status'] == 'success'
    assert result['data'] == body


@pytest.mark.asyncio
async def test_cursor_and_explicit_false_are_sent():
    result, requests = await execute({'operation': 'list_calls', 'cursor': 'next-page', 'include_anonymized': False}, {'items': []})
    assert dict(requests[0].url.params) == {'cursor': 'next-page', 'include_anonymized': 'false'}
    assert result['status'] == 'success'


@pytest.mark.asyncio
async def test_contact_list_values_are_trimmed():
    _, requests = await execute({'operation': 'update_contact', 'id': '5908860123456789', 'emails': 'one@test.com, two@test.com'}, FIXTURES['update_contact']['body'])
    assert json.loads(requests[0].content) == {'emails': ['one@test.com', 'two@test.com']}


@pytest.mark.asyncio
async def test_contact_path_segment_is_encoded():
    _, requests = await execute({'operation': 'get_contact', 'id': 'a/b?c'}, FIXTURES['get_contact']['body'])
    assert requests[0].url.raw_path == b'/api/v2/contacts/a%2Fb%3Fc'


@pytest.mark.asyncio
async def test_invalid_json_is_structured_error():
    result, _ = await execute({'operation': 'get_company'}, None, raw=b'<html>not json</html>')
    assert result['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'id': '1'}, {'name': 'Test'}, {'id': '1', 'name': 'Test', 'error': 'Rejected'}])
async def test_company_identity_requires_account_fields(body):
    result, _ = await execute({'operation': 'get_company'}, body)
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_missing_credential_is_rejected():
    instance = node({'operation': 'get_company'})
    instance.config.credentials = None
    with pytest.raises(ValueError, match='API key'):
        await instance.execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'list_calls', 'target_id': 2},
    {'operation': 'send_sms', 'text': 'test', 'to_numbers': '+14155557777'},
    {'operation': 'send_sms', 'from_number': '+14155551001', 'text': 'test', 'to_numbers': ','},
    {'operation': 'send_sms', 'from_number': '+14155551001', 'text': 'test', 'to_numbers': ','.join(['+14155557777'] * 11)},
    {'operation': 'update_contact', 'id': '1'},
    {'operation': 'update_user', 'id': '2'},
    {'operation': 'list_users', 'first_name': 'sample', 'email': 'someemail3@test.com'},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises(ValidationError):
        node(config)


def test_connection_evidence_uses_argument_free_reads():
    evidence = DialpadNode.connection_evidence
    assert evidence.operation == 'list_users'
    assert evidence.identity_operation == 'get_company'
    assert DialpadNodeConfig(config={'operation': evidence.operation}).config.operation == 'list_users'


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_connection_seam_shows_users_or_company(empty):
    from nodes.core.connection_evidence import collect_evidence
    requests = []
    original = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        if request.url.path.endswith('/users'):
            body = {'items': []} if empty else FIXTURES['list_users']['body']
        else:
            body = FIXTURES['get_company']['body']
        return httpx.Response(200, json=body)
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        result = await collect_evidence(node_type='automation-dialpad', credential_data={'api_key': 'test-key'}, user_id='test-user', pool=Mock())
    assert result.reachable is True
    if empty:
        assert result.account_label == FIXTURES['get_company']['body']['name']
        assert len(requests) == 2
    else:
        assert result.samples
        assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_seam_reports_rejected_key():
    from nodes.core.connection_evidence import collect_evidence
    original = httpx.AsyncClient
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(lambda request: httpx.Response(401, text='Token rejected')), **kw)):
        result = await collect_evidence(node_type='automation-dialpad', credential_data={'api_key': 'test-key'}, user_id='test-user', pool=Mock())
    assert result.reachable is False
    assert 'Token rejected' in str(result)


@pytest.mark.asyncio
async def test_timeout_is_error_without_retry():
    original = httpx.AsyncClient
    requests = []
    def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout('Dialpad timed out', request=request)
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        result = await node(FIXTURES['send_sms']['config']).execute({})
    assert result['status'] == 'error'
    assert len(requests) == 1


def test_typed_api_key_uses_field_based_credential_schema():
    schema = DialpadNode.get_config_schema()
    credential = schema['$defs']['DialpadAPIKeyCredential']
    assert 'x-credential-type' not in credential
    assert credential['properties']['credential_type']['const'] == 'dialpad_api_key'
    assert credential['properties']['api_key']['ui:widget'] == 'password'
    assert DialpadAPIKeyCredential(api_key='test-key').credential_type == 'dialpad_api_key'
    generated = json.loads((Path(__file__).resolve().parents[3] / 'frontend/app/schemas/nodes/dialpad.json').read_text())
    assert generated['$defs']['DialpadAPIKeyCredential'] == credential


# Examples copied from Dialpad's call-events and sms-events documentation.
# A trailing comma in the published recap summary example was removed to parse its JSON.
EVENTS = json.loads((Path(__file__).parent / 'fixtures/dialpad/events.json').read_text())


def signed_event(body, secret='test-secret', algorithm='HS256'):
    import base64
    import hashlib
    import hmac
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b'=')
    message = encode(json.dumps({'alg': algorithm, 'typ': 'JWT'}).encode()) + b'.' + encode(json.dumps(body).encode())
    return message + b'.' + encode(hmac.new(secret.encode(), message, hashlib.sha256).digest())


@pytest.mark.parametrize('case', EVENTS.values(), ids=EVENTS.keys())
def test_documented_signed_events(case):
    event = case['body']
    config = {'operation': 'on_call', 'call_state': 'all', 'signing_secret': 'test-secret'} if 'call_id' in event else {
        'operation': 'on_sms', 'direction': 'all', 'signing_secret': 'test-secret'}
    body = signed_event(event)
    assert DialpadNode.verify_webhook_signature(body, {}, config)
    assert not DialpadNode.verify_webhook_signature(body + b' ', {}, config)
    assert not DialpadNode.verify_webhook_signature(body, {}, {**config, 'signing_secret': 'wrong'})
    assert not DialpadNode.verify_webhook_signature(signed_event(event, algorithm='none'), {}, config)
    assert not DialpadNode.verify_webhook_signature(json.dumps(event).encode(), {}, config)
    for raw in (body, body.decode()):
        payload = {'raw': raw}
        assert DialpadNode.filter_trigger_payload(payload, config)
        output = DialpadNode.resolve_trigger_payload(payload, config)
        assert output == event
        turn = DialpadNode.resolve_agent_event(output)
        assert str(event.get('call_id', event.get('id'))) in turn['text']
        assert 'Dialpad' in turn['text']


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,family', [('on_call', 'call'), ('on_sms', 'sms')])
async def test_webhook_registration_and_cleanup(operation, family):
    requests = []
    def handle(request):
        requests.append(request)
        if request.method == 'DELETE':
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'id': '193' if request.url.path.endswith('webhooks') else '5620703441190912'})
    original = httpx.AsyncClient
    config = {'operation': operation, 'target_id': 123, 'target_type': 'user'}
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        state = await DialpadNode._register_external_webhook(webhook_url='https://example.com/webhook', credential={'api_key': 'key'}, config=config, node_id='test')
        await DialpadNode._unregister_external_webhook(credential={'api_key': 'key'}, config={**config, **state}, node_id='test')
    assert json.loads(requests[0].content) == {'hook_url': 'https://example.com/webhook', 'secret': state['signing_secret']}
    subscription = json.loads(requests[1].content)
    assert subscription['endpoint_id'] == 193
    assert subscription['target_id'] == 123
    assert subscription['target_type'] == 'user'
    assert subscription.get('call_states') == (['hangup'] if family == 'call' else None)
    assert subscription.get('direction') == ('inbound' if family == 'sms' else None)
    assert [r.url.path for r in requests[2:]] == [f'/api/v2/subscriptions/{family}/5620703441190912', '/api/v2/webhooks/193']
    assert all(r.headers['Authorization'] == 'Bearer key' for r in requests)
    assert (await node({'operation': operation}).execute({}))['status'] == 'no_event'


@pytest.mark.asyncio
async def test_subscription_failure_removes_created_webhook():
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(400, json={'error': 'rejected'}) if '/subscriptions/' in request.url.path else httpx.Response(200, json={'id': '193'})
    original = httpx.AsyncClient
    with patch('nodes.dialpad_node.httpx.AsyncClient', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle), **kw)):
        with pytest.raises(httpx.HTTPStatusError):
            await DialpadNode._register_external_webhook(webhook_url='https://example.com', credential={'api_key': 'key'}, config={'operation': 'on_call'}, node_id='test')
    assert requests[-1].method == 'DELETE'
    assert requests[-1].url.path == '/api/v2/webhooks/193'


def test_trigger_filters_and_scope_fields():
    call = next(v['body'] for v in EVENTS.values() if v['body'].get('state') == 'hangup')
    sms = next(v['body'] for v in EVENTS.values() if v['body'].get('direction') == 'inbound' and 'id' in v['body'])
    assert not DialpadNode.filter_trigger_payload(call, {'operation': 'on_call', 'call_state': 'missed'})
    assert not DialpadNode.filter_trigger_payload(sms, {'operation': 'on_sms', 'direction': 'outbound'})
    assert not DialpadNode.filter_trigger_payload(sms, {'operation': 'on_call', 'call_state': 'all'})
    assert not DialpadNode.filter_trigger_payload(call, {'operation': 'on_sms', 'direction': 'all'})
    with pytest.raises(ValidationError, match='both target'):
        DialpadNodeConfig(config={'operation': 'on_call', 'target_id': 1})
    assert DialpadNode.registration_fingerprint_fields({'operation': 'on_sms', 'direction': 'inbound'}) != DialpadNode.registration_fingerprint_fields({'operation': 'on_sms', 'direction': 'outbound'})


@pytest.mark.asyncio
async def test_delivery_after_row_secret_fallback_with_stale_config():
    from utils.webhook_routes import _apply_trigger_node_hooks
    event = next(case['body'] for case in EVENTS.values() if case['body'].get('state') == 'hangup')
    body = signed_event(event, secret='new-row-secret')
    config = {'operation': 'on_call', 'call_state': 'hangup', 'signing_secret': 'old-config-secret'}
    trigger = {'type': 'automation-dialpad', 'id': 'test', 'config': config}
    assert await _apply_trigger_node_hooks(trigger, body, {}, webhook_secret='new-row-secret') is None
    assert DialpadNode.filter_trigger_payload({'raw': body}, config)
    assert DialpadNode.resolve_trigger_payload({'raw': body.decode()}, config) == event
