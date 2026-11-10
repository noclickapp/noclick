"""Request contract, manual token connect and documented completion payloads."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.rundeck_node import RundeckNode, RundeckTokenCredential
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'rundeck'
TOKEN = 'test-rundeck-token-12345'
CREDENTIAL = {'credential_type': 'rundeck_api_token', 'server_url': 'https://rundeck.example.com', 'api_token': TOKEN}


def node(config):
    return NodeFactory.create_node(node_id='rundeck-test', node_type='automation-rundeck',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, responder):
    calls = []
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        async def handle(request):
            calls.append(request)
            assert request.headers['X-Rundeck-Auth-Token'] == TOKEN
            assert TOKEN not in str(request.url)
            return responder(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as session:
            yield session
    monkeypatch.setattr('nodes.rundeck_node.guarded_async_client', client)
    return calls


@pytest.mark.parametrize('operation,config,method,path,query,body', [
    ('get_profile', {}, 'GET', '/user/info', {}, None),
    ('list_projects', {}, 'GET', '/projects', {}, None),
    ('get_project', {'project': 'my project'}, 'GET', '/project/my%20project', {}, None),
    ('list_jobs', {'project': 'test', 'max': 20, 'offset': 5, 'job_filter': 'deploy', 'group_path': 'ops'}, 'GET', '/project/test/jobs', {'max': '20', 'offset': '5', 'jobFilter': 'deploy', 'groupPath': 'ops'}, None),
    ('get_job', {'job_id': 'job-id'}, 'GET', '/job/job-id/info', {}, None),
    ('get_job_workflow', {'job_id': 'job-id'}, 'GET', '/job/job-id/workflow', {}, None),
    ('run_job', {'job_id': 'job-id', 'options': {'target': 'prod'}, 'loglevel': 'INFO'}, 'POST', '/job/job-id/run', {}, {'options': {'target': 'prod'}, 'loglevel': 'INFO'}),
    ('retry_job', {'job_id': 'job-id', 'execution_id': '387', 'failed_nodes': True, 'arg_string': '-opt value'}, 'POST', '/job/job-id/retry/387', {}, {'failedNodes': True, 'argString': '-opt value'}),
    ('enable_job_execution', {'job_id': 'job-id'}, 'POST', '/job/job-id/execution/enable', {}, None),
    ('disable_job_execution', {'job_id': 'job-id'}, 'POST', '/job/job-id/execution/disable', {}, None),
    ('enable_job_schedule', {'job_id': 'job-id'}, 'POST', '/job/job-id/schedule/enable', {}, None),
    ('disable_job_schedule', {'job_id': 'job-id'}, 'POST', '/job/job-id/schedule/disable', {}, None),
    ('list_job_executions', {'job_id': 'job-id', 'status': 'failed'}, 'GET', '/job/job-id/executions', {'max': '100', 'offset': '0', 'status': 'failed'}, None),
    ('get_execution', {'execution_id': '387'}, 'GET', '/execution/387', {}, None),
    ('get_execution_state', {'execution_id': '387'}, 'GET', '/execution/387/state', {}, None),
    ('get_execution_output', {'execution_id': '387', 'offset': 100, 'maxlines': 50}, 'GET', '/execution/387/output', {'offset': '100', 'maxlines': '50'}, None),
    ('abort_execution', {'execution_id': '387'}, 'POST', '/execution/387/abort', {'forceIncomplete': 'false'}, None),
    ('query_executions', {'project': 'test', 'recent_filter': '2w', 'job_id_filter': 'job-id'}, 'GET', '/project/test/executions', {'max': '100', 'offset': '0', 'recentFilter': '2w', 'jobIdListFilter': 'job-id'}, None),
    ('list_running_executions', {'project': 'test'}, 'GET', '/project/test/executions/running', {'max': '100', 'offset': '0'}, None),
    ('list_nodes', {'project': 'test', 'node_filter': 'tags:prod'}, 'GET', '/project/test/resources', {'filter': 'tags:prod'}, None),
])
@pytest.mark.asyncio
async def test_requests(monkeypatch, operation, config, method, path, query, body):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={'ok': True}))
    result = await node({'operation': operation, **config}).execute({})
    assert result == {'status': 'success', 'data': {'ok': True}}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method
    assert request.url.raw_path.split(b'?')[0].decode() == '/api/60' + path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body


def test_manual_credential():
    credential = RundeckTokenCredential(server_url=' https://rundeck.example.com/context/ ', api_token='token-12345')
    assert credential.credential_type == 'rundeck_api_token'
    assert credential.server_url == 'https://rundeck.example.com/context'


@pytest.mark.parametrize('url', ['http://rundeck.example.com', 'https://user:pass@rundeck.example.com', 'https://rundeck.example.com?token=secret', 'https://rundeck.example.com/api/60', 'https://rundeck.example.com/../other', 'https://rundeck.example.com/%2e%2e'])
def test_bad_server_url(url):
    with pytest.raises(ValidationError):
        RundeckTokenCredential(server_url=url, api_token='token-12345')


@pytest.mark.asyncio
async def test_provider_rejection_and_redirect(monkeypatch):
    for status in [401, 403, 302]:
        transport(monkeypatch, lambda request: httpx.Response(status, json={'error': True, 'message': 'Not authorized'}))
        assert await node({'operation': 'get_profile'}).execute({}) == {'status': 'error', 'http_status': status, 'error': 'Not authorized'}


@pytest.mark.asyncio
async def test_documented_profile_and_projects(monkeypatch):
    for operation, fixture in [('get_profile', 'profile'), ('list_projects', 'projects')]:
        body = json.loads((FIXTURES / (fixture + '.json')).read_text())
        assert isinstance(body, dict if fixture == 'profile' else list)
        transport(monkeypatch, lambda request: httpx.Response(200, json=body))
        assert (await node({'operation': operation}).execute({}))['data'] == body


@pytest.mark.asyncio
async def test_completion_baseline_and_dedup(monkeypatch):
    body = json.loads((FIXTURES / 'executions.json').read_text())
    # The published example says count=2 but contains one record; adjust only
    # pagination bookkeeping for this one-row response, preserving the event.
    body['paging'].update(count=1, total=1)
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    instance = node({'operation': 'on_completed_execution', 'project': 'test'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None:
            state = next_state
        return result
    monkeypatch.setattr(instance, '_update_node_state', update)
    assert (await instance.execute({}))['new_execution_count'] == 0
    assert instance.trigger_produced_no_event({})
    body['executions'][0]['id'] = 388
    result = await instance.execute({})
    assert result['new_execution_count'] == 1
    assert result['executions'][0]['id'] == 388
    assert instance.trigger_emitted_event(result)
    assert (await instance.execute({}))['new_execution_count'] == 0
    assert dict(calls[0].url.params) == {'recentFilter': '2w', 'max': '100', 'offset': '0'}


@pytest.mark.asyncio
async def test_poll_paginates_before_dedup(monkeypatch):
    body = json.loads((FIXTURES / 'executions.json').read_text())
    def respond(request):
        page = copy.deepcopy(body)
        page['paging'].update(total=2, count=1)
        page['executions'][0]['id'] = 387 + int(request.url.params['offset'])
        return httpx.Response(200, json=page)
    calls = transport(monkeypatch, respond)
    instance = node({'operation': 'on_completed_execution', 'project': 'test', 'status_filter': 'failed', 'job_id_filter': 'job-id'})
    collected = []
    async def unseen(items, key):
        collected.extend(items)
        return items
    monkeypatch.setattr(instance, '_filter_unseen', unseen)
    assert (await instance.execute({}))['new_execution_count'] == 2
    assert [x['id'] for x in collected] == [387, 388]
    assert [dict(x.url.params)['offset'] for x in calls] == ['0', '1']
    assert all(x.url.params['statusFilter'] == 'failed' and x.url.params['jobIdListFilter'] == 'job-id' for x in calls)
