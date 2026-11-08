"""Offline HTTP contract checks; no live credentials or provider mutations."""
import json
import re
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import griptape_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-griptape-key-42"
ID = "123e4567-e89b-42d3-a456-426614174000"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="griptape-test", node_type="automation-griptape", node_data={"config": config, "credentials": {"credential_type": "griptape_api_key", "api_key": TOKEN}})

def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation,route', json.loads((Path(__file__).parent / 'fixtures/griptape/routes.json').read_text()).items())
async def test_every_operation_uses_one_fixed_route(monkeypatch, operation, route):
    config = {'operation': operation}
    config.update({field: ID for field in re.findall(r'\{(\w+)\}', route['path'])})
    config.update({'create_thread': {'name': 'Support conversation'}, 'create_message': {'input': 'Hello', 'output': 'Hi'}, 'create_assistant_run': {'input': 'Summarize this'}, 'query_knowledge_base': {'query': 'Shipping policy'}, 'search_knowledge_base': {'query': 'Shipping policy'}}.get(operation, {}))
    data = {native.LIST_KEYS[operation]: []} if operation in native.LIST_KEYS else {'thread_id': ID}
    requests = transport(monkeypatch, lambda _: httpx.Response(204) if operation == 'delete_thread' else httpx.Response(201 if operation.startswith('create_') else 200, json=data))
    result = await node(config).execute({})
    assert result['status'] == 'success' and len(requests) == 1
    request = requests[0]
    assert request.method == route['method']
    assert str(request.url).startswith('https://cloud.griptape.ai/api/')
    assert request.url.path == re.sub(r'\{\w+\}', ID, route['path'])
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    if request.method == 'GET': assert not request.content
    if operation == 'create_assistant_run': assert json.loads(request.content)['stream'] is False
    if operation == 'create_structure_run': assert json.loads(request.content) == {'args': []}
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_pagination_and_recognisable_connection_evidence(monkeypatch):
    body = {'threads': [{'name': 'Customer support', 'thread_id': ID}], 'pagination': {'next_page': 3, 'page_number': 2, 'total_pages': 4}}
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    result = await node({'operation': 'list_threads', 'page': 2, 'page_size': 10}).execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'page_size': '10'}
    assert result['data'] == body and result['items'] == body['threads']
    assert native.GriptapeNode.connection_evidence.operation == 'list_threads'

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_provider_rejection_is_reported_without_retry_or_secret(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={'errors': ['Rejected ' + TOKEN]}))
    result = await node({'operation': 'create_thread', 'name': 'Support'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and 'Rejected' in result['error'] and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'threads': None}, {'errors': ['Denied']}, []])
async def test_bad_list_response_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({'operation': 'list_threads'}).execute({}))['status'] == 'error'

@pytest.mark.asyncio
async def test_transport_failure_does_not_retry_writes(monkeypatch):
    def fail(request): raise httpx.ReadTimeout('timeout')
    requests = transport(monkeypatch, fail)
    assert (await node({'operation': 'create_thread', 'name': 'Support'}).execute({}))['status'] == 'error'
    assert len(requests) == 1

@pytest.mark.parametrize('config', [
    {'operation': 'get_thread', 'thread_id': '../escape'}, {'operation': 'list_threads', 'page': 0},
    {'operation': 'create_thread', 'name': ''}, {'operation': 'create_message', 'thread_id': ID, 'input': 'Hi'},
    {'operation': 'create_structure_run', 'structure_id': ID, 'args': '{"not":"array"}'},
    {'operation': 'create_structure_run', 'structure_id': ID, 'args': '[1]'},
    {'operation': 'create_assistant_run', 'assistant_id': ID, 'input': 'Hi', 'stream': True},
])
def test_invalid_configs_are_refused(config):
    with pytest.raises((ValidationError, ValueError)):
        native.GriptapeNode.parse_config({'config': config, 'credentials': {'api_key': TOKEN}})

def test_manual_key_credential_has_default_type_and_no_extra_required_fields():
    parsed = native.GriptapeAPIKeyCredential(api_key=TOKEN)
    assert parsed.credential_type == 'griptape_api_key'
    assert native.GriptapeAPIKeyCredential.model_json_schema()['required'] == ['api_key']
    with pytest.raises(ValidationError): native.GriptapeAPIKeyCredential(api_key='Bearer ' + TOKEN)

@pytest.mark.asyncio
async def test_structure_arguments_and_message_bodies_remain_exact(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(201, json={'structure_run_id': ID}))
    args = ['-i', 'input file.txt', 'café + "quote"']
    await node({'operation': 'create_structure_run', 'structure_id': ID, 'args': json.dumps(args)}).execute({})
    assert json.loads(requests[0].content) == {'args': args}
    requests = transport(monkeypatch, lambda _: httpx.Response(201, json={'message_id': ID}))
    await node({'operation': 'create_message', 'thread_id': ID, 'input': 'Question?', 'output': 'Answer.'}).execute({})
    assert json.loads(requests[0].content) == {'input': 'Question?', 'output': 'Answer.'}
