"""Offline request assertions using the provider's documented examples."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import itm_platform_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/itm-platform/contract.json').read_text())
AUTH = {'credential_type': 'itm_platform_token', 'company': 'companyURL', 'token': 'fixture-itm-session-7291'}
USER = '00000000-0000-4000-8000-000000000001'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.itmplatform.com'
        assert request.headers['Token'] == AUTH['token']
        assert AUTH['token'] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, 'guarded_async_client', lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config):
    return await run_node_operation(node_type='automation-itm-platform', operation=config['operation'],
        arguments={k: v for k, v in config.items() if k != 'operation'}, credential_data=AUTH.copy(), user_id=USER)


@pytest.mark.parametrize('operation', FIXTURES, ids=lambda op: 'itm-platform-' + op)
async def test_itm_platform_documented_operation(transport, operation):
    requests, replies = transport
    fixture = FIXTURES[operation]
    replies.append((200, fixture['response']))
    result = await run(fixture['config'])
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    path = fixture['path']
    for name in ('ProjectId', 'TaskId', 'ServiceId', 'UserId'):
        field = {'ProjectId': 'project_id', 'TaskId': 'task_id', 'ServiceId': 'service_id', 'UserId': 'user_id'}[name]
        if '{' + name + '}' in path:
            path = path.replace('{' + name + '}', str(fixture['config'][field]))
    assert request.method == fixture['method']
    assert request.url.path == ('/v2' if fixture['v2'] else '') + '/companyURL' + path
    if operation.startswith('search_'):
        body = json.loads(request.content)
        assert body['Filter'] == fixture['config']['filter']
        assert body['Columns'] == {'$in': fixture['config']['columns']}
        assert (body['page'], body['pageSize']) == (1, 50)
    if operation.startswith(('create_', 'update_')):
        body = json.loads(request.content)
        assert body['Name'] == fixture['config']['name']
        assert 'operation' not in body and 'project_id' not in body
    if operation == 'get_timesheet':
        assert dict(request.url.params) == {'StartDate': '2026-07-01', 'EndDate': '2026-07-31'}
    if operation == 'set_time_entries':
        body = json.loads(request.content)
        assert body['UserId'] == 33382
        assert body['TimeReports'][0] == {'EntityId': 55713, 'WorkItemId': 131459,
            'Date': '2026-02-03', 'ReportedHours': '4:00', 'UserComment': 'Design review and documentation',
            'BillingCategoryId': 15353, 'NonBillableMins': '0'}


@pytest.mark.parametrize('status,body', [
    (401, {'StatusMessage': 'Invalid Token.', 'StatusCode': 401}),
    (200, {'StatusMessage': 'Invalid report', 'StatusCode': 400, 'Errors': [{'Message': 'Task missing'}]}),
    (302, {'message': 'Redirect refused'}),
    (429, {'message': 'Quota exceeded'}),
    (503, {'message': 'Unavailable'}),
])
async def test_itm_platform_rejection_is_not_success_or_retried(transport, status, body):
    requests, replies = transport
    replies.append((status, body))
    result = await run(FIXTURES['create_task']['config'])
    assert result['status'] == 'error'
    assert len(requests) == 1


async def test_itm_platform_redacts_reflected_session_token(transport):
    _, replies = transport
    replies.append((401, {'StatusMessage': 'Invalid ' + AUTH['token']}))
    result = await run({'operation': 'list_users'})
    assert AUTH['token'] not in json.dumps(result)
    assert result['message'] == 'Invalid [redacted]'


async def test_itm_platform_empty_timesheet(transport):
    _, replies = transport
    replies.append((204, None))
    result = await run(FIXTURES['get_timesheet']['config'])
    assert result['status'] == 'success' and result['data'] is None


@pytest.mark.parametrize('company', ['../other', 'a/b', 'a?x=y', 'https://api.itmplatform.com/a', 'a#x', 'a%2fb', 'a\\b'])
def test_itm_platform_company_cannot_change_route(company):
    with pytest.raises(ValidationError):
        node.ITMPlatformTokenCredential.model_validate({**AUTH, 'company': company})


@pytest.mark.parametrize('config', [
    {'operation': 'get_project', 'project_id': -1},
    {'operation': 'search_projects', 'page': 0},
    {'operation': 'search_projects', 'page_size': 501},
    {'operation': 'update_project', 'project_id': 55713},
    {'operation': 'get_timesheet', 'start_date': '2026-01-01', 'end_date': '2026-02-01'},
    {'operation': 'get_timesheet', 'start_date': '2026-01-03', 'end_date': '2026-01-01'},
])
def test_itm_platform_invalid_config(config):
    assert not node.ITMPlatformNode.validate_config({'config': config, 'credentials': AUTH})['valid']


def test_itm_platform_manual_connect_default():
    assert node.ITMPlatformTokenCredential.model_validate({'company': 'companyURL', 'token': AUTH['token']}).credential_type == 'itm_platform_token'
    assert node.ITMPlatformNode.connection_evidence.operation == 'list_users'
