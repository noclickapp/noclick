"""Contract-backed requests and documented response parsing, without live spending."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from nodes import videoupscaler_node as vu
from nodes.core.registry import NodeFactory

DOCS = json.loads((Path(__file__).parent / 'fixtures/videoupscaler/documented.json').read_text())
TASK = next(row for row in DOCS['tasks']['examples'] if 'id' in row)
AUTH = {'credential_type': 'videoupscaler_api_key', 'api_key': 'vu_live_fixture_only'}


def node(config):
    return NodeFactory.create_node(node_id='vu-test', node_type='automation-videoupscaler',
        node_data={'config': config, 'credentials': AUTH})


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    real_client = httpx.AsyncClient
    async def handle(request):
        calls.append(request)
        assert request.url.host == 'videoupscaler.co'
        assert request.headers['authorization'] == 'Bearer ' + AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)
    monkeypatch.setattr(vu.httpx, 'AsyncClient', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handle)))
    return calls, replies


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,reply', [
    ({'operation': 'create_upscale_task', 'video_url': 'https://example.com/clip.mp4', 'resolution': '2k', 'idempotency_key': 'order-1234', 'ops': {'denoise': 0, 'faceRestore': False}}, 'POST', '/api/v1/upscale', TASK),
    ({'operation': 'create_upload_url', 'content_type': 'video/mp4', 'size': 7340032}, 'POST', '/api/v1/uploads', DOCS['uploads']['examples'][0]),
    ({'operation': 'get_upscale_task', 'task_id': TASK['id'], 'wait': 45}, 'GET', '/api/v1/tasks/' + TASK['id'], TASK),
    ({'operation': 'list_upscale_tasks', 'page': 2, 'limit': 100}, 'GET', '/api/v1/tasks', {'data': [TASK], 'page': 2, 'limit': 100, 'total': 101, 'has_more': False}),
    ({'operation': 'get_account_balance'}, 'GET', '/api/v1/account', DOCS['account']['examples'][0]),
])
async def test_contract_operations(transport, config, method, path, reply):
    calls, replies = transport
    replies.append((201 if method == 'POST' else 200, reply))
    result = await node(config).execute({})
    assert result['data'] == reply
    request = calls[0]
    assert request.method == method and request.url.path == path
    if config['operation'] == 'create_upscale_task':
        assert request.headers['Idempotency-Key'] == 'order-1234'
        assert json.loads(request.content) == {'video_url': config['video_url'], 'resolution': '2k', 'ops': {'denoise': 0, 'faceRestore': False}}
    elif config['operation'] == 'create_upload_url':
        assert json.loads(request.content) == {'content_type': 'video/mp4', 'size': 7340032}
    elif config['operation'] == 'get_upscale_task':
        assert request.url.params['wait'] == '45'
    elif config['operation'] == 'list_upscale_tasks':
        assert dict(request.url.params) == {'page': '2', 'limit': '100'}
    assert not replies


@pytest.mark.asyncio
async def test_failed_task_is_data_not_an_api_error(transport):
    calls, replies = transport
    task = {**TASK, 'status': 'failed', 'error': 'Processing failed'}
    replies.append((200, task))
    assert (await node({'operation': 'get_upscale_task', 'task_id': TASK['id']}).execute({}))['data'] == task


@pytest.mark.asyncio
async def test_error_is_verbatim_and_write_is_never_retried(transport):
    calls, replies = transport
    replies.append((402, {'error': {'code': 'insufficient_credits', 'message': 'Not enough credits for this video. Buy credits to continue.'}}))
    with pytest.raises(ValueError, match='Not enough credits for this video'):
        await node({'operation': 'create_upscale_task', 'video_url': 'https://example.com/clip.mp4', 'resolution': '2k'}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_poll_baselines_then_emits_once_and_paginates(transport):
    calls, replies = transport
    instance = node({'operation': 'on_new_task'})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update
    def page(rows, page=1, more=False):
        return {'data': rows, 'page': page, 'limit': 100, 'total': len(rows), 'has_more': more}
    replies.append((200, page([TASK])))
    assert (await instance.execute({}))['tasks'] == []
    new = {**TASK, 'id': 'new-task'}
    replies.extend([(200, page([new], more=True)), (200, page([TASK], page=2))])
    output = await instance.execute({})
    assert output['tasks'] == [new]
    assert 'new-task' in vu.VideoUpscalerNode.resolve_agent_event(output)['text']
    replies.append((200, page([new, TASK])))
    assert (await instance.execute({}))['new_task_count'] == 0
    assert not vu.VideoUpscalerNode.should_propagate_output({'new_task_count': 0}, {'operation': 'on_new_task'})
    assert dict(calls[2].url.params) == {'page': '2', 'limit': '100'}


@pytest.mark.parametrize('config', [
    {'operation': 'create_upload_url', 'content_type': 'video/mp4', 'size': 104857601},
    {'operation': 'get_upscale_task', 'task_id': 'a', 'wait': 46},
    {'operation': 'list_upscale_tasks', 'limit': 101},
    {'operation': 'create_upscale_task', 'video_url': 'https://example.com/clip.mp4', 'resolution': '8k'},
    {'operation': 'create_upscale_task', 'video_url': 'https://example.com/clip.mp4', 'resolution': '2k', 'idempotency_key': 'bad\nkey'},
])
def test_contract_bounds(config):
    assert not vu.VideoUpscalerNode.validate_config({'config': config, 'credentials': AUTH})['valid']


def test_manual_credential_defaults():
    assert vu.VideoUpscalerAPIKey(api_key='vu_live_fixture_only').credential_type == 'videoupscaler_api_key'


@pytest.mark.asyncio
async def test_updated_task_emits_completion_once(transport):
    _, replies = transport
    instance = node({'operation': 'on_task_updated'})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update
    pending = {**TASK, 'status': 'processing', 'output_url': None, 'updated_at': '2026-09-30T08:00:02.000Z'}
    def page(task):
        return {'data': [task], 'page': 1, 'limit': 100, 'total': 1, 'has_more': False}
    replies.append((200, page(pending)))
    assert (await instance.execute({}))['tasks'] == []
    replies.append((200, page(TASK)))
    output = await instance.execute({})
    assert output['tasks'] == [TASK]
    assert TASK['output_url'] in vu.VideoUpscalerNode.resolve_agent_event(output)['text']
    replies.append((200, page(TASK)))
    assert (await instance.execute({}))['tasks'] == []
