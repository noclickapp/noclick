"""Regression coverage for failures through the real concurrent workflow runner."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from billing.exceptions import InsufficientBalanceError
from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

pytestmark = pytest.mark.asyncio


def node(nid, kind='processor', **config):
    return {'id': nid, 'type': kind, 'config': config}


def edge(source, target, handle=None):
    return {'source': source, 'target': target, 'sourceHandle': handle}


def runner(execute):
    handler = WorkflowExecutionHandler(sio=AsyncMock())
    handler._emit_node_state = AsyncMock()
    handler._emit_node_output = AsyncMock()

    async def run_node(n, outputs, *args):
        return await execute(n, outputs)

    handler._execute_node = AsyncMock(side_effect=run_node)
    return handler


async def run(handler, nodes, edges):
    return await asyncio.wait_for(handler._execute_nodes_concurrent(
        nodes, edges, 'sid', 'user', 'workflow',
    ), timeout=5)


def states(handler, nid):
    return [c.args[4] for c in handler._emit_node_state.await_args_list if c.args[2] == nid]


@pytest.mark.parametrize('failure', [
    {'type': 'agent', 'status': 'failed', 'response': 'provider unavailable'},
    {'status': 'error', 'error': 'provider unavailable'},
    {'type': 'serverless_function', 'exit_code': 1, 'stderr': 'provider unavailable'},
    RuntimeError('provider unavailable'),
])
async def test_item_failure_is_counted_and_does_not_feed_its_dependents(failure):
    calls = []

    async def execute(n, outputs):
        if n['id'] == 'loop':
            return {'items': [0, 1], 'concurrency': 1}
        calls.append((n['id'], outputs.get('index')))
        if n['id'] == 'body' and outputs['index'] == 0:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return {'result': outputs.get('index')}

    handler = runner(execute)
    _, error, outputs = await run(handler, [node('loop', 'iteration'), node('body'), node('write')], [
        edge('loop', 'body', 'loop'), edge('body', 'write'),
    ])
    assert 'provider unavailable' in error
    assert calls == [('body', 0), ('body', 1), ('write', 1)]
    assert outputs['loop']['results_success'] == 1
    assert outputs['loop']['collected_results'][0] == {'_iteration_error': 'provider unavailable'}
    assert states(handler, 'body')[-1] == 'error'


@pytest.mark.parametrize('concurrency', [1, 3])
async def test_credit_denial_stops_queued_items_and_done_branch(concurrency):
    started = []
    all_started = asyncio.Event()

    async def execute(n, outputs):
        if n['id'] == 'loop':
            return {'items': list(range(100)), 'concurrency': concurrency}
        assert n['id'] == 'body', 'No downstream side effects after credit denial'
        started.append(outputs['index'])
        if len(started) == concurrency:
            all_started.set()
        await all_started.wait()
        raise InsufficientBalanceError('Insufficient credits')

    handler = runner(execute)
    _, error, outputs = await run(handler, [
        node('loop', 'iteration'), node('body', 'agent'), node('write'), node('done'), node('after'),
    ], [
        edge('loop', 'body', 'loop'), edge('body', 'write'),
        edge('loop', 'done', 'done'), edge('done', 'after'),
    ])
    assert 'Insufficient credits' in error
    assert len(started) == concurrency
    assert outputs['loop']['results_count'] == concurrency
    assert outputs['loop']['results_success'] == 0
    assert outputs['loop']['results_skipped'] == 100 - concurrency
    assert outputs['loop']['status'] == 'error'
    assert outputs['loop']['completed'] is False
    assert states(handler, 'loop')[-1] == 'error'
    assert outputs['body']['lastOutput']['error_type'] == 'InsufficientBalanceError'
    assert states(handler, 'write') == ['skipped']
    assert states(handler, 'done') == ['skipped']
    assert states(handler, 'after') == ['skipped']


async def test_nested_credit_denial_stops_the_outer_loop_too():
    calls = []

    async def execute(n, outputs):
        calls.append(n['id'])
        if n['type'] == 'iteration':
            return {'items': [0, 1, 2], 'concurrency': 1}
        if n['id'] == 'body':
            raise InsufficientBalanceError('Insufficient credits')
        pytest.fail('Nested or outer done branch must not execute')

    handler = runner(execute)
    _, error, outputs = await run(handler, [
        node('outer', 'iteration'), node('inner', 'iteration'), node('body', 'agent'),
        node('inner_done'), node('outer_done'),
    ], [
        edge('outer', 'inner', 'loop'), edge('inner', 'body', 'loop'),
        edge('inner', 'inner_done', 'done'), edge('outer', 'outer_done', 'done'),
    ])
    assert calls == ['outer', 'inner', 'body']
    assert 'Insufficient credits' in error
    assert outputs['outer']['results_count'] == 1
    assert outputs['outer']['results_skipped'] == 2
    assert states(handler, 'outer')[-1] == 'error'


@pytest.mark.parametrize('failure', [
    {'type': 'agent', 'status': 'failed', 'response': 'done failed'},
    RuntimeError('done failed'),
])
async def test_failed_done_node_is_terminal_and_does_not_release_success_branch(failure):
    async def execute(n, outputs):
        if n['id'] == 'loop':
            return {'items': [], 'concurrency': 1}
        assert n['id'] == 'done'
        if isinstance(failure, Exception):
            raise failure
        return failure

    handler = runner(execute)
    _, error, _ = await run(handler, [node('loop', 'iteration'), node('done', 'agent'), node('after')], [
        edge('loop', 'done', 'done'), edge('done', 'after'),
    ])
    assert 'done failed' in error
    assert states(handler, 'done')[0] == 'running'
    assert states(handler, 'done')[-1] == 'error'
    assert 'completed' not in states(handler, 'done')
    assert states(handler, 'after') == ['skipped']


async def test_mocked_failure_shaped_output_remains_data():
    payload = {'type': 'agent', 'status': 'failed', 'response': 'fixture'}

    async def execute(n, outputs):
        if n['id'] == 'loop':
            return {'items': [0], 'concurrency': 1}
        assert n['id'] == 'write'
        assert outputs['body'] == payload
        return {'result': 'ok'}

    handler = runner(execute)
    _, error, outputs = await run(handler, [
        node('loop', 'iteration'), node('body', 'agent', mockedOutput=payload), node('write'),
    ], [edge('loop', 'body', 'loop'), edge('body', 'write')])
    assert error is None
    assert outputs['loop']['results_success'] == 1
    assert states(handler, 'body') == ['completed']


async def test_credit_abort_does_not_leak_into_a_later_execution():
    denied = True
    body_calls = 0

    async def execute(n, outputs):
        nonlocal body_calls
        if n['id'] == 'loop':
            return {'items': [0, 1], 'concurrency': 1}
        body_calls += 1
        if denied:
            raise InsufficientBalanceError('Insufficient credits')
        return {'result': 'ok'}

    handler = runner(execute)
    nodes = [node('loop', 'iteration'), node('body', 'agent')]
    edges = [edge('loop', 'body', 'loop')]
    _, error, _ = await run(handler, nodes, edges)
    assert error and body_calls == 1
    denied = False
    _, error, outputs = await run(handler, nodes, edges)
    assert error is None and body_calls == 3
    assert outputs['loop']['results_success'] == 2


async def test_preloaded_output_does_not_turn_a_strategy_skip_into_completed():
    async def execute(n, outputs):
        assert n['id'] == 'agent'
        return {'type': 'agent', 'status': 'awaiting_agent_turn'}

    handler = runner(execute)
    _, error, _ = await asyncio.wait_for(handler._execute_nodes_concurrent(
        [node('agent', 'agent'), node('write')], [edge('agent', 'write')],
        'sid', 'user', 'workflow', initial_outputs={'write': {'result': 'old run'}},
    ), timeout=5)
    assert error is None
    assert states(handler, 'write') == ['skipped']


@pytest.mark.parametrize('denied', [True, False])
async def test_regular_node_retries_transient_errors_but_not_credit_denials(denied):
    count = 0

    async def execute(n, outputs):
        nonlocal count
        count += 1
        if denied:
            raise InsufficientBalanceError('Insufficient credits')
        if count == 1:
            raise RuntimeError('temporary provider failure')
        return {'result': 'ok'}

    handler = runner(execute)
    _, error, _ = await run(handler, [node('work', _settings={
        'retryOnFail': 'true', 'maxTries': '3', 'waitBetweenTries': '0',
    })], [])
    assert count == (1 if denied else 2)
    assert bool(error) is denied
