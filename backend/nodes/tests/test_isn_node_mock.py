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
