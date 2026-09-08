"""Nested strategies retain ownership and terminal failures across item runs."""

import asyncio
from collections import Counter
from unittest.mock import AsyncMock

import pytest

from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

pytestmark = pytest.mark.asyncio


def node(node_id, kind='processor'):
    return {'id': node_id, 'type': kind, 'config': {}}


def edge(source, target, handle=None):
    return {'source': source, 'target': target, 'sourceHandle': handle}


def yielding_runner(execute):
    handler = WorkflowExecutionHandler(sio=AsyncMock())

    async def emit(*args):
        # Real socket emission yields; immediate AsyncMocks hide the race
        # between a nested strategy's signal_done and the outer return.
        await asyncio.sleep(0)

    handler._emit_node_state = AsyncMock(side_effect=emit)
    handler._emit_node_output = AsyncMock(side_effect=emit)

    async def run_node(n, outputs, *args):
        return await execute(n, outputs)

    handler._execute_node = AsyncMock(side_effect=run_node)
    return handler


async def run(handler, nodes, edges):
    return await asyncio.wait_for(handler._execute_nodes_concurrent(
        nodes, edges, 'sid', 'user', 'workflow',
    ), timeout=5)


def states(handler, node_id):
    return [
        call.args[4]
        for call in handler._emit_node_state.await_args_list
        if call.args[2] == node_id
    ]


@pytest.mark.parametrize('outer_concurrency', [1, 2])
async def test_nested_body_runs_once_per_item_with_yielding_emitters(outer_concurrency):
    body_calls = []

    async def execute(n, outputs):
        if n['id'] == 'outer':
            return {'items': [0, 1], 'concurrency': outer_concurrency}
        if n['id'] == 'inner':
            return {'items': [0, 1], 'concurrency': 1}
        assert n['id'] == 'body'
        body_calls.append((outputs.get('outer', {}).get('index'), outputs.get('index')))
        await asyncio.sleep(0)
        return {'result': 'ok'}

    handler = yielding_runner(execute)
    _, error, _ = await run(handler, [
        node('outer', 'iteration'), node('inner', 'iteration'), node('body'),
    ], [edge('outer', 'inner', 'loop'), edge('inner', 'body', 'loop')])

    assert error is None
    assert Counter(body_calls) == Counter({(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 1})
    assert states(handler, 'body')[-1] == 'completed'


@pytest.mark.parametrize('failed_node', ['body', 'inner_done'])
async def test_nested_failure_remains_terminal_after_a_later_item_succeeds(failed_node):
    calls = []

    async def execute(n, outputs):
        if n['id'] == 'outer':
            return {'items': [0, 1], 'concurrency': 1}
        if n['id'] == 'inner':
            return {'items': [0], 'concurrency': 1}
        outer_index = outputs.get('outer', {}).get('index')
        calls.append((n['id'], outer_index))
        if n['id'] == failed_node and outer_index == 0:
            raise RuntimeError('first nested item failed')
        return {'result': 'ok'}

    handler = yielding_runner(execute)
    _, error, outputs = await run(handler, [
        node('outer', 'iteration'), node('inner', 'iteration'),
        node('body'), node('inner_done'),
    ], [
        edge('outer', 'inner', 'loop'), edge('inner', 'body', 'loop'),
        edge('inner', 'inner_done', 'done'),
    ])

    assert error == 'first nested item failed'
    assert calls == [('body', 0), ('inner_done', 0), ('body', 1), ('inner_done', 1)]
    assert outputs['outer']['results_count'] == 2
    assert 'completed' in states(handler, failed_node)
    assert states(handler, failed_node)[-1] == 'error'


async def test_nested_done_failure_skips_its_child_for_only_that_item():
    calls = []

    async def execute(n, outputs):
        if n['id'] == 'outer':
            return {'items': [0, 1], 'concurrency': 1}
        if n['id'] == 'inner':
            return {'items': [0], 'concurrency': 1}
        outer_index = outputs.get('outer', {}).get('index')
        calls.append((n['id'], outer_index))
        if n['id'] == 'inner_done':
            assert outputs['inner']['collected_results'] == [{'result': outer_index}]
            assert outputs['body']['lastOutput'] == {'result': outer_index}
            if outer_index == 0:
                raise RuntimeError('nested done failed')
        return {'result': outer_index}

    handler = yielding_runner(execute)
    _, error, outputs = await run(handler, [
        node('outer', 'iteration'), node('inner', 'iteration'),
        node('body'), node('inner_done'), node('after_done'),
    ], [
        edge('outer', 'inner', 'loop'), edge('inner', 'body', 'loop'),
        edge('inner', 'inner_done', 'done'), edge('inner_done', 'after_done'),
    ])

    assert error == 'nested done failed'
    assert calls == [
        ('body', 0), ('inner_done', 0), ('body', 1),
        ('inner_done', 1), ('after_done', 1),
    ]
    assert outputs['outer']['results_success'] == 1
    assert states(handler, 'inner_done')[-1] == 'error'
    assert states(handler, 'after_done') == ['skipped', 'running', 'completed']
