"""Exercise FlowSavvy's published HTTP routes and poll revision detection.

Fixtures use synthetic values within the provider's documented schemas; no
working FlowSavvy account or live writes are needed for these regressions.
"""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.core.credential_connect import shape_credential
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.flowsavvy_node import BASE_URL, FlowSavvyAPIKeyCredential, FlowSavvyNode

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/flowsavvy/items.json').read_text())
KEY = 'synthetic-personal-key-42'


def node(operation, **values):
    return NodeFactory.create_node(node_id='flowsavvy-test', node_type='automation-flowsavvy', node_data={
        'config': {'operation': operation, **values},
        'credentials': {'credential_type': 'flowsavvy_api_key', 'api_key': KEY},
    })


@pytest.mark.parametrize('operation,values,method,path,params,body,status', [
    ('list_items', {'itemType': 'task', 'listId': 'inbox', 'completed': False, 'pageToken': 'next', 'modifiedAfter': '2026-11-10T00:00:00Z', 'query': 'launch', 'limit': 10}, 'GET', '/api/items', {'itemType': 'task', 'listId': 'inbox', 'completed': 'false', 'pageToken': 'next', 'modifiedAfter': '2026-11-10T00:00:00Z', 'query': 'launch', 'limit': '10'}, None, 200),
    ('get_item', {'id': 'task-1', 'occurrenceDate': '2026-11-10'}, 'GET', '/api/items/task-1', {'occurrenceDate': '2026-11-10'}, None, 200),
    ('delete_item', {'id': 'task-1', 'occurrenceDate': '2026-11-10', 'scope': 'thisOccurrence'}, 'DELETE', '/api/items/task-1', {'occurrenceDate': '2026-11-10', 'scope': 'thisOccurrence'}, None, 204),
    ('create_task', {'title': 'Plan', 'durationMinutes': 30, 'listId': 'inbox'}, 'POST', '/api/tasks', {}, {'title': 'Plan', 'durationMinutes': 30, 'listId': 'inbox'}, 200),
    ('update_task', {'id': 'task-1', 'title': 'Plan', 'priority': 'high', 'progressMinutes': 10, 'occurrenceDate': '2026-11-10', 'scope': 'thisAndFutureOccurrences'}, 'PUT', '/api/tasks/task-1', {'occurrenceDate': '2026-11-10', 'scope': 'thisAndFutureOccurrences'}, {'title': 'Plan', 'priority': 'high', 'progressMinutes': 10}, 200),
    ('create_event', {'title': 'Review', 'startDateTime': '2026-11-10T14:00:00', 'endDateTime': '2026-11-10T15:00:00', 'allDay': False, 'busy': True}, 'POST', '/api/events', {}, {'title': 'Review', 'startDateTime': '2026-11-10T14:00:00', 'endDateTime': '2026-11-10T15:00:00', 'allDay': False, 'busy': True}, 200),
    ('update_event', {'id': 'event-1', 'title': 'Review', 'startDateTime': '2026-11-10T14:00:00', 'endDateTime': '2026-11-10T15:00:00', 'calendarId': 'work'}, 'PUT', '/api/events/event-1', {}, {'title': 'Review', 'startDateTime': '2026-11-10T14:00:00', 'endDateTime': '2026-11-10T15:00:00', 'calendarId': 'work'}, 200),
    ('complete_task', {'id': 'task-1', 'occurrenceDate': '2026-11-10'}, 'POST', '/api/tasks/task-1/complete', {'occurrenceDate': '2026-11-10'}, None, 200),
    ('uncomplete_task', {'id': 'task-1'}, 'POST', '/api/tasks/task-1/uncomplete', {}, None, 204),
    ('get_schedule', {'startDate': '2026-11-10', 'endDate': '2026-11-11'}, 'GET', '/api/schedule', {'startDate': '2026-11-10', 'endDate': '2026-11-11'}, None, 200),
    ('recalculate', {'reschedulePastTasks': True}, 'POST', '/api/recalculate', {'reschedulePastTasks': 'true'}, None, 204),
    ('list_calendars', {}, 'GET', '/api/calendars', {}, None, 200),
    ('list_lists', {}, 'GET', '/api/lists', {}, None, 200),
    ('list_scheduling_hours', {}, 'GET', '/api/scheduling-hours', {}, None, 200),
])
@pytest.mark.asyncio
async def test_published_operation(operation, values, method, path, params, body, status):
    payload = {'items': [FIXTURE['task']], 'nextPageToken': 'following'}
    with respx.mock(assert_all_called=True) as router:
        route = router.route(method=method, url=BASE_URL + path).mock(return_value=httpx.Response(status, json=payload) if status != 204 else httpx.Response(204))
        out = await node(operation, **values).execute({})
    request = route.calls[0].request
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    assert dict(request.url.params) == params
    assert (json.loads(request.content) if request.content else None) == body
    assert out['success'] is True
    if status == 200:
        assert out['items'] == payload['items'] and out['nextPageToken'] == 'following'
    assert len(route.calls) == 1


def test_manual_credential_and_discovery():
    assert NODE_REGISTRY['automation-flowsavvy'] is FlowSavvyNode
    assert FlowSavvyAPIKeyCredential(api_key=KEY).credential_type == 'flowsavvy_api_key'
    shaped, errors, resolved = shape_credential('flowsavvy_api_key', {'api_key': ' ' + KEY + ' '})
    assert not errors and shaped['api_key'] == KEY
    assert FlowSavvyNode.connection_evidence.operation == 'list_lists'
    for bad in ['https://example.com/key', '<token>', 'Bearer abc']:
        with pytest.raises(ValidationError):
            FlowSavvyAPIKeyCredential(api_key=bad)


def test_filters_and_readonly_properties_rejected():
    with pytest.raises(ValueError, match='item type to task'):
        node('list_items', listId='work')
    with pytest.raises(ValueError, match='item type to event'):
        node('list_items', itemType='task', calendarId='work')
    with pytest.raises(ValueError):
        node('create_task', title='Plan', completed=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_no_redirect_or_write_retry_and_secret_redacted(status):
    with respx.mock as router:
        route = router.post(BASE_URL + '/api/tasks').mock(return_value=httpx.Response(status, text='Provider error ' + KEY, headers={'Location': 'https://other.example'}))
        with pytest.raises(ValueError) as error:
            await node('create_task', title='Plan').execute({})
    assert KEY not in str(error.value)
    assert f'HTTP {status}' in str(error.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,kind,scope_key', [('on_task_updated', 'task', 'listId'), ('on_event_updated', 'event', 'calendarId')])
async def test_poll_baseline_revision_pagination_and_agent_event(operation, kind, scope_key):
    instance = node(operation, **{scope_key: 'work'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changes, result = mutator(copy.deepcopy(state))
        if changes is not None:
            state = changes
        return result
    instance._update_node_state = update
    row = copy.deepcopy(FIXTURE[kind])
    requests = []
    def respond(request):
        requests.append(request)
        assert request.url.params['itemType'] == kind
        assert request.url.params[scope_key] == 'work'
        if request.url.params.get('completed') == 'true':
            return httpx.Response(200, json={'items': []})
        if not request.url.params.get('pageToken'):
            return httpx.Response(200, json={'items': [], 'nextPageToken': 'page-2'})
        assert request.url.params['pageToken'] == 'page-2'
        return httpx.Response(200, json={'items': [row]})
    with respx.mock as router:
        router.get(BASE_URL + '/api/items').mock(side_effect=respond)
        assert (await instance.execute({}))['new_item_count'] == 0
        assert instance.trigger_produced_no_event({})
        row['lastModified'] = '2026-11-10T11:00:00Z'
        out = await instance.execute({})
        assert out['items'] == [row] and out['new_item_count'] == 1
        assert instance.trigger_emitted_event(out)
        event = FlowSavvyNode.resolve_agent_event(out)
        assert row['id'] in event['text'] and row['title'] in event['text']
        assert 'work' in event['text'] and row['url'] in event['text']
        assert (await instance.execute({}))['new_item_count'] == 0
        assert FlowSavvyNode.resolve_agent_event({'operation': operation, 'items': []}) is None
    assert poll_scope(FlowSavvyNode, {'operation': operation, scope_key: 'work'}) != poll_scope(FlowSavvyNode, {'operation': operation, scope_key: 'personal'})


@pytest.mark.asyncio
async def test_bad_poll_page_does_not_advance_state():
    instance = node('on_task_updated')
    instance._filter_unseen = AsyncMock()
    with respx.mock as router:
        router.get(BASE_URL + '/api/items').mock(return_value=httpx.Response(200, json={'items': [FIXTURE['task']], 'nextPageToken': 'same'}))
        with pytest.raises(ValueError, match='pagination did not advance'):
            await instance.execute({})
    instance._filter_unseen.assert_not_called()


@pytest.mark.parametrize('operation,kind,location_key', [('on_task_updated', 'task', 'listId'), ('on_event_updated', 'event', 'calendarId')])
def test_agent_event_reads_only_documented_subtype_fields(operation, kind, location_key):
    class SchemaRow(dict):
        def get(self, key, default=None):
            assert key != ('calendarId' if kind == 'task' else 'listId'), 'undeclared subtype field'
            return super().get(key, default)
    item = SchemaRow(FIXTURE[kind])
    item[location_key] = None
    event = FlowSavvyNode.resolve_agent_event({'operation': operation, 'items': [item]})
    assert item['title'] in event['text'] and 'list/calendar default' in event['text']
