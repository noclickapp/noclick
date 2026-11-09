"""HTTP-boundary regressions; fixtures are synthetic unless sourced explicitly."""
import json
from pathlib import Path

import httpx
import pytest
from nodes import kadoa_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/kadoa/operations.json').read_text())
TOKEN = 'tk-synthetic-kadoa-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='kadoa-test', node_type='automation-kadoa',
        node_data={'config': config, 'credentials': credential or {'credential_type': 'kadoa_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_factory_exact_request_and_response(monkeypatch, operation):
    case = CASES[operation]
    reply = case['response']
    requests = transport(monkeypatch, httpx.Response(201 if operation.startswith('create_') else 200,
        **({'text': reply} if isinstance(reply, str) else {'json': reply})))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'api.kadoa.com'
    assert request.headers['x-api-key'] == TOKEN
    assert TOKEN not in str(result)
    if not isinstance(reply, str):
        assert result['data'] == reply
    if request.method == 'DELETE':
        assert request.content == b''
    if operation == 'get_workflow_data':
        assert dict(request.url.params) == {'page': '2', 'limit': '25', 'runId': 'run-456', 'order': 'asc'}
        assert result['data']['pagination']['page'] == 2
    if operation == 'get_workflow_history':
        assert dict(request.url.params) == {'page': '2', 'limit': '25', 'status': 'failed'}
    if operation == 'list_workflows':
        assert dict(request.url.params) == {'skip': '25', 'limit': '25', 'search': 'Product & prices'}
        assert result['items'][0]['name'] == 'Products'
    if operation == 'create_workflow':
        assert json.loads(request.content) == {'urls': ['https://sandbox.kadoa.com/ecommerce'], 'userPrompt': 'Extract all product information', 'limit': 50, 'bypassPreview': False}
    if operation == 'run_workflow':
        assert json.loads(request.content) == {'variables': {'country': 'US'}, 'limit': 100, 'preview': False}
        assert result['data']['status'] == 'running'
    if operation in {'create_schema', 'update_schema'}:
        body = json.loads(request.content)
        assert 'schemaId' not in body
        assert body['fields'] == [{'name': 'title', 'description': 'Product name', 'fieldType': 'SCHEMA', 'dataType': 'STRING'}]
    if operation == 'schedule_workflow':
        assert json.loads(request.content) == {'date': '2023-10-07T10:00:00.000Z'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500, 302])
async def test_provider_rejection_redacts_key_without_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={'message': 'Rejected '+TOKEN}))
    result = await node({'operation': 'list_workflows'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', [{'error': True}, {'success': False}, {}, {'workflows': 'wrong'}, []])
async def test_connection_evidence_refuses_malformed_and_error_responses(monkeypatch, reply):
    transport(monkeypatch, httpx.Response(200, json=reply))
    assert (await node({'operation': 'list_workflows'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_response_redaction_and_empty_account_evidence(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'workflows': [], 'note': TOKEN}))
    result = await node({'operation': 'list_workflows'}).execute({})
    assert result['status'] == 'success' and result['items'] == [] and TOKEN not in str(result)
    assert native.KadoaNode.connection_evidence.operation == 'list_workflows'
    assert NODE_REGISTRY['automation-kadoa'] is native.KadoaNode


@pytest.mark.asyncio
async def test_resume_202_retains_preview_job(monkeypatch):
    transport(monkeypatch, httpx.Response(202, json={'message': 'Preview restarted', 'jobId': 'new-preview'}))
    result = await node({'operation': 'resume_workflow', 'workflow_id': 'workflow-123'}).execute({})
    assert result['http_status'] == 202 and result['data']['jobId'] == 'new-preview'


@pytest.mark.asyncio
async def test_write_timeout_is_ambiguous_and_never_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('timeout', request=request)
    requests = transport(monkeypatch, fail)
    result = await node({'operation': 'run_workflow', 'workflow_id': 'workflow-123'}).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unknown' and len(requests) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'get_workflow', 'workflow_id': '../other'},
    {'operation': 'get_workflow', 'workflow_id': 'a?b'},
    {'operation': 'create_workflow', 'urls': ['invalid'], 'user_prompt': 'Extract product titles'},
    {'operation': 'get_workflow_data', 'workflow_id': 'abc', 'limit': 0},
    {'operation': 'get_workflow_data', 'workflow_id': 'abc', 'filters': '{}'},
    {'operation': 'schedule_workflow', 'workflow_id': 'abc', 'date': '2026-11-09'},
    {'operation': 'schedule_workflow', 'workflow_id': 'abc', 'date': '2026-11-09T10:00:00+05:30'},
    {'operation': 'create_schema', 'name': 'Products', 'fields': []},
])
def test_invalid_inputs_fail_before_transport(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_defaults_and_shaping():
    credential = native.KadoaAPIKeyCredential.model_validate({'api_key': ' '+TOKEN+' '})
    assert credential.credential_type == 'kadoa_api_key' and credential.api_key == TOKEN
    for value in ['https://example.com/key', 'YOUR_API_KEY', 'bad\nkey']:
        with pytest.raises(ValueError):
            native.KadoaAPIKeyCredential(api_key=value)
