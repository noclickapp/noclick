"""Native factory request contracts and error/verification semantics, without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import addressfinder_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/addressfinder/operations.json').read_text())
CREDENTIAL = {'credential_type': 'addressfinder_api_key', 'api_key': 'fixture-license-key', 'api_secret': 'fixture-server-secret'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='addressfinder-fixture', node_type=native.NODE_TYPE,
        node_data={'config': config, 'credentials': CREDENTIAL if credentials is None else credentials})


def transport(monkeypatch, body, status=200, content_type='application/json'):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'content-type': content_type})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_each_operation_has_one_exact_contract_request(monkeypatch, operation):
    case = CASES[operation]
    body = {'success': True, 'completions': []} if 'autocomplete' in case['path'] or 'reverse_geocode' in case['path'] else {'success': True, 'is_verified': False}
    requests = transport(monkeypatch, body)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['data'] == body
    assert result['identity_verified'] is False
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET'
    assert request.url.host == 'api.addressfinder.io'
    assert request.url.path == '/api' + case['path'].replace('{country}', case['config'].get('country', ''))
    assert request.headers['Authorization'] == CREDENTIAL['api_secret']
    assert request.url.params['key'] == CREDENTIAL['api_key']
    assert request.url.params['format'] == 'json'
    assert 'secret' not in request.url.params
    for key, value in case['config'].items():
        if key not in {'operation', 'country'}:
            assert request.url.params[key] == str(value)


@pytest.mark.asyncio
async def test_evidence_defaults_to_documented_address_query(monkeypatch):
    requests = transport(monkeypatch, {'success': True, 'completions': []})
    result = await node({'operation': native.AddressfinderNode.connection_evidence.operation}).execute({})
    assert result['status'] == 'success' and requests[0].url.params['q'] == 'Unit 2, 21 Kent Road'
    assert native.AddressfinderNode.connection_evidence.proves == 'reachability'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,mime', [
    (401, {'success': False, 'message': 'Invalid API key'}, 'application/json'),
    (200, {'success': False, 'message': 'No service permission'}, 'application/json'),
    (200, {}, 'application/json'),
    (200, {'success': True, 'completions': 'bad'}, 'application/json'),
    (302, {'success': True}, 'application/json'),
    (200, {'success': True}, 'text/html'),
])
async def test_rejected_malformed_and_redirect_responses_fail(monkeypatch, status, body, mime):
    requests = transport(monkeypatch, body, status, mime)
    result = await node({'operation': 'search_au_addresses'}).execute({})
    assert result['status'] == 'error' and 'data' not in result and len(requests) == 1
    if 'message' in body:
        assert result['error'] == body['message']


@pytest.mark.asyncio
async def test_errors_and_successes_redact_credentials(monkeypatch):
    for status, body in [(403, {'success': False, 'message': CREDENTIAL['api_key'] + CREDENTIAL['api_secret']}),
                         (200, {'success': True, 'completions': [{'a': CREDENTIAL['api_secret']}]})]:
        transport(monkeypatch, body, status)
        result = await node({'operation': 'search_au_addresses'}).execute({})
        assert all(secret not in json.dumps(result) for secret in (CREDENTIAL['api_key'], CREDENTIAL['api_secret']))


@pytest.mark.asyncio
async def test_verification_false_is_a_completed_lookup_not_a_verified_value(monkeypatch):
    body = {'success': True, 'is_verified': False, 'not_verified_reason': 'Phone number is not connected'}
    requests = transport(monkeypatch, body)
    result = await node({**CASES['verify_phone']['config'], 'mobile_only': False, 'verify_format_only': True}).execute({})
    assert result['status'] == 'success' and result['data']['is_verified'] is False
    assert requests[0].url.params['mobile_only'] == 'false'
    assert requests[0].url.params['verify_format_only'] == 'true'


@pytest.mark.parametrize('config', [
    {'operation': 'get_au_address_metadata'}, {'operation': 'get_nz_address_metadata'},
    {'operation': 'search_international_addresses', 'q': 'test', 'country': '../nz'},
    {'operation': 'search_au_addresses', 'max': 101},
    {'operation': 'search_international_addresses', 'q': 'test', 'country': 'fr', 'max': 16},
    {'operation': 'verify_email', 'email': 'a\nb'},
    {'operation': 'search_nz_addresses', 'q': 'test', 'custom_url': 'https://example.test'},
])
def test_invalid_config_fails_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize('value', ['https://portal.addressfinder.net', '<token>', 'abc\r\ndef', 'Bearer abc', ''])
def test_credential_paste_validation(value):
    with pytest.raises(ValidationError):
        native.AddressfinderAPIKeyCredential.model_validate({**CREDENTIAL, 'api_secret': value})


@pytest.mark.parametrize('operation,field', [('get_au_address_metadata', 'gnaf_id'), ('get_au_address_metadata', 'dpid'), ('get_nz_address_metadata', 'dpid')])
def test_documented_alternative_metadata_ids(operation, field):
    assert node({'operation': operation, field: '12345'}).config.config.operation == operation
