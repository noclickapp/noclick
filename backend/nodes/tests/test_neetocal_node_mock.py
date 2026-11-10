"""Exercise documented NeetoCal payloads at the HTTP boundary and poll state seam."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.neetocal_node import NeetoCalAPIKeyCredential, NeetoCalNode
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/neetocal/documented_responses.json').read_text())
CREDENTIAL = {'credential_type': 'neetocal_api_key', 'api_key': 'neetocal-unit-test-key', 'subdomain': 'spinkart'}


def node(config):
    return NodeFactory.create_node(node_id='neetocal-test', node_type='automation-neetocal',
        node_data={'config': config, 'credentials': CREDENTIAL})


def wire(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as value:
            yield value
    monkeypatch.setattr('nodes.neetocal_node.guarded_async_client', client)


@pytest.mark.asyncio
async def test_documented_booking_and_auth_are_preserved(monkeypatch):
    example = FIXTURES['get_booking']['body']
    def handler(request):
        assert request.url == 'https://spinkart.neetocal.com/api/external/v2/bookings/8sqtzrs'
        assert request.headers['X-Api-Key'] == CREDENTIAL['api_key']
        assert 'Authorization' not in request.headers
        return httpx.Response(200, json=example)
    wire(monkeypatch, handler)
    result = await node({'operation': 'get_booking', 'booking_sid': '8sqtzrs'}).execute({})
    assert result['data'] == example
    assert result['data']['sid'] == '8sqtzrs'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,expected', [
    ('create_meeting_outcome', {'name': 'Pricing Discussion', 'color': 'yellow'}, {'meeting_outcome': {'name': 'Pricing Discussion', 'color': 'yellow'}}),
    ('update_booking', {'booking_id': 'hda6gxy', 'status': 'cancelled', 'cancel_reason': 'I am not available'}, {'status': 'cancelled', 'cancel_reason': 'I am not available'}),
    ('update_booking', {'booking_id': 'hda6gxy', 'meeting_outcome_id': None}, {'meeting_outcome_id': None}),
])
async def test_write_shapes_and_explicit_null(monkeypatch, operation, config, expected):
    def handler(request):
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={})
    wire(monkeypatch, handler)
    await node({'operation': operation, **config}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'update_booking', 'booking_id': 'hda6gxy', 'name': 'Eve Smith'},
    {'operation': 'update_booking', 'booking_id': 'hda6gxy', 'status': 'cancelled', 'meeting_outcome_id': 'outcome'},
    {'operation': 'update_booking', 'booking_id': 'hda6gxy', 'slot_date': '2025-07-25'},
    {'operation': 'get_booking', 'booking_sid': '../team-members'},
    {'operation': 'get_booking', 'booking_sid': 'abc?key=leak'},
])
def test_invalid_changes_and_path_injection_are_rejected(config):
    assert not NeetoCalNode.validate_config({'config': config, 'credentials': CREDENTIAL})['valid']


@pytest.mark.parametrize('value', ['https://spinkart.neetocal.com', 'spinkart.neetocal.com', 'spinkart@evil.com', 'a/b', 'a:443', 'localhost.'])
def test_workspace_is_one_provider_subdomain(value):
    with pytest.raises(ValidationError):
        NeetoCalAPIKeyCredential(api_key=CREDENTIAL['api_key'], subdomain=value)


def test_manual_credentials_have_a_default_type():
    assert NeetoCalAPIKeyCredential(api_key=CREDENTIAL['api_key'], subdomain=' SPINKART ').credential_type == 'neetocal_api_key'


@pytest.mark.asyncio
async def test_poll_baselines_emits_once_and_rebaselines_scope(monkeypatch):
    first = copy.deepcopy(FIXTURES['get_booking']['body'])
    rows = [first]
    state = {}
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={'bookings': rows, 'pagination': {'total_pages': 1}})
    wire(monkeypatch, handler)
    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result
    n = node({'operation': 'on_new_booking'})
    monkeypatch.setattr(n, '_update_node_state', update)
    assert (await n.execute({}))['bookings'] == []
    second = {**first, 'id': 'second-booking-id', 'sid': 'new123'}
    rows = [second, first]
    result = await n.execute({})
    assert result['bookings'] == [second]
    event = n.resolve_agent_event(result)
    assert second['email'] in event['text'] and second['sid'] in event['text']
    assert second['admin_booking_url'] in event['text']
    assert n.trigger_emitted_event(result)
    assert (await n.execute({}))['bookings'] == []
    assert n.trigger_produced_no_event({})
    assert calls[0] == {'page_number': '1', 'page_size': '100', 'sorting_order': 'desc'}
    repointed = node({'operation': 'on_new_booking', 'host_email': 'oliver@example.com'})
    monkeypatch.setattr(repointed, '_update_node_state', update)
    assert (await repointed.execute({}))['bookings'] == []


@pytest.mark.asyncio
async def test_poll_does_not_advance_state_when_scan_is_incomplete(monkeypatch):
    example = FIXTURES['get_booking']['body']
    def handler(request):
        return httpx.Response(200, json={'bookings': [example], 'pagination': {'total_pages': 21}})
    wire(monkeypatch, handler)
    n = node({'operation': 'on_new_booking'})
    async def no_state(*args, **kwargs):
        pytest.fail('An incomplete scan must not write seen IDs')
    monkeypatch.setattr(n, '_update_node_state', no_state)
    with pytest.raises(ValueError, match='2,000'):
        await n.execute({})


@pytest.mark.asyncio
async def test_api_rejection_preserves_provider_error_without_key(monkeypatch):
    wire(monkeypatch, lambda request: httpx.Response(401, json={'error': 'Invalid API key'}))
    with pytest.raises(ValueError, match='HTTP 401:.*Invalid API key'):
        await node({'operation': 'list_scheduling_links'}).execute({})


@pytest.mark.asyncio
async def test_updated_booking_fires_once_per_documented_update_timestamp(monkeypatch):
    original = copy.deepcopy(FIXTURES['get_booking']['body'])
    rows = [original]
    wire(monkeypatch, lambda request: httpx.Response(200, json={'bookings': rows, 'pagination': {'total_pages': 1}}))
    n = node({'operation': 'on_new_or_updated_booking'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result
    monkeypatch.setattr(n, '_update_node_state', update)
    assert (await n.execute({}))['bookings'] == []
    rows = [{**original, 'updated_at': '2026-11-10T06:00:00.000Z', 'status': 'cancelled'}]
    result = await n.execute({})
    assert result['bookings'] == rows
    text = n.resolve_agent_event(result)['text']
    assert 'cancelled' in text and 'new or updated' in text
    assert (await n.execute({}))['bookings'] == []
