"""Exercise scheduled Zeffy triggers with the provider's OpenAPI examples.

These regressions cover baselining, deduplication, pagination, and agent events
so failed or incomplete polling cannot consume donor activity.
"""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from nodes import zeffy_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/zeffy/resources.json').read_text())
CREDENTIAL = {'credential_type': 'zeffy_api_key', 'api_key': 'synthetic-zeffy-key'}


def node(operation, **fields):
    return NodeFactory.create_node(node_id='zeffy-trigger', node_type='automation-zeffy',
        node_data={'config': {'operation': operation, **fields}, 'credentials': CREDENTIAL})


def state_for(instance, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update


def serve(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def page(rows, cursor=None):
    return httpx.Response(200, json={'object': 'list', 'data': rows,
        'has_more': cursor is not None, 'next_cursor': cursor})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,resource', native.POLL_RESOURCES.items())
async def test_arm_baseline_new_item_repeat_and_agent_event(monkeypatch, operation, resource):
    record = deepcopy(FIXTURES[resource[:-1]])
    rows = [record]
    requests = serve(monkeypatch, lambda _: page(rows))
    instance = node(operation, created_gte=1700000000)
    state = {}
    state_for(instance, state)
    baseline = await instance.execute({})
    assert baseline['data'] == []
    assert instance.trigger_produced_no_event(baseline)
    assert native.ZeffyNode.resolve_agent_event(baseline) is None
    assert dict(requests[0].url.params) == {'limit': '100', 'created[gte]': '1700000000'}
    assert requests[0].url.path == '/api/v1/' + resource
    fresh_record = {**record, 'id': 'new-resource'}
    rows.append(fresh_record)
    fresh = await instance.execute({})
    assert fresh['data'] == [fresh_record] and fresh['new_item_count'] == 1
    assert instance.trigger_emitted_event(fresh)
    assert native.ZeffyNode.should_propagate_output(fresh, {'operation': operation})
    event = native.ZeffyNode.resolve_agent_event(fresh)
    assert 'Zeffy' in event['text'] and fresh_record['id'] in event['text']
    assert (fresh_record.get('email') or fresh_record['buyer']['email']) in event['text']
    assert (await instance.execute({}))['data'] == []


@pytest.mark.asyncio
async def test_contact_update_fires_once_and_scope_change_rebaselines(monkeypatch):
    record = deepcopy(FIXTURES['contact'])
    serve(monkeypatch, lambda _: page([record]))
    instance = node('on_new_or_updated_contact')
    state = {}
    state_for(instance, state)
    assert (await instance.execute({}))['data'] == []
    record['updated'] += 1
    assert (await instance.execute({}))['data'] == [record]
    assert (await instance.execute({}))['data'] == []
    repointed = node('on_new_or_updated_contact', created_gte=1700000000)
    state_for(repointed, state)
    assert (await repointed.execute({}))['data'] == []
    assert poll_scope(native.ZeffyNode, {'operation':'on_new_contact', 'goal':'one'}) == poll_scope(
        native.ZeffyNode, {'operation':'on_new_contact', 'goal':'two'})


@pytest.mark.asyncio
async def test_payment_campaign_pagination_and_partial_failure_preserve_state(monkeypatch):
    record = deepcopy(FIXTURES['payment'])
    next_record = {**record, 'id': 'second-payment'}
    fail = False
    def respond(request):
        if request.url.params.get('starting_after'):
            return httpx.Response(429, json={'error':{'message':'rate limited'}}) if fail else page([next_record])
        return page([record], record['id'])
    requests = serve(monkeypatch, respond)
    instance = node('on_new_payment', campaign=record['campaign_id'])
    state = {'seen_ids': []}
    state_for(instance, state)
    fail = True
    with pytest.raises(ValueError, match='429'):
        await instance.execute({})
    assert state == {'seen_ids': []}
    fail = False
    result = await instance.execute({})
    assert result['data'] == [record, next_record]
    assert requests[-1].url.params['starting_after'] == record['id']
    assert all(req.url.params['campaign'] == record['campaign_id'] for req in requests)
    assert all(req.headers['authorization'] == 'Bearer synthetic-zeffy-key' for req in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['repeat_cursor', 'missing_updated', 'malformed'])
async def test_bad_pages_cannot_consume_events(monkeypatch, bad):
    record = deepcopy(FIXTURES['contact'])
    if bad == 'missing_updated':
        record.pop('updated')
    def respond(_):
        if bad == 'malformed':
            return httpx.Response(200, json={'object':'list','data':[record]})
        return page([record], record['id'] if bad == 'repeat_cursor' else None)
    serve(monkeypatch, respond)
    instance = node('on_new_or_updated_contact')
    state = {'seen_ids': []}
    state_for(instance, state)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {'seen_ids': []}
