"""Factorial's pinned request contract and published webhook delivery regressions.

No real account or key is used. The employee event is copied in full from the
provider docs; request schemas are a pinned provider OpenAPI excerpt.
"""
import json
from pathlib import Path

import httpx
import jsonschema
import pytest
from pydantic import ValidationError

from nodes import factorial_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'factorial'
CONTRACT = json.loads((FIXTURES / 'contract.json').read_text())
EMPLOYEE = json.loads((FIXTURES / 'employee-update.json').read_text())
TOKEN = 'synthetic-factorial-key-42'
CREDENTIAL = {'credential_type': 'factorial_api_key', 'api_key': TOKEN}
PREFIX = '/api/2026-10-01/resources'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='factorial-test', node_type='automation-factorial',
                                   node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, reply):
    calls = []
    real = httpx.AsyncClient
    def respond(request):
        calls.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return real(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return calls


def sample(schema):
    value = schema.get('example')
    if value is not None:
        if schema.get('type') == 'string':
            return str(value)
        if schema.get('type') == 'integer':
            return int(value)
        return value
    if schema.get('enum'):
        return schema['enum'][0]
    return {'string': '1', 'boolean': False, 'integer': 1, 'array': ['1']}[schema['type']]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.OPERATIONS))
async def test_every_action_obeys_pinned_provider_request_schema(monkeypatch, operation):
    spec = native.OPERATIONS[operation]
    contract = CONTRACT['paths'][PREFIX + spec.path][spec.method.lower()]
    schema = contract.get('requestBody', {}).get('content', {}).get('application/json', {}).get('schema', {})
    config = {'operation': operation}
    # Exercise every exposed field, including optional fields and false values.
    properties = schema.get('properties', {})
    for name in spec.fields:
        wire = 'assignee_ids' if name == 'assignee_ids_json' else 'from' if name == 'from_date' else name
        source = properties.get(wire)
        if source is None:
            source = next(p['schema'] for p in contract['parameters'] if p['name'] == wire)
        value = sample(source)
        config[name] = json.dumps(value) if name.endswith('_json') else value
    calls = transport(monkeypatch, {'id': '1', 'data': [], 'meta': {'has_next_page': False}})
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.url.host == 'api.factorialhr.com'
    assert request.headers['x-api-key'] == TOKEN and 'authorization' not in request.headers
    assert request.method == spec.method
    assert request.url.path == PREFIX + spec.path.replace('{id}', str(config.get('id', '')))
    if schema:
        body = json.loads(request.content)
        jsonschema.validate(body, schema)
        assert set(body) <= set(properties)
        assert set(body) == set(spec.body)
        if '{id}' in spec.path:
            assert body['id'] == config['id']
    else:
        assert request.content == b''
    for param in contract.get('parameters', []):
        if param.get('required') and param['in'] == 'query':
            assert param['name'] in request.url.params
    assert result['data']['meta']['has_next_page'] is False


@pytest.mark.asyncio
async def test_pagination_and_required_boolean_defaults_preserve_false(monkeypatch):
    calls = transport(monkeypatch, {'data': [], 'meta': {'has_next_page': True, 'end_cursor': 'MTY='}})
    result = await node({'operation': 'list_employees', 'limit': 10, 'after_id': 'MTU='}).execute({})
    assert dict(calls[0].url.params) == {'only_active': 'false', 'only_managers': 'false', 'limit': '10', 'after_id': 'MTU='}
    assert result['data']['meta']['end_cursor'] == 'MTY='


@pytest.mark.asyncio
async def test_leave_date_alias_and_required_bool(monkeypatch):
    calls = transport(monkeypatch, {'data': []})
    await node({'operation': 'list_leaves', 'from_date': '2028-09-01', 'to': '2028-09-30'}).execute({})
    assert calls[0].url.params['from'] == '2028-09-01'
    assert calls[0].url.params['include_deleted_leaves'] == 'false'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_errors_stop_without_retry_and_redact_key(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, text='provider refused ' + TOKEN))
    with pytest.raises(ValueError) as error:
        await node({'operation': 'get_credentials'}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert 'provider refused' in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_empty_success_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, content=b''))
    with pytest.raises(ValueError, match='empty response'):
        await node({'operation': 'get_credentials'}).execute({})


@pytest.mark.parametrize('value', ['not json', '{}', '[1]', '[""]'])
@pytest.mark.asyncio
async def test_bad_assignee_json_never_sends_a_write(monkeypatch, value):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({'operation': 'create_task', 'name': 'My task', 'status': 'todo', 'assignee_ids_json': value}).execute({})
    assert not calls


def test_manual_credential_has_default_tag_and_hides_key():
    credential = native.FactorialAPIKeyCredential(api_key='  ' + TOKEN + '  ')
    assert credential.credential_type == 'factorial_api_key' and credential.api_key == TOKEN
    field = native.FactorialAPIKeyCredential.model_json_schema()['properties']['api_key']
    assert field['ui:widget'] == 'password'
    for value in ['https://example.com', 'Bearer my-key', '']:
        with pytest.raises(ValidationError):
            native.FactorialAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
async def test_webhook_registration_pins_version_and_secret_and_unregisters(monkeypatch):
    calls = transport(monkeypatch, {'id': '18395'})
    config = {'operation': 'on_event', 'subscription_type': 'employees/employee/update', 'company_id': '1'}
    saved = await native.FactorialNode._register_external_webhook(
        webhook_url='https://example.hooks.example.test/webhook/test', credential=CREDENTIAL, config=config, node_id='test')
    body = json.loads(calls[0].content)
    assert body['api_version'] == '2026-10-01' and body['enabled'] is True
    assert body['subscription_type'] == config['subscription_type'] and body['company_id'] == '1'
    assert body['challenge'] == saved['signing_secret'] and len(saved['signing_secret']) >= 32
    assert saved['external_webhook_id'] == '18395'
    schema = CONTRACT['paths'][PREFIX + '/api_public/webhook_subscriptions']['post']['requestBody']['content']['application/json']['schema']
    jsonschema.validate(body, schema)
    await native.FactorialNode._unregister_external_webhook(credential=CREDENTIAL, config=saved, node_id='test')
    assert calls[1].method == 'DELETE' and calls[1].url.path.endswith('/webhook_subscriptions/18395')
    assert native.FactorialNode.registration_fingerprint_fields(config) == {'subscription_type': config['subscription_type'], 'company_id': '1'}


def test_factorial_challenge_verification_matches_provider_docs():
    verify = native.FactorialNode.verify_webhook_signature
    config = {'signing_secret': '2zal4e6d'}  # docs/manage-webhooks example challenge
    assert verify(b'{}', {'X-Factorial-Wh-Challenge': '2zal4e6d'}, config)
    # The challenge authenticates the subscription, not the bytes of the body.
    assert verify(b'{"different":true}', {'x-factorial-wh-challenge': '2zal4e6d'}, config)
    assert not verify(b'{}', {}, config)
    assert not verify(b'{}', {'x-factorial-wh-challenge': 'wrong'}, config)
    assert not verify(b'{}', {'x-factorial-wh-challenge': ''}, {})


@pytest.mark.parametrize('event', [e for e in native.EVENTS if e.startswith('employees/')])
def test_published_employee_delivery_becomes_a_human_agent_turn(event):
    config = {'subscription_type': event, 'company_id': '1'}
    output = native.FactorialNode.resolve_trigger_payload(EMPLOYEE, config)
    assert output['data'] == EMPLOYEE and output['subscription_type'] == event
    agent = native.FactorialNode.resolve_agent_event(output)
    assert 'Ana Blanco Perez' in agent['text']
    assert 'employee ' + event.split('/')[-1].replace('_', ' ') in agent['text']
    assert 'company id: 1' in agent['text'] and 'Factorial resource ID: 2' in agent['text']
    assert agent['conversation_key'] == 'factorial:employees:employee:2'
    assert 'get_employee or update_employee id=2' in agent['text']
    assert 'ES622080' not in agent['text'] and 'QKG587532Y' not in agent['text']


def test_non_employee_resource_does_not_reach_employee_trigger():
    assert not native.FactorialNode.filter_trigger_payload({'id': '1', 'employee_id': '1'}, {'subscription_type': 'employees/employee/update'})


@pytest.mark.asyncio
async def test_manual_trigger_run_reports_no_event():
    assert await node({'operation': 'on_event', 'company_id': '1'}).execute({}) == {'status': 'no_event'}
