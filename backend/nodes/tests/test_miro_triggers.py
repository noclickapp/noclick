"""Poll contracts use the provider's Board and UserInfoShort example values.
These checks cover baselining, change detection, pagination and agent context.
"""
import copy
import json
from pathlib import Path

import httpx
import pytest
import respx

from nodes.core.poll_trigger import poll_scope
from nodes.miro_node import MiroNode, MiroOnNewBoardConfig, MiroOnNewOrUpdatedBoardConfig
from nodes.tests.test_miro_node_integration import make_node

BOARD = json.loads((Path(__file__).parent / 'fixtures/miro/board.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('config_type,sort', [
    (MiroOnNewBoardConfig, 'last_created'),
    (MiroOnNewOrUpdatedBoardConfig, 'last_modified'),
])
async def test_poll_baselines_then_emits_only_unseen_boards(config_type, sort, monkeypatch):
    node = make_node(config_type(team_id='3074457353169356300'))
    state = {}

    async def update(mutator, **kwargs):
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return result

    async def token(_):
        return 'access'

    monkeypatch.setattr(node, '_token', token)
    monkeypatch.setattr(node, '_update_node_state', update)
    with respx.mock(assert_all_called=True) as router:
        route = router.get('https://api.miro.com/v2/boards').mock(side_effect=[
            httpx.Response(200, json={'data': [], 'total': 0}),
            httpx.Response(200, json={'data': [BOARD], 'total': 1}),
            httpx.Response(200, json={'data': [BOARD], 'total': 1}),
        ])
        first = await node.execute({})
        assert first['boards'] == []
        assert node.trigger_produced_no_event(first)
        fresh = await node.execute({})
        assert fresh['boards'] == [BOARD]
        assert node.trigger_emitted_event(fresh)
        assert MiroNode.should_propagate_output(fresh, {'operation': node.config.config.operation})
        event = MiroNode.resolve_agent_event(fresh)
        for value in ('John Smith', BOARD['name'], BOARD['id'], BOARD['viewLink'], BOARD['description']):
            assert value in event['text']
        repeated = await node.execute({})
        assert repeated['boards'] == []
        assert MiroNode.resolve_agent_event(repeated) is None
        for call in route.calls:
            assert dict(call.request.url.params) == {
                'team_id': '3074457353169356300', 'sort': sort, 'limit': '50', 'offset': '0'}


@pytest.mark.asyncio
@pytest.mark.parametrize('config_type,expected', [
    (MiroOnNewBoardConfig, 0), (MiroOnNewOrUpdatedBoardConfig, 1),
])
async def test_modified_timestamp_detects_updates(config_type, expected, monkeypatch):
    # Timestamps follow Board.modifiedAt's documented ISO 8601 UTC schema.
    before = {**BOARD, 'modifiedAt': '2026-11-09T00:00:00Z'}
    after = {**BOARD, 'modifiedAt': '2026-11-10T00:00:00Z'}
    node = make_node(config_type(team_id='3074457353169356300'))
    state = {}

    async def update(mutator, **kwargs):
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return result

    monkeypatch.setattr(node, '_update_node_state', update)
    with respx.mock(assert_all_called=True) as router:
        router.get('https://api.miro.com/v2/boards').mock(side_effect=[
            httpx.Response(200, json={'data': [before], 'total': 1}),
            httpx.Response(200, json={'data': [after], 'total': 1}),
        ])
        await node._poll_boards('access', node.config.config)
        result = await node._poll_boards('access', node.config.config)
    assert result['board_count'] == expected


@pytest.mark.asyncio
async def test_pagination_finishes_before_dedup_and_failures_do_not_advance_state(monkeypatch):
    node = make_node(MiroOnNewBoardConfig(team_id='3074457353169356300'))
    batches = []

    async def unseen(boards, key):
        batches.append(boards)
        return boards

    monkeypatch.setattr(node, '_filter_unseen', unseen)
    with respx.mock(assert_all_called=True) as router:
        route = router.get('https://api.miro.com/v2/boards').mock(side_effect=[
            httpx.Response(200, json={'data': [BOARD], 'total': 2}),
            httpx.Response(200, json={'data': [BOARD], 'total': 2}),
        ])
        await node._poll_boards('access', node.config.config)
        assert route.calls[1].request.url.params['offset'] == '1'
    assert len(batches[0]) == 2
    batches.clear()
    with respx.mock(assert_all_called=True) as router:
        router.get('https://api.miro.com/v2/boards').mock(side_effect=[
            httpx.Response(200, json={'data': [BOARD], 'total': 2}),
            httpx.Response(503, json={'message': 'Unavailable'}),
        ])
        with pytest.raises(ValueError, match='503'):
            await node._poll_boards('access', node.config.config)
    assert batches == []


def test_poll_scope_tracks_declared_team_but_not_editor_metadata():
    base = {'operation': 'on_new_board', 'team_id': 'team-one'}
    assert poll_scope(MiroNode, base) != poll_scope(MiroNode, {**base, 'team_id': 'team-two'})
    assert poll_scope(MiroNode, base) == poll_scope(MiroNode, {**base, 'label': 'New label'})
