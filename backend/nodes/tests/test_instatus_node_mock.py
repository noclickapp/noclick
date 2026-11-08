"""Exercise Instatus's native factory against isolated HTTP responses.

The operation fixtures cover the selected published routes and required bodies;
regressions also cover token rejection, pagination, connection evidence and errors.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import instatus_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-instatus-token-42'
CASES = json.loads((Path(__file__).parent / 'fixtures/instatus/operations.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='instatus-fixture', node_type='automation-instatus',
        node_data={'config': config, 'credentials': {'credential_type': 'instatus_api_token', 'api_token': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_published_operation_wire_contract(monkeypatch, case):
    requests = transport(monkeypatch, httpx.Response(200, json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['data'] == case['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'api.instatus.com'
    assert dict(request.url.params) == case['query']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == case['body']


@pytest.mark.asyncio
async def test_profile_connection_evidence_and_redaction(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'id': 'user-1', 'name': 'Ada', 'email': 'ada@example.com', 'echo': TOKEN}))
    result = await node({'operation': 'get_profile'}).execute({})
    assert native.InstatusNode.connection_evidence.identity_operation == 'get_profile'
    assert result['data']['name'] == 'Ada' and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 429, 500])
async def test_provider_failure_is_not_success(monkeypatch, status):
    transport(monkeypatch, httpx.Response(status, text='Provider rejected ' + TOKEN))
    result = await node({'operation': 'get_profile'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'Provider rejected' in result['message'] and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_pagination_returns_explicit_next_page(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[{'id': 'page-1'}]))
    result = await node({'operation': 'list_pages', 'page': 3, 'per_page': 1}).execute({})
    assert result['pagination'] == {'page': 3, 'per_page': 1, 'next_page': 4}
    transport(monkeypatch, httpx.Response(200, json=[]))
    assert (await node({'operation': 'list_pages'}).execute({}))['pagination']['next_page'] is None


@pytest.mark.parametrize('token', ['', 'Bearer abc', 'https://example.com/key', 'line\nbreak'])
def test_token_shaping(token):
    with pytest.raises(ValidationError):
        native.InstatusCredential(api_token=token)


@pytest.mark.parametrize('config', [
    {'operation': 'get_component', 'page_id': '..', 'component_id': 'x'},
    {'operation': 'list_pages', 'per_page': 101},
    {'operation': 'create_incident', 'page_id': 'page', 'name': 'Outage', 'status': 'BAD'},
    {'operation': 'create_incident_update', 'page_id': 'page', 'incident_id': 'i', 'status': 'RESOLVED', 'components': []},
])
def test_reject_invalid_contract_inputs(config):
    assert native.InstatusNode.validate_config({'config': config})['valid'] is False


def test_datetime_requires_timezone_and_serializes_utc():
    with pytest.raises(ValidationError):
        native.CreateIncidentConfig(page_id='p', name='Incident', status='INVESTIGATING', started='2026-11-08T10:00:00')
    operation = native.CreateIncidentConfig(page_id='p', name='Incident', status='INVESTIGATING', started='2026-11-08T12:00:00+02:00')
    assert operation.model_dump(mode='json')['started'] == '2026-11-08T10:00:00Z'
