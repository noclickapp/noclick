"""Wire-level checks for Cradl AI's v1 operations and pasted-token connect flow.

The tests exercise requests through the real node and an HTTP mock transport,
including pagination, review mutations, provider rejections and malformed output.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.cradl_ai_node import CradlAINode, CradlAIAccessTokenCredential

AGENT = 'cradl:agent:' + 'a' * 32
RUN = 'cradl:run:' + 'b' * 32
DOCUMENT = 'cradl:document:' + 'c' * 32
MODEL = 'cradl:model:' + 'd' * 32
VALIDATION = 'cradl:validation:' + 'e' * 32
TASK = 'cradl:task:' + 'f' * 32
PREDICTION = 'cradl:prediction:' + '0' * 32
TOKEN = 'test-cradl-private-token'
REAL_CLIENT = httpx.AsyncClient


def node(config, credentials=None):
    data = {'config': config, 'credentials': credentials or {'access_token': TOKEN}}
    return CradlAINode('test', 'automation-cradl-ai', data, config=CradlAINode.parse_config(data))


def transport(monkeypatch, handler):
    monkeypatch.setattr('nodes.cradl_ai_node.httpx.AsyncClient', lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', [
    ({'operation': 'create_agent_run', 'agent_id': AGENT, 'variables': {'customerId': '123'}}, 'POST', f'/v1/agents/{AGENT}/runs', {'variables': {'customerId': '123'}}),
    ({'operation': 'archive_agent_run', 'agent_id': AGENT, 'run_id': RUN}, 'PATCH', f'/v1/agents/{AGENT}/runs/{RUN}', {'status': 'archived'}),
    ({'operation': 'delete_agent_run', 'agent_id': AGENT, 'run_id': RUN}, 'DELETE', f'/v1/agents/{AGENT}/runs/{RUN}', None),
    ({'operation': 'create_document', 'name': 'My invoice', 'content_type': 'application/pdf', 'agent_run_id': AGENT + '/' + RUN}, 'POST', '/v1/documents', {'name': 'My invoice', 'contentType': 'application/pdf', 'agentRunId': AGENT + '/' + RUN}),
    ({'operation': 'update_document', 'document_id': DOCUMENT, 'metadata': {}}, 'PATCH', f'/v1/documents/{DOCUMENT}', {'metadata': {}}),
    ({'operation': 'delete_document', 'document_id': DOCUMENT}, 'DELETE', f'/v1/documents/{DOCUMENT}', None),
    ({'operation': 'create_prediction', 'document_id': DOCUMENT, 'model_id': MODEL, 'async_prediction': False, 'max_pages': 1}, 'POST', '/v1/predictions', {'documentId': DOCUMENT, 'modelId': MODEL, 'async': False, 'maxPages': 1}),
    ({'operation': 'create_validation_task', 'validation_id': VALIDATION, 'agent_run_id': AGENT + '/' + RUN}, 'POST', f'/v1/validations/{VALIDATION}/tasks', {'input': {}, 'agentRunId': AGENT + '/' + RUN}),
    ({'operation': 'update_validation_task', 'validation_id': VALIDATION, 'task_id': TASK, 'status': 'succeeded', 'output': {'invoiceDate': [{'value': '2021-05-01'}]}}, 'PATCH', f'/v1/validations/{VALIDATION}/tasks/{TASK}', {'status': 'succeeded', 'output': {'invoiceDate': [{'value': '2021-05-01'}]}}),
])
async def test_writes_map_exactly_once(monkeypatch, config, method, path, body):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == 'api.cradl.ai'
        assert request.url.path == path
        assert request.method == method
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json={'id': 'documented-resource'})
    transport(monkeypatch, handler)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('config,path,envelope', [
    ({'operation': 'list_agents'}, '/v1/agents', 'agents'),
    ({'operation': 'list_agent_runs', 'agent_id': AGENT}, f'/v1/agents/{AGENT}/runs', 'runs'),
    ({'operation': 'list_documents'}, '/v1/documents', 'documents'),
    ({'operation': 'list_predictions'}, '/v1/predictions', 'predictions'),
    ({'operation': 'list_models'}, '/v1/models', 'models'),
    ({'operation': 'list_validations'}, '/v1/validations', 'validations'),
    ({'operation': 'list_validation_tasks', 'validation_id': VALIDATION}, f'/v1/validations/{VALIDATION}/tasks', 'tasks'),
])
async def test_lists_return_one_page_with_opaque_continuation(monkeypatch, config, path, envelope):
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == path
        assert dict(request.url.params) == {'nextToken': 'opaque+/=', 'maxResults': '17'}
        return httpx.Response(200, json={envelope: [], 'nextToken': 'following+/='})
    transport(monkeypatch, handler)
    result = await node({**config, 'next_token': 'opaque+/=', 'max_results': 17}).execute({})
    assert result['data'] == {envelope: [], 'nextToken': 'following+/='}


@pytest.mark.asyncio
@pytest.mark.parametrize('config,path', [
    ({'operation': 'get_agent', 'agent_id': AGENT}, f'/v1/agents/{AGENT}'),
    ({'operation': 'get_agent_run', 'agent_id': AGENT, 'run_id': RUN}, f'/v1/agents/{AGENT}/runs/{RUN}'),
    ({'operation': 'get_agent_statistics', 'agent_id': AGENT}, f'/v1/agents/{AGENT}/statistics'),
    ({'operation': 'get_document', 'document_id': DOCUMENT}, f'/v1/documents/{DOCUMENT}'),
    ({'operation': 'get_prediction', 'prediction_id': PREDICTION}, f'/v1/predictions/{PREDICTION}'),
    ({'operation': 'get_model', 'model_id': MODEL}, f'/v1/models/{MODEL}'),
    ({'operation': 'get_validation', 'validation_id': VALIDATION}, f'/v1/validations/{VALIDATION}'),
    ({'operation': 'get_validation_task', 'validation_id': VALIDATION, 'task_id': TASK}, f'/v1/validations/{VALIDATION}/tasks/{TASK}'),
])
async def test_resource_reads(monkeypatch, config, path):
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path == path
        assert not request.content and not request.url.query
        return httpx.Response(200, json={'name': 'My invoice'})
    transport(monkeypatch, handler)
    assert (await node(config).execute({}))['data'] == {'name': 'My invoice'}


@pytest.mark.asyncio
async def test_connection_evidence_exposes_account_agents(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/cradl-ai/agents.json').read_text())
    transport(monkeypatch, lambda request: httpx.Response(200, json=fixture))
    evidence = CradlAINode.connection_evidence
    assert evidence.operation == 'list_agents' and evidence.proves == 'account'
    assert (await node({'operation': evidence.operation}).execute({}))['data'] == fixture


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500, 302])
async def test_provider_errors_are_not_success_or_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='permission denied ' + TOKEN)
    transport(monkeypatch, handler)
    result = await node({'operation': 'list_agents'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'permission denied' in result['error'] and TOKEN not in result['error']
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], {}, {'agents': {}}, {'agents': [], 'nextToken': 17}])
async def test_invalid_list_or_continuation_is_rejected(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({'operation': 'list_agents', 'next_token': 'same'}).execute({})


@pytest.mark.parametrize('token', ['https://example.com/token', '<token>', 'Bearer abc', ''])
def test_invalid_tokens_fail_shape(token):
    with pytest.raises((ValidationError, ValueError)):
        CradlAIAccessTokenCredential(access_token=token)


def test_credential_type_defaults_and_only_secret_is_required():
    credential = CradlAIAccessTokenCredential(access_token=TOKEN)
    assert credential.credential_type == 'cradl_ai_access_token'
    assert {n for n, f in CradlAIAccessTokenCredential.model_fields.items() if f.is_required()} == {'access_token'}


@pytest.mark.parametrize('config', [
    {'operation': 'get_document', 'document_id': '../documents'},
    {'operation': 'get_agent', 'agent_id': 'https://attacker.example'},
    {'operation': 'update_document', 'document_id': DOCUMENT},
    {'operation': 'update_validation_task', 'validation_id': VALIDATION, 'task_id': TASK},
])
def test_invalid_config_fails_before_network(config):
    assert CradlAINode.validate_config({'config': config, 'credentials': {'access_token': TOKEN}})['valid'] is False


@pytest.mark.asyncio
async def test_opaque_cursor_is_returned_without_following_it(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'agents': [], 'nextToken': 'same'})
    transport(monkeypatch, handler)
    result = await node({'operation': 'list_agents', 'next_token': 'same'}).execute({})
    assert result['data']['nextToken'] == 'same'
    assert len(calls) == 1
