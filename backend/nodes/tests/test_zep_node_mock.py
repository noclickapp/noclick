"""Offline Zep v4 wire contracts, error behavior and hand-connect coverage."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import zep_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/zep/contract_cases.json').read_text())
TOKEN = 'synthetic-zep-project-key-123'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='zep-test', node_type='automation-zep',
        node_data={'config': config, 'credentials': {'credential_type': 'zep_api_key', 'api_key': TOKEN}})


def mock_client(monkeypatch, respond):
    requests = []
    def handler(request):
        requests.append(request)
        return respond(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_zep_one_request_per_operation_exact_contract(monkeypatch, case):
    requests = mock_client(monkeypatch, lambda _: httpx.Response(case['status'], json=case['response']))
    output = await node(case['config']).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.scheme == 'https' and request.url.host == 'api.getzep.com'
    assert request.url.path == case['path']
    assert dict(request.url.params) == case['params']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert request.headers['Authorization'] == 'Api-Key ' + TOKEN
    assert output['data'] == case['response']
    assert output['status'] == ('accepted' if case['status'] == 202 else 'success')
    if case['status'] == 202:
        assert output['processing_complete'] is False
        assert output['data']['task']['uuid'] == 'task-123'
    if case['config']['operation'] in native.PAGE_OPERATIONS:
        assert output['items'] == case['response']['items']
        assert output['has_more'] == bool(case['response'].get('next_cursor'))
        assert output['next_cursor'] == case['response'].get('next_cursor')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 409, 429, 500])
async def test_zep_error_details_and_secrets_no_follow_or_retry(monkeypatch, status):
    requests = mock_client(monkeypatch, lambda _: httpx.Response(status,
        json={'error': {'message': 'Rejected key ' + TOKEN}}, headers={'Location': 'https://other.example/'}))
    output = await node({'operation':'get_project'}).execute({})
    assert len(requests) == 1 and output['status'] == 'error' and output['http_status'] == status
    assert 'Rejected key' in str(output) and TOKEN not in str(output)


@pytest.mark.asyncio
async def test_zep_interrupted_write_is_unknown_and_is_never_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout('provider timeout', request=request)
    requests = mock_client(monkeypatch, timeout)
    output = await node({'operation':'create_user','first_name':'Jane'}).execute({})
    assert len(requests) == 1 and output['status'] == 'error' and output['write_outcome'] == 'unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, [], 'not an object'])
async def test_zep_invalid_response_fails(monkeypatch, body):
    mock_client(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation':'get_project'}).execute({})


@pytest.mark.asyncio
async def test_zep_empty_page_and_no_automatic_pagination(monkeypatch):
    requests = mock_client(monkeypatch, lambda _: httpx.Response(200, json={'items':[], 'next_cursor':'next'}))
    output = await node({'operation':'list_users'}).execute({})
    assert len(requests) == 1 and output['items'] == [] and output['next_cursor'] == 'next'
    mock_client(monkeypatch, lambda _: httpx.Response(200, json={'total_size':5}))
    with pytest.raises(ValueError, match='items'):
        await node({'operation':'list_users'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation':'get_user','user_uuid':'../other'},
    {'operation':'get_user','user_uuid':'abc/other'},
    {'operation':'get_user','user_uuid':'%2fother'},
    {'operation':'list_users','page_size':201},
    {'operation':'search_nodes','graph_uuid':'graph-1','query':'Jane','page_size':51},
    {'operation':'create_thread'},
    {'operation':'add_messages','thread_uuid':'thread-1','messages':'{}'},
    {'operation':'add_messages','thread_uuid':'thread-1','messages':'[]'},
    {'operation':'add_messages','thread_uuid':'thread-1','messages':'[{"role":"user","content":"Hello","uuid":"forbidden"}]'},
    {'operation':'add_episode','graph_uuid':'graph-1','data':'hello','metadata':'{"nested":{"value":1}}'},
    {'operation':'update_user','user_uuid':'user-1','metadata':'not json'},
    {'operation':'get_project','url':'https://other.example'},
])
def test_zep_invalid_inputs_are_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_zep_hand_connect_schema_discovery_and_evidence():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, resolved = shape_credential('zep_api_key', {'api_key': TOKEN})
    assert not errors and resolved is not None
    assert resolved[1].model_validate(shaped).credential_type == 'zep_api_key'
    assert native.ZepAPIKeyCredential.model_fields['credential_type'].default == 'zep_api_key'
    assert native.ZepNode.connection_evidence.identity_operation == 'get_project'
    assert set(native.ROUTES) == {case['config']['operation'] for case in CASES}
    assert len(native.ROUTES) == 25
    assert native.ZepNode.get_config_schema()['$defs']['ZepAPIKeyCredential']['properties']['api_key']['ui:widget'] == 'password'


@pytest.mark.parametrize('key', ['https://example.com/key', 'Api-Key abc', 'abc\r\ndef'])
def test_zep_credentials_refuse_urls_and_header_prefixes(key):
    with pytest.raises((ValueError, ValidationError)):
        native.ZepAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,reachable', [(200, True), (401, False), (403, False)])
async def test_zep_connect_evidence_reads_project_and_reports_rejection(monkeypatch, status, reachable):
    from nodes.core.connection_evidence import collect_evidence
    body = {'uuid':'project-123','name':'Support memory'} if status == 200 else {'error': {'message':'Project access unavailable'}}
    requests = mock_client(monkeypatch, lambda _: httpx.Response(status, json=body))
    evidence = await collect_evidence(node_type='automation-zep', user_id='zep-test',
        credential_data={'credential_type':'zep_api_key','api_key':TOKEN})
    assert len(requests) == 1 and requests[0].url.path == '/api/v4/project'
    assert evidence.reachable is reachable
    if status == 200:
        assert evidence.account_label == 'Support memory'
    else:
        assert 'Project access unavailable' in evidence.error


@pytest.mark.asyncio
async def test_zep_message_optional_nulls_are_omitted_from_wire(monkeypatch):
    requests = mock_client(monkeypatch, lambda _: httpx.Response(202, json={'task': {'uuid':'task-123'}}))
    await node({'operation':'add_messages', 'thread_uuid':'thread-123',
        'messages':'[{"role":"user","content":"Hello","name":null,"reference_time":null,"metadata":null}]'}).execute({})
    assert json.loads(requests[0].content) == {'messages':[{'role':'user','content':'Hello'}]}
