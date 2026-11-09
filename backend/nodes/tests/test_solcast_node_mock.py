"""Solcast provider-authored request and response regression tests.

Fixtures are copied from the linked official API reference, with fake credentials.
The real factory and HTTP request path run against an offline transport.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import solcast_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/solcast/documented_examples.json').read_text())
KEY = 'synthetic-solcast-test-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, config=None, credentials=None):
    return NodeFactory.create_node(node_id='solcast-fixture', node_type='automation-solcast',
        node_data={'config': {'operation': operation, **(config or {})},
                   'credentials': credentials or {'credential_type': 'solcast_api_key', 'api_key': KEY}})


def transport(monkeypatch, status=200, body=None, text=None):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(status, text=text) if text is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,example', EXAMPLES.items())
async def test_solcast_official_request_response(monkeypatch, operation, example):
    requests = transport(monkeypatch, example['status'], example['response'])
    result = await node(operation, example['config']).execute({})
    assert result['status'] == 'success'
    assert result['http_status'] == example['status']
    if example['status'] != 204:
        assert result['data'] == example['response']
    assert len(requests) == 1
    req = requests[0]
    assert req.method == example['method'] and req.url.path == example['path']
    assert req.url.scheme == 'https' and req.url.host == 'api.solcast.com.au'
    assert req.headers['Authorization'] == 'Bearer ' + KEY
    assert KEY not in str(req.url) and KEY not in str(result)
    if req.method in {'POST', 'PUT', 'PATCH'}:
        assert req.headers['Content-Type'] == 'application/json'
        assert json.loads(req.content) == example['config']
        assert not req.url.query
    else:
        expected = {'format': 'json'} if req.method == 'GET' else {}
        expected.update(example['config'])
        actual = {k: req.url.params.get_list(k) if isinstance(v, list) else req.url.params[k] for k, v in expected.items()}
        expected = {k: v if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else str(v) for k, v in expected.items()}
        assert actual == expected
        assert set(req.url.params) == set(expected)
        assert not req.content


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 403, 429, 500, 302])
async def test_solcast_preserves_rejection_without_key(monkeypatch, status):
    seen = transport(monkeypatch, status, text='provider denied ' + KEY)
    with pytest.raises(ValueError, match='provider denied') as exc:
        await node('list_pv_power_resources').execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value)
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, 'unexpected', 42, {'response_status': {'error_code': 'Unauthorized'}}])
async def test_solcast_rejects_invalid_or_error_envelopes(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node('list_pv_power_resources').execute({})


@pytest.mark.asyncio
async def test_solcast_boolean_and_query_array_serialization(monkeypatch):
    requests = transport(monkeypatch, body={'forecasts': []})
    await node('get_forecast_advanced_pv_power', {'resource_id': 'site-id',
        'terrain_shading': False, 'apply_tracker_inactive': True,
        'output_parameters': ['pv_power_advanced']}).execute({})
    assert requests[0].url.params['terrain_shading'] == 'false'
    assert requests[0].url.params['apply_tracker_inactive'] == 'true'
    assert requests[0].url.params.get_list('output_parameters') == ['pv_power_advanced']


def test_solcast_registry_credential_and_evidence():
    assert NODE_REGISTRY['automation-solcast'] is native.SolcastNode
    assert native.SolcastAPIKeyCredential(api_key=KEY).credential_type == 'solcast_api_key'
    evidence = native.SolcastNode.connection_evidence
    assert evidence.operation == 'list_pv_power_resources'
    assert set(EXAMPLES) == set(native.OPERATIONS)
    native.SolcastNode.get_config_model().model_validate({'config': {'operation': evidence.operation},
        'credentials': {'api_key': KEY}})


@pytest.mark.parametrize('key', ['https://example.com/key', 'Bearer key', ''])
def test_solcast_rejects_bad_manual_key(key):
    with pytest.raises((ValidationError, ValueError)):
        native.SolcastAPIKeyCredential(api_key=key)


def test_solcast_required_fields_and_nested_measurements():
    with pytest.raises(ValidationError):
        native.SolcastConfig.model_validate({'config': {'operation': 'create_pv_power_resource', 'name': 'Site'}})
    with pytest.raises(ValidationError):
        native.SolcastConfig.model_validate({'config': {'operation': 'create_pv_site_measurements',
            'resource_id': 'site', 'measurements': [{'power': 1, 'period_end': '2026-01-01T00:05:00Z'}]}})
    with pytest.raises(ValidationError):
        native.SolcastConfig.model_validate({'config': {'operation': 'get_forecast_radiation_and_weather',
            'latitude': 91, 'longitude': 0}})
