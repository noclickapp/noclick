"""Real factory and HTTP transport tests; all keys are synthetic, with no live requests."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import graphhopper_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/graphhopper/published_examples.json').read_text())
KEY = 'synthetic-graphhopper-test-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='graphhopper-test', node_type='automation-graphhopper',
        node_data={'config': config, 'credentials': {'credential_type': 'graphhopper_api_key', 'api_key': KEY}})


def config_for(operation):
    if operation in EXAMPLES['inputs']:
        return EXAMPLES['inputs'][operation]['config']
    if operation == 'geocode':
        return {'operation': operation, 'q': 'Berlin', 'limit': 3, 'reverse': False}
    if operation == 'get_isochrone':
        return {'operation': operation, 'point': '52.537,13.406', 'time_limit': 600}
    if operation == 'get_matrix':
        return {'operation': operation, 'point': ['52.537,13.406', '52.525851,13.393364', '52.523543,13.416882'], 'out_array': ['times', 'distances']}
    if operation in {'solve_clustering', 'submit_clustering'}:
        return {'operation': operation, 'configuration': {'clustering': {'num_clusters': 1}},
                'customers': [{'id': 'customer-1', 'address': {'lat': 52.537, 'lon': 13.406}, 'quantity': 1}]}
    if operation.endswith('_solution'):
        return {'operation': operation, 'job_id': 'd62fcadd-c84a-4298-90b5-28550125bec5'}
    return {'operation': operation}


def mock_client(monkeypatch, responder):
    requests = []
    def handle(request):
        requests.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def test_discovery_and_manual_credential():
    assert NODE_REGISTRY['automation-graphhopper'] is native.GraphhopperNode
    credential = native.GraphhopperAPIKeyCredential(api_key='  ' + KEY + '  ')
    assert credential.api_key == KEY and credential.credential_type == 'graphhopper_api_key'
    assert native.GraphhopperNode.connection_evidence.proves == 'reachability'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.OPERATIONS))
async def test_every_operation_fixed_route_auth_and_documented_responses(monkeypatch, operation):
    method, path = native.OPERATIONS[operation]
    documented = EXAMPLES['responses'].get(f'{method} {path}')
    body = documented['body'] if documented else {'job_id': 'job-1', 'status': 'waiting'}
    requests = mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    config = config_for(operation)
    result = await node(config).execute({})
    assert result == {'status': 'success', 'data': body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'graphhopper.com'
    assert request.url.path == '/api/1' + path.replace('{jobId}', config.get('job_id', ''))
    assert request.url.params.get_list('key') == [KEY]
    assert 'authorization' not in request.headers
    assert KEY not in str(result)
    if method == 'POST':
        payload = json.loads(request.content)
        assert payload == {k: v for k, v in config.items() if k != 'operation'}
        assert 'key' not in payload
    else:
        assert request.content == b''
        for field in ['point', 'out_array']:
            if field in config:
                assert request.url.params.get_list(field) == (config[field] if isinstance(config[field], list) else [config[field]])
        if 'reverse' in config:
            assert request.url.params['reverse'] == 'false'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 403, 429, 500])
async def test_provider_failure_never_retries_or_exposes_key(monkeypatch, status):
    requests = mock_client(monkeypatch, lambda request: httpx.Response(status,
        json={'message': 'Invalid API key ' + KEY}, headers={'location': 'https://example.invalid/'}))
    with pytest.raises(ValueError) as exc:
        await node(config_for('submit_optimization')).execute({})
    assert len(requests) == 1
    assert str(status) in str(exc.value) and KEY not in str(exc.value)
    assert 'Invalid API key' in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_does_not_repeat_submission_or_leak_request_url(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(str(request.url), request=request)
    requests = mock_client(monkeypatch, timeout)
    with pytest.raises(ValueError, match='check job status') as exc:
        await node(config_for('submit_matrix')).execute({})
    assert KEY not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>sign in</html>'), httpx.Response(200, json=[])])
async def test_non_json_and_wrong_shapes_are_not_success(monkeypatch, response):
    mock_client(monkeypatch, lambda request: response)
    with pytest.raises(ValueError):
        await node({'operation': 'get_coverage'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_route', 'point': ['52,13']},
    {'operation': 'geocode', 'reverse': True},
    {'operation': 'calculate_route'},
    {'operation': 'calculate_matrix'},
    {'operation': 'solve_optimization'},
    {'operation': 'solve_clustering'},
    {'operation': 'get_matrix_solution', 'job_id': '../route?key=other'},
    {'operation': 'get_coverage', 'url': 'https://example.invalid'},
])
def test_missing_inputs_and_route_override_are_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize('config', [
    {'operation': 'get_route', 'point': ['52.537,13.406'], 'algorithm': 'round_trip', 'ch.disable': True},
    {'operation': 'calculate_route', 'points': [[13.406,52.537]], 'algorithm': 'round_trip', 'ch.disable': True},
])
def test_round_trip_accepts_one_origin(config):
    assert node(config).config.config.algorithm == 'round_trip'
