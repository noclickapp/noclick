"""Polling regressions using Sympla's published OpenAPI response examples."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import sympla_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.tests.test_sympla_node_mock import node

DOCUMENTED = json.loads((Path(__file__).parent / 'fixtures/sympla/documented_responses.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,operation,updated', [
    ('orders', 'on_new_or_updated_order', 'updated_date'),
    ('participants', 'on_new_or_updated_participant', 'ticket_updated_at'),
])
async def test_baseline_pagination_new_and_updated_records(monkeypatch, kind, operation, updated):
    instance = node({'operation': operation, 'event_id': 'abc123def456'})
    example = copy.deepcopy(DOCUMENTED[kind])
    item = example['data'][0]
    body = copy.deepcopy(example)
    body['pagination']['next_cursor'] = None
    requests = []
    def reply(request):
        requests.append(request)
        if 'cursor' not in request.url.params:
            first = copy.deepcopy(body)
            first['data'] = []
            first['pagination']['next_cursor'] = 'opaque+/='
            return httpx.Response(200, json=first)
        return httpx.Response(200, json=body)
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(state)
        if new is not None:
            state = new
        return result
    monkeypatch.setattr(instance, '_update_node_state', update)
    baseline = await instance.execute({})
    assert baseline['data'] == []
    assert instance.trigger_produced_no_event(baseline)
    assert instance.resolve_agent_event(baseline) is None
    assert (await instance.execute({}))['data'] == []
    new_item = copy.deepcopy(item)
    new_item['id'] = 'new-id'  # Only vary identity/version to simulate later deliveries.
    body['data'].append(new_item)
    fresh = await instance.execute({})
    assert fresh['data'] == [new_item]
    assert instance.trigger_emitted_event(fresh)
    text = instance.resolve_agent_event(fresh)['text']
    assert 'abc123def456' in text and 'new-id' in text
    assert (item['buyer_email'] if kind == 'orders' else item['email']) in text
    assert (await instance.execute({}))['data'] == []
    body['data'][0][updated] = '2026-06-19 19:12:37'
    assert (await instance.execute({}))['data'] == [body['data'][0]]
    assert (await instance.execute({}))['data'] == []
    for request in requests:
        assert request.method == 'GET'
        assert request.url.path == '/public/v1.6.0/events/abc123def456/' + kind
        assert request.headers['s_token'] == 'synthetic-token'
        assert request.url.params['field_sort'] == updated
        assert request.url.params['sort'] == 'desc'
        assert request.url.params['page_size'] == '200'
        assert request.url.params['cancelled_filter'] == 'include'
        assert request.url.params['timezone'] == 'America/Sao_Paulo'
        assert 'fields' not in request.url.params
    assert requests[1].url.params['cursor'] == 'opaque+/='
    # A different event must rebaseline, while canvas metadata must not consume events.
    flat = {'operation': operation, 'event_id': 'abc123def456'}
    assert poll_scope(native.SymplaNode, flat) == poll_scope(native.SymplaNode, {**flat, 'label': 'Renamed'})
    assert poll_scope(native.SymplaNode, flat) != poll_scope(native.SymplaNode, {**flat, 'event_id': 'other-event'})
    instance = node({**flat, 'event_id': 'other-event'})
    monkeypatch.setattr(instance, '_update_node_state', update)
    assert (await instance.execute({}))['data'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['cursor', 'error', 'data', 'limit'])
async def test_failed_poll_never_changes_baseline(monkeypatch, invalid):
    instance = node({'operation': 'on_new_or_updated_order', 'event_id': 'abc123def456'})
    body = copy.deepcopy(DOCUMENTED['orders'])
    if invalid == 'error':
        body = {'errors': ['failed']}
    elif invalid == 'data':
        body['data'] = {}
    elif invalid == 'limit':
        body['data'] *= 10001
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), **kw))
    async def unexpected_write(*a, **kw):
        pytest.fail('Incomplete poll must not modify the baseline')
    monkeypatch.setattr(instance, '_update_node_state', unexpected_write)
    with pytest.raises(ValueError):
        await instance.execute({})
