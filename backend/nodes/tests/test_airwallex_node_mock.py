"""Exercise native Airwallex nodes against provider-published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import airwallex_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/airwallex/published_examples.json').read_text())
ID = '8365ea88-2946-4877-abe1-e02a1015288d'
CREDENTIAL = {'credential_type': 'airwallex_api_key', 'client_id': 'fixture-client-id', 'api_key': 'fixture-api-key'}
TRANSFER = {'beneficiary_id': ID, 'request_id': 'fixture-request-1', 'transfer_amount': '10000',
            'transfer_currency': 'AUD', 'source_currency': 'AUD', 'reason': 'travel',
            'reference': 'PMT1936398', 'transfer_method': 'SWIFT'}
BENEFICIARY = {'entity_type': 'COMPANY', 'company_name': 'Complete Concrete Pty Ltd',
               'bank_details': {'account_currency': 'AUD', 'account_name': 'Lee Da Ming',
                                'bank_country_code': 'AU', 'account_number': '12750852'}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id='airwallex-fixture', node_type='automation-airwallex',
        node_data={'config': config, 'credentials': {**CREDENTIAL, **credential}})



@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_every_operation_exact_wire_and_published_response(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    config = {'operation': operation}
    if '{id}' in path:
        config['id'] = ID
    if operation in {'create_transfer', 'validate_transfer'}:
        config.update(TRANSFER)
    if operation == 'create_beneficiary':
        config.update(beneficiary=BENEFICIARY, transfer_methods=['SWIFT'])
    if operation == 'update_global_account':
        config['nick_name'] = 'Treasury'
    key = method + ' /api/v1' + path
    published = EXAMPLES['responses'].get(key, {'status': 200, 'body': {}})
    # Capture the class before monkeypatching the shared module attribute.
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(201, json=EXAMPLES['responses']['POST /api/v1/authentication/login']['body'])
        return httpx.Response(published['status'], json=published['body'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await node(config).execute({})
    assert len(requests) == 2
    login, request = requests
    assert login.method == 'POST' and login.url.path == '/api/v1/authentication/login'
    assert login.headers['x-api-key'] == CREDENTIAL['api_key']
    assert login.headers['x-client-id'] == CREDENTIAL['client_id']
    assert 'authorization' not in login.headers
    assert request.method == method and request.url.path == '/api/v1' + path.replace('{id}', ID)
    assert request.url.host == 'api.airwallex.com'
    assert request.headers['authorization'].startswith('Bearer eyJ')
    assert 'x-api-key' not in request.headers and 'x-client-id' not in request.headers
    assert result['data'] == published['body'] and result['status'] == 'success'
    if operation in {'create_transfer', 'validate_transfer'}:
        assert json.loads(request.content) == TRANSFER
    if operation == 'create_beneficiary':
        assert json.loads(request.content) == {'beneficiary': BENEFICIARY, 'transfer_methods': ['SWIFT']}
    if operation == 'update_global_account':
        assert json.loads(request.content) == {'nick_name': 'Treasury'}
    if operation in {'list_balance_history', 'list_financial_transactions', 'list_beneficiaries'}:
        assert dict(request.url.params) == {'page_num': '0', 'page_size': '100'}
    if operation == 'list_balances':
        assert dict(request.url.params) == {'account_type': 'cash'}


@pytest.mark.asyncio
async def test_sandbox_host_cursor_preserved_and_provider_false_not_deleted(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(201, json={'token': 'fixture-access-token'})
        return httpx.Response(200, json=False if request.url.path.endswith('/delete') else {'items': [], 'page_after': 'next-cursor'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    result = await node({'operation': 'delete_beneficiary', 'id': ID}, environment='sandbox', account_id='acct_LTwYEh8EPa2yiA3dCoBEVA').execute({})
    assert result['data'] is False
    assert requests[0].headers['x-login-as'] == 'acct_LTwYEh8EPa2yiA3dCoBEVA'
    assert 'x-login-as' not in requests[1].headers
    assert all(request.url.host == 'api.sandbox.airwallex.com' for request in requests)
    await node({'operation': 'list_transfers', 'page': 'opaque/+cursor', 'page_size': 20}).execute({})
    assert dict(requests[-1].url.params) == {'page': 'opaque/+cursor', 'page_size': '20'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_rejection_no_retry_or_secret_leak(monkeypatch, status):
    original = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, text='credentials_invalid ' + CREDENTIAL['api_key'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match=f'HTTP {status}') as error:
        await node({'operation': 'list_global_accounts'}).execute({})
    assert CREDENTIAL['api_key'] not in str(error.value) and len(requests) == 1


def test_invalid_routes_credentials_amounts_and_unknown_operation():
    for config in [{'operation': 'get_global_account', 'id': '../escape'},
                   {'operation': 'get_beneficiary', 'id': 'not-a-uuid'},
                   {'operation': 'create_transfer', **TRANSFER, 'transfer_amount': '-1'},
                   {'operation': 'custom_request'}]:
        with pytest.raises(ValidationError):
            native.AirwallexFullConfig.model_validate({'config': config, 'credentials': CREDENTIAL})
    with pytest.raises(ValidationError):
        native.AirwallexAPIKeyCredential.model_validate({**CREDENTIAL, 'environment': 'https://evil.test'})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, False, {'items': 'invalid'}])
async def test_malformed_account_list_cannot_prove_connection(monkeypatch, body):
    original = httpx.AsyncClient
    def respond(request):
        return httpx.Response(201, json={'token': 'fixture-token'}) if request.url.path.endswith('/login') else httpx.Response(200, json=body)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match='unexpected response shape'):
        await node({'operation': 'list_global_accounts'}).execute({})


EVENTS = json.loads((Path(__file__).parent / 'fixtures/airwallex/webhook_events.json').read_text())


@pytest.mark.parametrize('event,entry', EVENTS.items())
def test_published_webhook_signature_routing_and_agent_turn(event, entry):
    import hashlib
    import hmac
    body = json.dumps(entry['body']).encode()
    timestamp = '1794330000123'  # Millisecond timestamp is hashed verbatim, as documented.
    secret = 'whsec_fixture'
    signature = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).hexdigest()
    headers = {'X-Signature': signature, 'X-Timestamp': timestamp}
    operation = 'on_deposit_event' if event in native.DEPOSIT_EVENTS else 'on_transfer_event'
    config = {'operation': operation, 'event_type': event, 'signing_secret': secret}
    assert native.AirwallexNode.verify_webhook_signature(body, headers, config)
    assert not native.AirwallexNode.verify_webhook_signature(body + b' ', headers, config)
    assert not native.AirwallexNode.verify_webhook_signature(body, {}, config)
    assert not native.AirwallexNode.verify_webhook_signature(body, headers, {**config, 'signing_secret': 'wrong'})
    assert native.AirwallexNode.filter_trigger_payload(entry['body'], config)
    other = next(name for name in (native.DEPOSIT_EVENTS if event in native.DEPOSIT_EVENTS else native.TRANSFER_EVENTS) if name != event)
    assert not native.AirwallexNode.filter_trigger_payload(entry['body'], {'operation': operation, 'event_type': other})
    output = native.AirwallexNode.resolve_trigger_payload(entry['body'], config)
    turn = native.AirwallexNode.resolve_agent_event(output)
    data = entry['body']['data']
    assert turn['conversation_key'] == data['id']
    assert event in turn['text'] and data['id'] in turn['text'] and entry['body']['id'] in turn['text']
    assert data['reference'] in turn['text']
    account = entry['body'].get('account_id') or entry['body'].get('accountId')
    assert account in turn['text']
    currency = data.get('currency') or data.get('transfer_currency')
    amount = data.get('amount') or data.get('transfer_amount')
    assert currency in turn['text'] and str(amount) in turn['text']
    # The common delivery envelope also documents data.object (product examples use data).
    wrapped = {**entry['body'], 'data': {'object': data}}
    assert native.AirwallexNode.resolve_agent_event(wrapped) == turn


@pytest.mark.asyncio
@pytest.mark.parametrize('event', native.DEPOSIT_EVENTS + native.TRANSFER_EVENTS)
async def test_webhook_register_exact_event_and_unregister(monkeypatch, event):
    original = httpx.AsyncClient
    calls = []
    operation = 'on_deposit_event' if event in native.DEPOSIT_EVENTS else 'on_transfer_event'
    config = {'operation': operation, 'event_type': event}
    spec = native.AirwallexFullConfig.model_validate({'config': config, 'credentials': CREDENTIAL})
    assert spec.config.event_type == event
    def respond(request):
        calls.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(201, json=EXAMPLES['responses']['POST /api/v1/authentication/login']['body'])
        if request.url.path.endswith('/create'):
            # Provider-published createWebhook example (same API envelope for every event).
            return httpx.Response(201, json=EXAMPLES['responses']['POST /api/v1/webhooks/create']['body'])
        return httpx.Response(200, json=EXAMPLES['responses']['POST /api/v1/webhooks/{id}/delete']['body'])
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    kwargs = dict(webhook_url='https://example.hooks.example.test', credential=CREDENTIAL, config=config, node_id='airwallex-fixture')
    registered = await native.AirwallexNode._register_external_webhook(**kwargs)
    await native.AirwallexNode._register_external_webhook(**kwargs)
    first = json.loads(calls[1].content)
    second = json.loads(calls[3].content)
    assert first['request_id'] != second['request_id']
    assert {k: v for k, v in first.items() if k != 'request_id'} == {k: v for k, v in second.items() if k != 'request_id'}
    assert first['events'] == [event] and first['version'] == '2026-08-21'
    assert first['url'] == kwargs['webhook_url'] and len(first['request_id']) <= 50
    # The provider's published 200 example says deleted:false: this must not confirm cleanup.
    with pytest.raises(ValueError, match='confirm webhook deletion'):
        await native.AirwallexNode._unregister_external_webhook(credential=CREDENTIAL, config=registered, node_id='airwallex-fixture')
    assert calls[-1].method == 'POST'
    assert calls[-1].url.path == '/api/v1/webhooks/wh_E6JwepZbKpppjYftl3JUEXPI-ocQiSHS/delete'
    assert native.AirwallexNode.registration_fingerprint_fields(config) == {'event_type': event}


@pytest.mark.asyncio
async def test_trigger_manual_run_never_calls_provider_or_invents_event(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError('manual trigger execution must not access Airwallex')
    monkeypatch.setattr(native.httpx, 'AsyncClient', forbidden)
    for operation in native.TRIGGER_DEFAULTS:
        output = await node({'operation': operation}).execute({})
        assert output['status'] == 'no_event'


@pytest.mark.asyncio
async def test_registration_rejects_missing_secret_and_unregistration_failures(monkeypatch):
    async def request(*args, **kwargs):
        return {'id': 'wh_example'}
    monkeypatch.setattr(native.AirwallexNode, '_request', request)
    with pytest.raises(ValueError, match='signing secret'):
        await native.AirwallexNode._register_external_webhook(webhook_url='https://example.hooks.example.test',
            credential=CREDENTIAL, config={'operation': 'on_deposit_event'}, node_id='n')
    async def rejected(*args, **kwargs):
        raise ValueError('Airwallex HTTP 403: unauthorized')
    monkeypatch.setattr(native.AirwallexNode, '_request', rejected)
    with pytest.raises(ValueError, match='HTTP 403'):
        await native.AirwallexNode._unregister_external_webhook(credential=CREDENTIAL,
            config={'external_webhook_id': 'wh_example'}, node_id='n')


@pytest.mark.asyncio
async def test_webhook_delete_absent_endpoint_is_idempotent(monkeypatch):
    async def absent(*args, **kwargs):
        raise ValueError('Airwallex HTTP 404: not found')
    monkeypatch.setattr(native.AirwallexNode, '_request', absent)
    await native.AirwallexNode._unregister_external_webhook(credential=CREDENTIAL,
        config={'external_webhook_id': 'wh_example'}, node_id='n')


def test_registration_fingerprint_declares_event_before_operation_selection():
    from utils.webhook_manager import registration_fingerprint

    cls = native.AirwallexNode
    assert cls.registration_fingerprint_fields({}) == {'event_type': None}
    assert cls.registration_fingerprint_fields({'event_type': 'selected-event'}) == {'event_type': 'selected-event'}
    for operation, default in native.TRIGGER_DEFAULTS.items():
        implicit = {'operation': operation}
        explicit = {**implicit, 'event_type': default}
        changed = {**implicit, 'event_type': next(event for event in (native.DEPOSIT_EVENTS if operation == 'on_deposit_event' else native.TRANSFER_EVENTS) if event != default)}
        assert cls.registration_fingerprint_fields(implicit) == {'event_type': default}
        original = registration_fingerprint(cls, operation, 'fixture-credential', implicit)
        assert original == registration_fingerprint(cls, operation, 'fixture-credential', explicit)
        assert original != registration_fingerprint(cls, operation, 'fixture-credential', changed)
