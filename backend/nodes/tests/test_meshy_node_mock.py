"""Meshy request and parser regressions through the real node factory.

Synthetic HTTP transports avoid accounts and paid generation while checking the pinned routes.
"""
import json
from pathlib import Path
import httpx
import pytest
from nodes import meshy_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'msy_synthetic_test_key'
TASK = '018a210d-8ba4-705c-b111-1f1776f7f578'
BALANCE = {'balance': 1000, 'monthly_credits': 600, 'permanent_credits': 400, 'monthly_resets_at': 1793491200000}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='meshy-test', node_type='automation-meshy',
        node_data={'config': config, 'credentials': {'credential_type': 'meshy_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, status, body):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def create_config(kind):
    return {'text_to_3d': {'mode': 'preview', 'prompt': 'a monster mask'},
            'image_to_3d': {'image_url': 'https://docs.meshy.ai/images/api/quick-start/source-photo.webp'},
            'multi_image_to_3d': {'image_urls': ['https://docs.meshy.ai/images/api/quick-start/source-photo.webp']},
            'retexture': {'input_task_id': TASK, 'text_style_prompt': 'red ceramic'},
            'remesh': {'input_task_id': TASK, 'topology': 'quad', 'target_polycount': 50000}}[kind]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_all_operations_use_pinned_method_path_and_auth(monkeypatch, operation):
    golden = json.loads((Path(__file__).parent / 'fixtures/meshy/contract.json').read_text())
    method, path = golden['routes'][operation]
    config = {'operation': operation}
    if operation.startswith('create_'):
        config.update(create_config(operation.removeprefix('create_')))
        status, body = 202, {'result': TASK}
    elif operation.startswith('delete_'):
        config['task_id'] = TASK
        status, body = 200, {}
    elif operation.startswith('list_'):
        config.update(page_num=2, page_size=20)
        status, body = 200, []
    elif operation == 'get_balance':
        status, body = 200, BALANCE
    else:
        config['task_id'] = TASK
        status, body = 200, {'id': TASK, 'status': 'IN_PROGRESS', 'created_at': 1692771650657, 'progress': 50}
    requests = transport(monkeypatch, status, body)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.path == '/openapi' + path.replace('{id}', TASK)
    assert req.url.host == 'api.meshy.ai' and req.headers['Authorization'] == 'Bearer ' + TOKEN
    if method == 'POST':
        assert json.loads(req.content) == create_config(operation.removeprefix('create_'))
        assert result['task_id'] == TASK and result['task_completed'] is False
    if operation.startswith('list_'):
        assert dict(req.url.params) == {'page_num': '2', 'page_size': '20', 'sort_by': '-created_at'}
        assert result['next_page_num'] is None and result['tasks'] == []
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_refine_and_full_page_are_explicit(monkeypatch):
    requests = transport(monkeypatch, 202, {'result': TASK})
    await node({'operation': 'create_text_to_3d', 'mode': 'refine', 'preview_task_id': TASK}).execute({})
    assert json.loads(requests[0].content) == {'mode': 'refine', 'preview_task_id': TASK}
    transport(monkeypatch, 200, [{'id': TASK}] * 10)
    result = await node({'operation': 'list_text_to_3d'}).execute({})
    assert result['next_page_num'] == 2 and result['has_more'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 409, 429, 500])
async def test_provider_errors_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, status, {'message': 'Rejected ' + TOKEN})
    result = await node({'operation': 'create_text_to_3d', 'mode': 'preview', 'prompt': 'a monster mask'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert len(requests) == 1 and TOKEN not in str(result)
    assert result['outcome_unknown'] == (status >= 500)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,body', [('get_balance', {}), ('get_text_to_3d', []), ('list_text_to_3d', {}), ('create_text_to_3d', {})])
async def test_malformed_success_is_not_accepted(monkeypatch, operation, body):
    config = {'operation': operation}
    if operation == 'get_text_to_3d': config['task_id'] = TASK
    if operation == 'create_text_to_3d': config.update(mode='preview', prompt='a monster mask')
    transport(monkeypatch, 202 if operation.startswith('create_') else 200, body)
    assert (await node(config).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'create_text_to_3d', 'mode': 'preview'},
    {'operation': 'create_text_to_3d', 'mode': 'refine'},
    {'operation': 'create_image_to_3d'},
    {'operation': 'create_image_to_3d', 'image_url': 'https://example.com/i.png', 'input_task_id': TASK},
    {'operation': 'create_multi_image_to_3d', 'image_urls': []},
    {'operation': 'create_remesh', 'model_url': 'file:///tmp/model.glb'},
    {'operation': 'get_text_to_3d', 'task_id': '../balance'},
    {'operation': 'list_text_to_3d', 'page_num': 0},
    {'operation': 'create_remesh', 'input_task_id': TASK, 'target_polycount': 99},
])
def test_invalid_input_is_rejected_before_network(config):
    with pytest.raises(ValueError):
        native.MeshyNode.parse_config({'config': config})


def test_pasted_credential_default_and_family():
    credential = native.MeshyAPIKeyCredential(api_key='  ' + TOKEN + '  ')
    assert credential.credential_type == 'meshy_api_key' and credential.api_key == TOKEN
    with pytest.raises(ValueError): native.MeshyAPIKeyCredential(api_key='Bearer ' + TOKEN)
    with pytest.raises(ValueError): native.MeshyAPIKeyCredential(api_key=TOKEN, credential_type='other_api_key')


@pytest.mark.asyncio
@pytest.mark.parametrize('selector', list(json.loads((Path(__file__).parent / 'fixtures/meshy/responses.json').read_text())))
async def test_published_response_examples(monkeypatch, selector):
    witnesses = json.loads((Path(__file__).parent / 'fixtures/meshy/responses.json').read_text())
    method, path = selector.split(' ', 1)
    operation = next(op for op, route in native.ROUTES.items() if route == (method, path))
    config = {'operation': operation}
    if operation.startswith('create_'): config.update(create_config(operation.removeprefix('create_')))
    if '{id}' in path: config['task_id'] = TASK
    transport(monkeypatch, 202 if method == 'POST' else 200, witnesses[selector]['body'])
    result = await node(config).execute({})
    assert result['status'] == 'success'


def poll_state(monkeypatch, initial=None):
    state = dict(initial or {})

    async def update(self, mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result

    monkeypatch.setattr(native.MeshyNode, '_update_node_state', update)
    return state


def documented_tasks(operation):
    witnesses = json.loads((Path(__file__).parent / 'fixtures/meshy/responses.json').read_text())
    config = native.POLL_OPERATIONS[operation]()
    path = native.ROUTES[config.operation][1]
    return path, witnesses['GET ' + path]['body']


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', native.POLL_OPERATIONS)
async def test_poll_documented_tasks_baseline_emit_once_and_agent_event(monkeypatch, operation):
    path, tasks = documented_tasks(operation)
    state = poll_state(monkeypatch)
    config = {'operation': operation}
    poll = node(config)
    transport(monkeypatch, 200, [])
    assert (await poll.execute({}))['tasks'] == []
    assert state['seen_ids'] == []
    assert poll.trigger_produced_no_event({})

    requests = transport(monkeypatch, 200, tasks)
    result = await poll.execute({})
    assert result['tasks'] == tasks and result['new_task_count'] == len(tasks)
    assert requests[0].url.path == '/openapi' + path
    assert dict(requests[0].url.params) == {'page_num': '1', 'page_size': '100', 'sort_by': '-created_at'}
    assert poll.trigger_emitted_event(result)
    assert native.MeshyNode.should_propagate_output(result, config)
    text = native.MeshyNode.resolve_agent_event(result)['text']
    assert 'Meshy' in text and tasks[0]['id'] in text and tasks[0]['status'] in text
    assert native.BASE_URL + path + '/' + tasks[0]['id'] in text
    again = await poll.execute({})
    assert again['tasks'] == [] and poll.trigger_produced_no_event(again)
    assert not native.MeshyNode.should_propagate_output(again, config)
    assert native.MeshyNode.resolve_agent_event(again) is None


@pytest.mark.asyncio
async def test_poll_existing_history_and_repoint_are_quiet(monkeypatch):
    state = poll_state(monkeypatch)
    _, tasks = documented_tasks('on_new_text_to_3d')
    transport(monkeypatch, 200, tasks)
    first = await node({'operation': 'on_new_text_to_3d'}).execute({})
    assert first['tasks'] == [] and state['seen_ids'] == [tasks[0]['id']]
    old_scope = state['scope']
    _, tasks = documented_tasks('on_new_remesh')
    transport(monkeypatch, 200, tasks)
    assert (await node({'operation': 'on_new_remesh'}).execute({}))['tasks'] == []
    assert state['scope'] != old_scope and state['seen_ids'] == [tasks[0]['id']]


@pytest.mark.asyncio
async def test_poll_paginates_and_deduplicates_overlapping_pages(monkeypatch):
    state = poll_state(monkeypatch, {'seen_ids': []})
    path, tasks = documented_tasks('on_new_text_to_3d')
    requests = []

    def respond(request):
        requests.append(request)
        # Synthetic repeated rows exercise pagination overlap; the task body is provider-authored.
        return httpx.Response(200, json=tasks * 100 if request.url.params['page_num'] == '1' else tasks)

    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kw))
    result = await node({'operation': 'on_new_text_to_3d'}).execute({})
    assert [r.url.params['page_num'] for r in requests] == ['1', '2']
    assert result['tasks'] == tasks and state['seen_ids'] == [tasks[0]['id']]


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'message': 'Invalid key'}), (429, {}),
                                       (200, {}), (200, [{'id': TASK}])])
async def test_poll_failure_never_consumes_state(monkeypatch, status, body):
    state = poll_state(monkeypatch, {'seen_ids': []})
    transport(monkeypatch, status, body)
    result = await node({'operation': 'on_new_text_to_3d'}).execute({})
    assert result['status'] == 'error' and state == {'seen_ids': []}


@pytest.mark.asyncio
async def test_poll_truncation_does_not_advance_state(monkeypatch):
    state = poll_state(monkeypatch, {'seen_ids': []})
    _, tasks = documented_tasks('on_new_text_to_3d')
    requests = transport(monkeypatch, 200, tasks * 100)
    with pytest.raises(ValueError, match='polling limit'):
        await node({'operation': 'on_new_text_to_3d'}).execute({})
    assert len(requests) == 100 and state == {'seen_ids': []}


def test_poll_scope_ignores_canvas_metadata():
    from nodes.core.poll_trigger import poll_scope
    config = {'operation': 'on_new_text_to_3d'}
    assert poll_scope(native.MeshyNode, config) == poll_scope(native.MeshyNode, {
        **config, 'label': 'My tasks', 'goal': 'Watch tasks',
        'schedule': {'frequency': 'minutes', 'interval': 10}})
    assert poll_scope(native.MeshyNode, config) != poll_scope(native.MeshyNode, {'operation': 'on_new_remesh'})
