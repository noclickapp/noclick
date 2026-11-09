"""CarsXE request, response and credential regressions through the real node factory.

HTTP is intercepted locally, so these tests never use an account or bill lookups.
Provider examples in the operation fixture retain their published JSON shape.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import carsxe_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/carsxe/operations.json').read_text())
TOKEN = 'synthetic-carsxe-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config, credential=None):
    node = NodeFactory.create_node(node_id='carsxe-fixture', node_type='automation-carsxe',
        node_data={'config': config, 'credentials': credential or {'credential_type': 'carsxe_api_key', 'api_key': TOKEN}})
    node.emit = AsyncMock()
    return node


def intercept(monkeypatch, response):
    requests = []
    original = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_carsxe_documented_operation_request_and_response(monkeypatch, case):
    requests = intercept(monkeypatch, lambda r: httpx.Response(case['status'], json=case['response']))
    node = make_node(case['config'])
    result = await node.execute({})
    assert result == {'success': True, 'data': case['response'], 'http_status': case['status']}
    node.emit.assert_awaited_once_with(result)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method'] and req.url.path == case['path']
    assert req.url.host == 'api.carsxe.com' and req.url.scheme == 'https'
    expected = {k: v for k, v in case['config'].items() if k != 'operation'}
    if case['method'] == 'POST':
        assert dict(req.url.params) == {'key': TOKEN}
        assert json.loads(req.content) == expected
    else:
        actual = dict(req.url.params)
        assert actual.pop('key') == TOKEN
        assert actual.keys() == expected.keys()
        for name, value in expected.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                assert float(actual[name]) == value
            else:
                assert actual[name] == (str(value).lower() if isinstance(value, bool) else value)
    assert 'authorization' not in req.headers


@pytest.mark.asyncio
async def test_carsxe_connection_read_has_no_required_config_or_identity_claim(monkeypatch):
    body = {'success': True, 'input': {}, 'years': [2025, 2024]}
    requests = intercept(monkeypatch, body)
    result = await make_node({'operation': native.CarsxeNode.connection_evidence.operation}).execute({})
    assert requests[0].url.path == '/v1/ymm-options'
    assert dict(requests[0].url.params) == {'key': TOKEN}
    assert result['data'] == body
    assert native.CarsxeNode.connection_evidence.proves == 'reachability'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'success': False, 'message': 'Invalid key'}),
    (429, {'success': False, 'message': 'Usage limit exceeded'}),
    (200, {'success': False, 'message': 'Product not enabled'}),
    (302, {'message': 'Redirect refused'}), (500, {'message': 'Temporary error'})])
async def test_carsxe_errors_do_not_emit_success_or_follow_redirects(monkeypatch, status, body):
    requests = intercept(monkeypatch, lambda r: httpx.Response(status, json=body, headers={'Location': 'https://example.com'}))
    node = make_node({'operation': 'get_ymm_options'})
    with pytest.raises(ValueError, match=body['message']):
        await node.execute({})
    assert len(requests) == 1
    node.emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_carsxe_key_echoes_are_redacted_recursively(monkeypatch):
    intercept(monkeypatch, {'success': True, 'input': {'key': TOKEN}, 'items': [TOKEN]})
    result = await make_node({'operation': 'get_ymm_options'}).execute({})
    assert TOKEN not in str(result)
    assert result['data']['input']['key'] == '[redacted]'


@pytest.mark.asyncio
async def test_carsxe_transport_error_cannot_expose_query_key_or_retry_write(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout(str(req.url), request=req)
    requests = intercept(monkeypatch, fail)
    with pytest.raises(ValueError) as error:
        await make_node({'operation': 'submit_recalls_batch', 'vins': ['1HGBH41JXMN109186']}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>Error</html>'), httpx.Response(200, json='unexpected')])
async def test_carsxe_invalid_responses_are_not_success(monkeypatch, response):
    intercept(monkeypatch, lambda req: response)
    with pytest.raises(ValueError):
        await make_node({'operation': 'get_ymm_options'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_specs', 'vin': 'short'},
    {'operation': 'get_specs', 'vin': '1HGBH41JXMN109186', 'format': 'xml'},
    {'operation': 'submit_recalls_batch', 'vins': []},
    {'operation': 'get_collateral_score', 'vin': '3TMKB5FNXRM012539', 'zip': '20878', 'mileage': -1},
    {'operation': 'submit_collateral_batch', 'vehicles': []},
    {'operation': 'decode_plate', 'plate': 'ABC', 'country': 'AU'},
    {'operation': 'get_images', 'make': 'Toyota', 'model': 'Camry', 'photoType': 'interior'},
    {'operation': 'get_ymm_options', 'key': 'override'},
])
def test_carsxe_rejects_missing_invalid_and_auth_override_input(config):
    with pytest.raises((ValueError, ValidationError)):
        make_node(config)


def test_carsxe_manual_credential_defaults_type_and_cleans_key():
    credential = native.CarsxeApiKeyCredential(api_key='  '+TOKEN+'  ')
    assert credential.credential_type == 'carsxe_api_key' and credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.CarsxeApiKeyCredential(credential_type='other_api_key', api_key=TOKEN)
