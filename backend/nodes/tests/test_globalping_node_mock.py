"""Globalping 1.0.0 published fixtures: https://api.globalping.io/v1/spec.yaml."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import globalping_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/globalping/published-examples.json').read_text())
TOKEN = 'synthetic-globalping-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='globalping-test', node_type='automation-globalping',
        node_data={'config': config, 'credentials': {'credential_type': 'globalping_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={'Retry-After': '4'})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,kind,options', [
    ('create_ping', 'ping', {'packets': 3, 'protocol': 'ICMP'}),
    ('create_tcp_ping', 'ping', {'packets': 3, 'protocol': 'TCP', 'port': 80}),
    ('create_traceroute', 'traceroute', {'protocol': 'ICMP'}),
    ('create_mtr', 'mtr', {'protocol': 'ICMP', 'packets': 3}),
    ('create_dns', 'dns', {'protocol': 'UDP', 'port': 53, 'query': {'type': 'A'}, 'trace': False}),
    ('create_dns_trace', 'dns', {'protocol': 'UDP', 'port': 53, 'query': {'type': 'A'}, 'trace': True}),
    ('create_http', 'http', {'protocol': 'HTTPS', 'request': {'method': 'HEAD', 'path': '/'}}),
])
async def test_globalping_creation_exact_route_body_token_and_async_ack(monkeypatch, operation, kind, options):
    requests = transport(monkeypatch, EXAMPLES['createMeasurementResponse'], 202)
    result = await node({'operation': operation, 'target': 'cdn.jsdelivr.net', 'location': 'Berlin+Germany', 'limit': 2, 'timeout': 10}).run({})
    assert result['status'] == 'success' and result['data'] == EXAMPLES['createMeasurementResponse']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'POST' and str(request.url) == native.BASE + '/measurements'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['User-Agent'].startswith('NoClick/')
    assert json.loads(request.content) == {'type': kind, 'target': 'cdn.jsdelivr.net', 'limit': 2, 'timeout': 10,
        'locations': [{'magic': 'Berlin+Germany'}], 'measurementOptions': {'ipVersion': 4, **options}}


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['getPingMeasurementResponse', 'getTracerouteMeasurementResponse',
    'getSimpleDnsMeasurementResponse', 'getTraceDnsMeasurementResponse', 'getMtrMeasurementResponse', 'getHttpMeasurementResponse'])
async def test_globalping_reads_all_published_measurement_shapes(monkeypatch, name):
    body = EXAMPLES[name]
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'get_measurement', 'measurement_id': body['id']}).run({})
    assert result['status'] == 'success' and result['data'] == body
    assert requests[0].method == 'GET' and requests[0].url.path == '/v1/measurements/' + body['id']


@pytest.mark.asyncio
async def test_globalping_authenticated_limits_and_public_probes(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['authenticatedLimits'])
    assert (await node({'operation': 'get_limits'}).run({}))['status'] == 'success'
    assert requests[0].url.path == '/v1/limits'
    transport(monkeypatch, EXAMPLES['nonAuthenticatedLimits'])
    assert (await node({'operation': 'get_limits'}).run({}))['status'] == 'error'
    requests = transport(monkeypatch, EXAMPLES['probes'])
    assert (await node({'operation': 'list_probes'}).run({}))['data'] == EXAMPLES['probes']
    assert requests[0].url.path == '/v1/probes'


@pytest.mark.asyncio
async def test_globalping_previous_probe_selection_and_http_options(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['createMeasurementResponse'], 202)
    await node({'operation': 'create_http', 'target': 'cdn.jsdelivr.net', 'reuse_measurement_id': '1wzMrzLBZfaPoT1c',
        'ip_version': 6, 'request_method': 'GET', 'path': '/npm', 'query': 'a=b', 'port': 443}).run({})
    body = json.loads(requests[0].content)
    assert body['locations'] == '1wzMrzLBZfaPoT1c'
    assert body['measurementOptions'] == {'ipVersion': 6, 'protocol': 'HTTPS', 'port': 443,
        'request': {'method': 'GET', 'path': '/npm', 'query': 'a=b'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 422, 429, 500])
async def test_globalping_errors_are_definitive_and_token_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'error': {'type': 'validation_error', 'message': 'Rejected ' + TOKEN}}, status)
    result = await node({'operation': 'get_limits'}).run({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and result['retry_after'] == '4' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('create_ping', {}), ('list_probes', {}), ('get_limits', {'rateLimit': {}}),
    ('get_measurement', {'id': 'other', 'status': 'finished', 'results': []})])
async def test_globalping_malformed_success_cannot_claim_success(monkeypatch, operation, body):
    transport(monkeypatch, body, 202 if operation == 'create_ping' else 200)
    cfg = {'operation': operation}
    if operation == 'create_ping': cfg['target'] = 'cdn.jsdelivr.net'
    if operation == 'get_measurement': cfg['measurement_id'] = 'expected'
    assert (await node(cfg).run({}))['status'] == 'error'


@pytest.mark.parametrize('changes', [{'limit': 501}, {'packets': 17}, {'timeout': 4}, {'target': 'https://example.com'},
    {'location': 'DE', 'reuse_measurement_id': 'old'}])
def test_globalping_invalid_inputs_refused(changes):
    with pytest.raises(ValidationError):
        native.Ping.model_validate({'target': 'cdn.jsdelivr.net', **changes})


def test_globalping_manual_token_default_and_validation():
    assert native.GlobalpingTokenCredential(api_token=TOKEN).credential_type == 'globalping_api_token'
    with pytest.raises(ValidationError):
        native.GlobalpingTokenCredential(api_token='Bearer ' + TOKEN)


@pytest.mark.parametrize('identifier', ['..', '../limits', 'id/other', 'id?query'])
def test_globalping_measurement_ids_cannot_change_route(identifier):
    with pytest.raises(ValidationError):
        native.GetMeasurement(measurement_id=identifier)
