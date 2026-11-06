"""Test each Gusto operation with unmodified provider-authored responses.

Every fixture records its official docs URL in fixtures/gusto/responses.json.
Assertions check requests independently, including nested writes and account evidence.
"""
import json
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from pydantic import ValidationError
from nodes.gusto_node import GustoNode, GustoNodeConfig, GustoAccessTokenCredential, GUSTO_SCOPES
from nodes.core.connection_evidence import collect_evidence

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/gusto/responses.json').read_text())
ORIGINAL_CLIENT = httpx.AsyncClient
TOKEN = 'test-gusto-company-token'


def node(operation, config=None, *, credential=True, environment='demo'):
    raw = {**FIXTURES[operation]['config'], **(config or {}), 'operation': operation}
    return GustoNode('test-gusto', 'automation-gusto', {}, config=GustoNodeConfig(
        config=raw, credentials=GustoAccessTokenCredential(access_token=TOKEN, environment=environment) if credential else None))


def client_for(handler):
    return patch('nodes.gusto_node.httpx.AsyncClient', side_effect=lambda **kwargs: ORIGINAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(FIXTURES))
async def test_documented_operation(operation):
    # Each response is copied from the official source URL recorded in its fixture.
    fixture = FIXTURES[operation]
    requests = []
    def respond(request):
        requests.append(request)
        assert request.method == fixture['method']
        path = fixture['path']
        aliases = {'company_uuid': 'company_id', 'employee_uuid': 'employee_id'}
        for key in ('company_id', 'company_uuid', 'employee_id', 'employee_uuid', 'payroll_id', 'time_off_policy_uuid'):
            if '{' + key + '}' in path:
                path = path.replace('{' + key + '}', fixture['config'][aliases.get(key, key)])
        assert request.url.path == path
        assert request.url.host == 'api.gusto-demo.com'
        assert request.headers['authorization'] == f'Bearer {TOKEN}'
        assert request.headers['x-gusto-api-version'] == '2026-06-15'
        assert TOKEN not in str(request.url)
        if request.method in ('GET', 'DELETE'):
            assert not request.content
        else:
            body = json.loads(request.content)
            assert not {'operation', 'company_id', 'employee_id', 'payroll_id', 'page', 'per'} & body.keys()
            if operation == 'update_company': assert body == {'contractor_only': False}
            if operation == 'create_employee':
                assert body == {'first_name': 'Boaty', 'last_name': 'Koss', 'email': 'keena.feest@kiehn.co.uk', 'self_onboarding': False}
            if operation == 'update_employee':
                assert body == {'version': 'a5cec1f1c0135feb3e76ca6ea3c46176', 'first_name': 'Weezy', 'two_percent_shareholder': False}
            if operation == 'update_payroll':
                assert body == {'employee_compensations': json.loads(fixture['config']['employee_compensations'])}
                assert body['employee_compensations'][0]['excluded'] is False
                assert isinstance(body['employee_compensations'][0]['hourly_compensations'], list)
            if operation == 'prepare_payroll': assert body == {'employee_uuids': json.loads(fixture['config']['employee_uuids'])}
            if operation == 'add_employees_to_time_off_policy': assert body == {'employees': json.loads(fixture['config']['employees'])}
        if operation in ('list_locations', 'list_employees', 'list_payrolls', 'get_payroll', 'prepare_payroll'):
            assert request.url.params['page'] == '1'
            assert request.url.params['per'] == '100'
        if operation == 'get_time_off_activities': assert request.url.params['time_off_type'] == 'vacation'
        if fixture['status'] == 204: return httpx.Response(204)
        return httpx.Response(fixture['status'], json=fixture['body'], headers={'X-Total-Pages': '3'})
    with client_for(respond): result = await node(operation).execute({})
    assert len(requests) == 1
    assert result['status'] == 'success'
    assert result['action'] == operation
    assert result['status_code'] == fixture['status']
    assert result['data'] == ({} if fixture['status'] == 204 else fixture['body'])
    assert result['timing_ms']['api_request'] >= 0
    if fixture['status'] != 204: assert result['pagination'] == {'x-total-pages': '3'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 409, 422, 429, 500])
async def test_provider_errors_are_not_successful_empty_data(status):
    text = '{"error":"access_denied","message":"The access token is expired or revoked"}'
    with client_for(lambda req: httpx.Response(status, text=text)): result = await node('get_token_info').execute({})
    assert result['status'] == 'error'
    assert result['status_code'] == status
    assert result['error'] == text
    assert 'data' not in result
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_false_query_filter_and_pagination():
    def respond(request):
        assert dict(request.url.params) == {'page': '2', 'per': '5', 'terminated': 'false', 'onboarded': 'false', 'search_term': 'Boaty'}
        return httpx.Response(200, json=FIXTURES['list_employees']['body'])
    with client_for(respond): await node('list_employees', {'page': 2, 'per': 5, 'terminated': False, 'onboarded': False, 'search_term': 'Boaty'}).execute({})


@pytest.mark.asyncio
async def test_production_origin_and_encoded_path():
    def respond(request):
        assert request.url.host == 'api.gusto.com'
        assert request.url.raw_path == b'/v1/companies/company%2Fwith%3Fsymbols'
        return httpx.Response(200, json=FIXTURES['get_company']['body'])
    with client_for(respond): await node('get_company', {'company_id': 'company/with?symbols'}, environment='production').execute({})


@pytest.mark.asyncio
async def test_timeout_does_not_expose_secret():
    def fail(request): raise httpx.ReadTimeout('sensitive internal request', request=request)
    with client_for(fail): result = await node('get_company').execute({})
    assert result['status'] == 'error'
    assert result['error'] == 'Gusto request failed (ReadTimeout)'
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_credential_fails_before_request():
    with client_for(lambda req: pytest.fail('No request permitted without credential')):
        with pytest.raises(ValueError, match='access token is required'): await node('get_company', credential=False).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, 'unexpected', 123, {'scope': 'public'}])
async def test_invalid_token_info_cannot_prove_connection(body):
    with client_for(lambda req: httpx.Response(200, json=body)):
        with pytest.raises(ValueError): await node('get_token_info').execute({})


@pytest.mark.parametrize('operation,config', [
    ('update_employee', {'version': ''}), ('list_employees', {'per': 101}),
    ('add_employees_to_time_off_policy', {'employees': 'not json'}),
    ('add_employees_to_time_off_policy', {'employees': '[{"balance":"4.0"}]'}),
    ('update_payroll', {'employee_compensations': '[{"employee_uuid":"123"}]'}),
    ('update_payroll', {'employee_compensations': '[{"employee_uuid":"123", "version":"v1", "unknown":true}]'}),
    ('update_company', {'contractor_only': True}),
])
def test_invalid_inputs_are_rejected(operation, config):
    with pytest.raises(ValidationError): node(operation, config)


@pytest.mark.asyncio
async def test_connection_evidence_uses_real_token_info_operation():
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.path == '/v1/token_info'
        return httpx.Response(200, json=FIXTURES['get_token_info']['body'])
    with client_for(respond):
        evidence = await collect_evidence(node_type='automation-gusto', user_id='test-user', credential_data={'credential_type': 'gusto_access_token', 'access_token': TOKEN, 'environment': 'demo'})
    assert len(requests) == 1
    assert evidence.reachable is True
    assert evidence.account_label == '7b1d0df1-6403-4a06-8768-c1dd7d24d27a'


@pytest.mark.asyncio
async def test_connection_evidence_rejected_token():
    with client_for(lambda req: httpx.Response(401, text='The access token is expired or revoked')):
        evidence = await collect_evidence(node_type='automation-gusto', user_id='test-user', credential_data={'credential_type': 'gusto_access_token', 'access_token': TOKEN, 'environment': 'demo'})
    assert evidence.reachable is False
    assert 'expired or revoked' in evidence.error


def test_scope_declarations_cover_all_operations():
    assert set(GUSTO_SCOPES) == set(FIXTURES)
    assert GUSTO_SCOPES.require('prepare_payroll').scopes == ('payrolls:write', 'employees:read')
    assert GUSTO_SCOPES.require('create_employee').scopes == ('employees:manage',)
    assert GUSTO_SCOPES.require('add_employees_to_time_off_policy').scopes == ('time_off_policies:write',)
