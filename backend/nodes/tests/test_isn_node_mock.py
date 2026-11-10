"""Synthetic transport tests for ISN JSON API 1.1.0; no account is used."""
import base64
from pathlib import Path
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import isn_node as native
from nodes.core.registry import NodeFactory

ACCESS = 'synthetic-isn-access-42'
SECRET = 'synthetic-isn-secret-42'
BASE = 'https://goisn.net/greenway/json'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {'credential_type': 'isn_api_key', 'api_base_url': BASE,
            'access_key': ACCESS, 'secret_key': SECRET, **changes}


def node(config):
    return NodeFactory.create_node(node_id='isn-test', node_type='automation-isn',
        node_data={'config': config, 'credentials': credential()})


def transport(monkeypatch, body, status=200, *, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = json.loads((Path(__file__).parent / 'fixtures/isn/requests.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['config']['operation'])
async def test_isn_each_operation_has_one_contract_request(monkeypatch, case):
    requests = transport(monkeypatch, case['response'], case.get('status', 200))
    result = await node(case['config']).run({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url).split('?')[0] == BASE + case['path']
    assert dict(request.url.params) == case.get('query', {})
    assert request.headers['authorization'] == 'Basic ' + base64.b64encode((ACCESS + ':' + SECRET).encode()).decode()
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    assert ACCESS not in str(result) and SECRET not in str(result)
    if request.method != 'GET':
        assert result['write_acknowledged'] and result['readback_verified'] is False
    if isinstance(case['response'], list):
        assert result['count'] == len(case['response'])


@pytest.mark.asyncio
async def test_isn_account_evidence_names_current_user(monkeypatch):
    requests = transport(monkeypatch, {'me': {'id': 'user-42', 'display': 'Pat Inspector'}})
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['data']['display'] == 'Pat Inspector'
    assert requests[0].url.path.endswith('/me')
    assert native.ISNNode.connection_evidence.identity_operation == 'get_current_user'


@pytest.mark.asyncio
@pytest.mark.parametrize('body,status', [({'status': 'error', 'message': 'Key rejected'}, 401),
    ({'status': 'error', 'description': 'Access denied'}, 200),
    ({'error': 'Not allowed'}, 403), ({'status': 'error', 'message': 'Rate limited'}, 429)])
async def test_isn_provider_rejections_remain_errors_and_never_retry(monkeypatch, body, status):
    requests = transport(monkeypatch, body, status)
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == body.get('message', body.get('description', body.get('error')))
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'me': {}}, {'me': []}, [], {'me': 'user'}])
async def test_isn_malformed_identity_does_not_verify(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'orders': []}, [1]])
async def test_isn_malformed_list_is_not_success(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'list_clients'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_isn_keys_are_redacted_in_success_and_errors(monkeypatch):
    transport(monkeypatch, {'me': {'display': 'Pat', 'notes': ACCESS + SECRET}})
    result = await node({'operation': 'get_current_user'}).execute({})
    assert ACCESS not in str(result) and SECRET not in str(result)
    transport(monkeypatch, {'message': 'Denied ' + ACCESS + SECRET}, 403)
    result = await node({'operation': 'cancel_order', 'order_id': 'order-42'}).execute({})
    assert ACCESS not in str(result) and SECRET not in str(result)
    assert result['write_outcome'] == 'unverified' and 'write_acknowledged' not in result


@pytest.mark.asyncio
async def test_isn_redirect_html_and_transport_failure_do_not_claim_write(monkeypatch):
    for status, headers in [(302, {'location': 'https://other.test'}), (200, {'content-type': 'text/html'})]:
        requests = transport(monkeypatch, {}, status, headers=headers)
        result = await node({'operation': 'cancel_order', 'order_id': 'order-42'}).execute({})
        assert result['status'] == 'error' and result['write_outcome'] == 'unverified'
        assert len(requests) == 1
    def client(**kwargs):
        def fail(request):
            raise httpx.ReadTimeout('timeout', request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node({'operation': 'cancel_order', 'order_id': 'order-42'}).execute({})
    assert result['write_outcome'] == 'unverified' and result['status'] == 'error'


@pytest.mark.parametrize('url', ['http://goisn.net/greenway/json', 'https://goisn.net.evil.test/greenway/json',
    'https://127.0.0.1/greenway/json', 'https://goisn.net:443/greenway/json',
    'https://name:pass@goisn.net/greenway/json', 'https://goisn.net/greenway/json?secret=x',
    'https://goisn.net/greenway/json#fragment', 'https://goisn.net/greenway/../json'])
def test_isn_refuses_non_provider_and_ambiguous_account_urls(url):
    with pytest.raises(ValidationError):
        native.ISNAPIKeyCredential.model_validate(credential(api_base_url=url))


def test_isn_manual_connect_defaults_type_and_normalizes_pastes():
    data = credential(api_base_url=BASE + '/', access_key=' ' + ACCESS + '\n')
    data.pop('credential_type')
    parsed = native.ISNAPIKeyCredential.model_validate(data)
    assert parsed.credential_type == 'isn_api_key' and parsed.api_base_url == BASE
    assert parsed.access_key == ACCESS


@pytest.mark.parametrize('value', ['https://example.test/key', '<token>', 'bad:key', 'bad\nkey', 'bad key'])
def test_isn_invalid_key_is_rejected(value):
    with pytest.raises(ValidationError):
        native.ISNAPIKeyCredential.model_validate(credential(access_key=value))


@pytest.mark.parametrize('config', [
    {'operation': 'get_order', 'order_id': '../me'}, {'operation': 'get_order', 'order_id': 'one?key=x'},
    {'operation': 'list_orders', 'start': 'yesterday', 'end': 'tomorrow'},
    {'operation': 'list_orders'}, {'operation': 'update_order', 'order_id': 'order-42'},
    {'operation': 'update_service', 'service_id': 'service-42'},
    {'operation': 'get_current_user', 'route': '/arbitrary'},
])
def test_isn_invalid_configs_fail_before_transport(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['config']['operation'])
def test_isn_request_fixtures_satisfy_published_parameter_and_body_schemas(case):
    """Validate fields independently of the spec's undefined auth scheme.

    The conformance harness still checks the unchanged complete pin and reports
    the auth defect. This separate check catches body/query defects that its
    security-scheme lookup would otherwise mask.
    """
    import re
    from jsonschema import Draft4Validator, FormatChecker, RefResolver
    contract = json.loads((Path(__file__).parent / 'fixtures/isn/contract.json').read_text())
    matches = [(path, methods[case['method'].lower()]) for path, methods in contract['paths'].items()
               if case['method'].lower() in methods and re.fullmatch(re.sub(r'\{[^}]+\}', '[^/]+', path), case['path'])]
    assert len(matches) == 1
    path, operation = matches[0]
    assert operation['security'] == [{'UserSecurity': []}]
    assert 'securitySchemes' not in contract['components']
    query = case.get('query', {})
    parameters = {p['name']: p for p in operation.get('parameters', []) if p['in'] == 'query'}
    assert not set(query) - parameters.keys()
    assert {k for k, p in parameters.items() if p.get('required')} <= query.keys()
    resolver = RefResolver.from_schema(contract)
    for key, value in query.items():
        schema = parameters[key]['schema']
        if schema.get('type') == 'boolean':
            assert value in {'true', 'false'}
            value = value == 'true'
        Draft4Validator(schema, resolver=resolver, format_checker=FormatChecker()).validate(value)
    request_body = operation.get('requestBody')
    if request_body:
        assert 'body' in case
        schema = request_body['content']['application/json']['schema']
        Draft4Validator(schema, resolver=resolver, format_checker=FormatChecker()).validate(case['body'])
    else:
        assert 'body' not in case


EVENTS = json.loads((Path(__file__).parent / 'fixtures/isn/webhook-events.json').read_text())
REST_CONTRACT = json.loads((Path(__file__).parent / 'fixtures/isn/rest-openapi.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,event', [('on_order_event', 'OrderCompleted'), ('on_order_status_changed', 'OrderStatusChanged')])
async def test_isn_webhook_lifecycle_uses_official_rest_contract(monkeypatch, operation, event):
    from jsonschema import Draft202012Validator, RefResolver
    bodies = [{'status': 'ok', 'webhook': {'id': 'hook-42'}, 'secret': 'a' * 64}, {'status': 'ok'}]
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(201 if request.method == 'POST' else 200, json=bodies.pop(0))
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    config = {'operation': operation, 'office_id': 'office-42', 'order_id': 'order-42'}
    if operation == 'on_order_event':
        config['event_type'] = event
    registration = await native.ISNNode._register_external_webhook(webhook_url='https://hooks.example.test/isn', credential=credential(), config=config, node_id='test')
    assert registration == {'external_webhook_id': 'hook-42', 'signing_secret': 'a' * 64}
    await native.ISNNode._unregister_external_webhook(credential=credential(), config={**config, **registration}, node_id='test')
    assert [r.method for r in requests] == ['POST', 'DELETE']
    assert [r.url.path for r in requests] == ['/greenway/rest/webhooks', '/greenway/rest/webhooks/hook-42']
    assert all(dict(r.url.params) == {'office': 'office-42'} for r in requests)
    body = json.loads(requests[0].content)
    assert body == {'url': 'https://hooks.example.test/isn', 'name': 'NoClick test', 'events': [event], 'method': 'POST', 'signed': True, 'track': True, 'order': 'order-42'}
    schema = REST_CONTRACT['paths']['/webhooks']['post']['requestBody']['content']['application/json']['schema']
    Draft202012Validator(schema, resolver=RefResolver.from_schema(REST_CONTRACT)).validate(body)
    assert all(r.headers['authorization'] == 'Basic ' + base64.b64encode((ACCESS + ':' + SECRET).encode()).decode() for r in requests)
    assert not requests[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize('body,status', [({'status': 'error'}, 403), ({'status': 'ok', 'webhook': {'id': 'hook-42'}, 'secret': 'a' * 64}, 302), ({'status': 'ok', 'webhook': {'id': 'hook-42'}}, 201), ({'status': 'ok', 'secret': 'a' * 64}, 201)])
async def test_isn_registration_requires_success_id_and_secret(monkeypatch, body, status):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError):
        await native.ISNNode._register_external_webhook(webhook_url='https://hooks.example.test/isn', credential=credential(), config={'operation': 'on_order_event'}, node_id='test')


def test_isn_signature_matches_documented_scheme_and_rejects_tampering(monkeypatch):
    import hashlib
    import hmac
    raw = json.dumps(EVENTS['ORDER_COMPLETED']['body']).encode()
    timestamp = '1790368200'
    monkeypatch.setattr(native.time, 'time', lambda: int(timestamp))
    config = {'signing_secret': 'ab' * 32}  # UTF-8 key, not hex-decoded.
    signature = hmac.new(config['signing_secret'].encode(), timestamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    headers = {'X-ISN-Signature': f't={timestamp},v1={signature}'}
    verify = native.ISNNode.verify_webhook_signature
    assert verify(raw, headers, config)
    assert verify(raw, {k.lower(): v for k, v in headers.items()}, config)
    assert not verify(raw + b' ', headers, config)
    assert not verify(raw, headers, {'signing_secret': 'other'})
    assert not verify(raw, headers, {})
    for header in ['', 't=invalid,v1=abc', 't=²,v1=abc', 't=' + '9' * 5000 + ',v1=abc', f't={timestamp},v1=bad', f't={timestamp},v1=é']:
        assert not verify(raw, {'x-isn-signature': header}, config)
    for offset in [-301, 301]:
        monkeypatch.setattr(native.time, 'time', lambda: int(timestamp) + offset)
        assert not verify(raw, headers, config)


@pytest.mark.parametrize('key', EVENTS)
def test_isn_documented_event_payloads_reach_agents_with_actionable_context(key):
    event = EVENTS[key]['body']
    operation = 'on_order_status_changed' if event['action'] == 'ORDER_STATUS_CHANGED' else 'on_order_event'
    config = {'operation': operation, 'event_type': 'OrderCompleted'}
    cls = native.ISNNode
    assert cls.filter_trigger_payload(event, config)
    output = cls.resolve_trigger_payload({**event, '_webhook': {'headers': {'secret': 'internal'}}}, config)
    assert output['data'] == event
    agent = cls.resolve_agent_event(output)
    assert agent['conversation_key'] == event['order_id']
    for value in [event['action'], event['order_id'], str(event['order_oid']), event['ck'], event['event_id'], event['utc']]:
        assert value in agent['text']
    if operation == 'on_order_event':
        assert event['address'] in agent['text'] and event['client_email'] in agent['text']
        assert event['completed_by_name'] in agent['text']
    else:
        assert event['changed_by_name'] in agent['text']
        assert event['new_status'] in agent['text']
        if event['transition'] == 'RESCHEDULED':
            assert event['old_datetime'] in agent['text'] and event['new_datetime'] in agent['text']


@pytest.mark.asyncio
async def test_isn_manual_runs_and_unsubscribed_events_do_not_fire(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError('Manual trigger must not call ISN')
    monkeypatch.setattr(native, 'guarded_async_client', unexpected)
    cls = native.ISNNode
    for operation in ['on_order_event', 'on_order_status_changed']:
        output = await node({'operation': operation}).execute({})
        assert output['status'] == 'no_event'
    assert not cls.filter_trigger_payload(EVENTS['ORDER_COMPLETED']['body'], {'operation': 'on_order_event', 'event_type': 'OrderPaid'})
    assert not cls.filter_trigger_payload(EVENTS['ORDER_COMPLETED']['body'], {'operation': 'get_order'})
    assert not cls.filter_trigger_payload({}, {'operation': 'on_order_event'})
    assert cls.resolve_agent_event({'operation': 'on_order_event', 'data': {}}) is None


def test_isn_event_choices_are_the_official_subscription_names():
    enum = REST_CONTRACT['components']['schemas']['WebhookEvents']['items']['enum']
    assert set(native.ORDER_EVENTS) <= set(enum)
    assert 'OrderStatusChanged' in enum
    for name in native.ORDER_EVENTS:
        parsed = native.ISNNode.parse_config({'config': {'operation': 'on_order_event', 'event_type': name}})
        assert parsed.config.event_type == name
    with pytest.raises((ValueError, ValidationError)):
        node({'operation': 'on_order_event', 'event_type': 'InventedEvent'})
