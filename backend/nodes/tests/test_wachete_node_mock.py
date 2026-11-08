"""Exercise Wachete through the native node factory with fixture-only HTTP."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wachete_node as module
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "wachete_api_token", "api_token": "fixture-only-token"}
EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/wachete/provider_examples.json').read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.wachete.com'
        assert request.headers['Authorization'] == 'Bearer fixture-only-token'
        assert 'fixture-only-token' not in str(request.url)
        return replies.pop(0)
    native = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, **config):
    return await run_node_operation(node_type='automation-wachete', operation=operation,
        arguments=config, credential_data=AUTH.copy(), user_id='00000000-0000-4000-8000-000000000001')


CASES = [
    ('list_folder_contents', {}, 'GET', '/folder/list', {'subfolders': [EXAMPLES['Folder']], 'tasks': [EXAMPLES['ClientTask']], 'continuationToken': 'page-two'}),
    ('save_folder', {'name': 'My Folder'}, 'POST', '/folder', EXAMPLES['Folder']),
    ('delete_folder', {'folder_id': 'folder-1'}, 'DELETE', '/folder/folder-1', None),
    ('move_items', {'task_ids': ['task-1'], 'folder_id': 'folder-1'}, 'POST', '/folder/move', None),
    ('save_monitor', {'name': 'My First Monitor', 'url': 'http://www.mypage.com'}, 'PUT', '/task', EXAMPLES['ClientTask']),
    ('get_monitor', {'monitor_id': 'task-1'}, 'GET', '/task/task-1', EXAMPLES['ClientTask']),
    ('delete_monitor', {'monitor_id': 'task-1'}, 'DELETE', '/task/task-1', None),
    ('search_monitors', {'query': 'My First Monitor'}, 'GET', '/task/search', [EXAMPLES['ClientTask']]),
    ('list_monitor_pages', {'monitor_id': 'task-1'}, 'GET', '/task/task-1/pages', []),
    ('list_history', {'monitor_id': 'task-1'}, 'GET', '/data/list/task-1', {'data': [EXAMPLES['ClientTask']['data']], 'continuationToken': 'page-two'}),
    ('list_notifications', {}, 'GET', '/notification/list', {'data': [], 'continuationToken': None}),
    ('get_notification', {'alert_id': 'alert-1'}, 'GET', '/notification/alert-1', {'html': '<h1>Changed</h1>'}),
]


@pytest.mark.parametrize('operation,config,method,path,body', CASES)
@pytest.mark.asyncio
async def test_operations_through_native_factory(transport, operation, config, method, path, body):
    requests, replies = transport
    replies.append(httpx.Response(200, json=body) if body is not None else httpx.Response(200))
    result = await run(operation, **config)
    assert len(requests) == 1
    assert requests[0].method == method
    assert requests[0].url.path == '/thirdparty/v1' + path
    if body is None: assert result['status'] == 'success'
    else: assert result == (body if isinstance(body, dict) else {'items': body})


@pytest.mark.asyncio
async def test_query_filters_and_continuation_are_preserved(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json={'data': [], 'continuationToken': 'next-token'}))
    result = await run('list_history', monitor_id='task-1', from_time='2026-01-01T00:00:00Z',
        to_time='2026-01-02T00:00:00Z', count=25, continuation_token='opaque+token/=', return_diff=True)
    params = requests[0].url.params
    assert params['from'] == '2026-01-01T00:00:00+00:00'
    assert params['to'] == '2026-01-02T00:00:00+00:00'
    assert params['count'] == '25'
    assert params['continuationToken'] == 'opaque+token/='
    assert params['returnDiff'] == 'true'
    assert result['continuationToken'] == 'next-token'
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_monitor_definition_and_update_id(transport):
    requests, replies = transport
    replies.append(httpx.Response(200, json=EXAMPLES['ClientTask']))
    await run('save_monitor', monitor_id='task-1', name='Monitor', url='https://example.org',
        xpath='//main', recurrence_in_seconds=3600, folder_id='folder-1', job_type=1,
        dynamic_content=True, crawling_depth=2, alerts=[{'type': 1}],
        notification_endpoints=[{'type': 8, 'value': 'https://example.org/webhook'}])
    body = json.loads(requests[0].content)
    assert body['id'] == 'task-1' and body['xPath'] == '//main'
    assert body['recurrenceInSeconds'] == 3600 and body['folderId'] == 'folder-1'
    assert body['jobType'] == 1 and body['dynamicContent'] is True and body['crawlingDepth'] == 2
    assert body['alerts'] == [{'type': 1}]
    assert body['notificationEndpoints'] == [{'type': 8, 'value': 'https://example.org/webhook'}]
    assert 'operation' not in body and 'monitor_id' not in body


@pytest.mark.asyncio
async def test_folder_create_omits_id_and_update_sends_it(transport):
    requests, replies = transport
    replies.extend([httpx.Response(200, json=EXAMPLES['Folder']) for _ in range(2)])
    await run('save_folder', name='My Folder')
    await run('save_folder', folder_id='folder-1', name='Renamed', parent_id='parent-1')
    assert json.loads(requests[0].content) == {'name': 'My Folder'}
    assert json.loads(requests[1].content) == {'id': 'folder-1', 'name': 'Renamed', 'parentId': 'parent-1'}


@pytest.mark.asyncio
async def test_error_envelope_is_not_reported_as_success(transport):
    _, replies = transport
    replies.append(httpx.Response(200, json={'error': 'Token has expired'}))
    assert (await run('list_folder_contents'))['error'] == 'Token has expired'


@pytest.mark.parametrize('code', [401, 403, 429, 500])
@pytest.mark.asyncio
async def test_http_failures_raise(transport, code):
    _, replies = transport
    replies.append(httpx.Response(code, json={'message': 'Provider rejection'}))
    with pytest.raises(httpx.HTTPStatusError, match="Provider rejection"):
        await run('list_folder_contents')


@pytest.mark.parametrize('code,body', [(302, b''), (200, b''), (200, b'"not an object"'), (200, b'<html>Sign in</html>')])
@pytest.mark.asyncio
async def test_incomplete_or_redirected_reads_fail(transport, code, body):
    requests, replies = transport
    replies.append(httpx.Response(code, content=body, headers={'Location': 'https://elsewhere.example'}))
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await run('list_folder_contents')
    assert len(requests) == 1


def test_empty_move_and_wrong_enum_are_rejected():
    with pytest.raises(ValidationError): module.MoveItems()
    with pytest.raises(ValidationError): module.SaveMonitor(name='Monitor', url='https://example.org', job_type=99)
    with pytest.raises(ValidationError): module.WacheteTokenCredential(api_token='Bearer token')
