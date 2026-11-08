"""Exercise the native factory and HTTP transport against Batch API request boundaries."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import zenrows_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import _raise_if_error_envelope

TOKEN = 'synthetic-zenrows-key-42'
JOB = '01ARZ3NDEKTSV4RRFFQ69G5FAV'
RUN = '01ARZ3NDEKTSV4RRFFQ69G5FAW'
CASES = json.loads((Path(__file__).parent / 'fixtures/zenrows/requests.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='zenrows-test', node_type='automation-zenrows', node_data={
        'config': config, 'credentials': credentials or {'credential_type': 'zenrows_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_contract_routes_auth_body_and_page_preservation(monkeypatch, case):
    status = case['status']
    response = httpx.Response(status, json=case['response']) if status not in (202, 204) or case['response'] else httpx.Response(status)
    requests = transport(monkeypatch, response)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'async.api.zenrows.com'
    assert request.url.path == '/v1' + case['path']
    assert request.headers['X-API-Key'] == TOKEN
    assert 'api_key' not in request.url.params and 'apikey' not in request.url.params
    assert dict(request.url.params) == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    assert request.headers.get('Idempotency-Key') == case.get('idempotency_key')
    if case['response']:
        assert result['data'] == case['response']
    elif case['method'] == 'DELETE':
        assert result['accepted'] is True
        assert result['deletion_complete'] is (status == 204)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [201, 202])
async def test_submit_accepts_both_sync_and_async_ingestion(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={'job_id': JOB, 'accepted_tasks': 1}))
    result = await node({'operation': 'submit_job', 'tasks': [{'url': 'https://example.com'}]}).execute({})
    assert result['status_code'] == status and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 402, 404, 409, 429, 503])
async def test_provider_problem_is_error_not_evidence_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={'title': 'Request refused', 'detail': 'Provider refused ' + TOKEN}))
    result = await node({'operation': 'list_jobs'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert len(requests) == 1 and TOKEN not in str(result)
    with pytest.raises(Exception, match='Provider refused'):
        _raise_if_error_envelope(result)


@pytest.mark.asyncio
async def test_transport_failure_leaves_out_credential_and_avoids_retries(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(TOKEN, request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({'operation': 'stop_job', 'job_id': JOB}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], {'jobs': None}, {'jobs': ['invalid']}])
async def test_invalid_list_cannot_prove_connection(monkeypatch, payload):
    transport(monkeypatch, httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({'operation': 'list_jobs'}).execute({})


@pytest.mark.asyncio
async def test_success_output_redacts_key_recursively(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'jobs': [{'job_id': JOB, 'name': TOKEN}], 'next_cursor': None}))
    result = await node({'operation': 'list_jobs'}).execute({})
    assert TOKEN not in str(result) and result['items'][0]['name'] == '[redacted]'


@pytest.mark.parametrize('config', [
    {'operation': 'get_job', 'job_id': '../jobs'},
    {'operation': 'get_job_run', 'job_id': JOB, 'run_id': 'bad'},
    {'operation': 'get_latest_run_task_history', 'job_id': JOB, 'task_id': '../task'},
    {'operation': 'get_latest_run_task_history', 'job_id': JOB, 'task_id': '..'},
    {'operation': 'get_run_task_history', 'job_id': JOB, 'run_id': RUN, 'task_id': '.'},
    {'operation': 'submit_job'},
    {'operation': 'submit_job', 'tasks': [{'url': 'file:///etc/passwd'}]},
    {'operation': 'submit_job', 'tasks': [{'url': 'https://example.com', 'body': 'no GET body'}]},
    {'operation': 'submit_job', 'tasks': [{'url': 'https://example.com'}], 'file_input_id': 'file'},
    {'operation': 'submit_job', 'type': 'scheduled', 'status': 'open'},
    {'operation': 'add_tasks', 'job_id': JOB, 'tasks': []},
    {'operation': 'list_jobs', 'limit': 101},
    {'operation': 'rerun_job', 'job_id': JOB, 'status': 'made_up'},
    {'operation': 'put_job_webhook', 'job_id': JOB, 'webhook': {'url': 'http://example.com', 'signature': False}},
    {'operation': 'put_job_webhook', 'job_id': JOB, 'webhook': {'url': 'https://example.com'}},
    {'operation': 'update_job_schedule', 'job_id': JOB, 'schedule': {}},
    {'operation': 'update_job_schedule', 'job_id': JOB, 'schedule': {'at': '2026-09-01T09:00:00Z', 'timezone': 'UTC'}},
    {'operation': 'update_job_schedule', 'job_id': JOB, 'schedule': {'rate': {'every': 15, 'unit': 'minute'}, 'at': '2026-09-01T09:00:00', 'timezone': 'UTC'}},
])
def test_invalid_inputs_rejected_before_http(config):
    with pytest.raises(ValueError):
        node(config)


def test_credential_shaping_and_wrong_family():
    assert native.ZenrowsAPIKeyCredential(api_key='  ' + TOKEN + '  ').api_key == TOKEN
    for key in ['https://example.com', 'key\r\nHeader: value', '<token>']:
        with pytest.raises(ValidationError):
            native.ZenrowsAPIKeyCredential(api_key=key)
    with pytest.raises(ValueError):
        node({'operation': 'list_jobs'}, {'credential_type': 'other_key', 'api_key': TOKEN})


def test_account_evidence_and_operation_inventory():
    evidence = native.ZenrowsNode.connection_evidence
    assert evidence.operation == 'list_jobs' and evidence.proves == 'account'
    assert len(CASES) == 23 and {c['config']['operation'] for c in CASES} == set(native.ROUTES)
