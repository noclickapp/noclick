"""Exercise Kantata OX wire bodies, canonical envelopes and poll state transitions.

The provider's handwritten response examples pin how associated data is kept
out of results. Additional synthetic cases cover errors and pagination bounds.
"""
import copy
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.core.poll_trigger import poll_scope
from nodes.kantataox_node import (
    BASE_URL, CONFIG_MODELS, TRIGGER_MODELS, KantataOXNode,
    KantataOXNodeConfig, KantataOXTokenCredential, records,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'kantataox'


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def node(operation, **values):
    config_cls = {**CONFIG_MODELS, **TRIGGER_MODELS}[operation]
    return KantataOXNode(node_id='kantataox-test', node_type='automation-kantataox', node_data={},
        config=KantataOXNodeConfig(config=config_cls(**values), credentials=KantataOXTokenCredential(api_token='personal-test-token')),
        sio=Mock(), sid='sid', workflow_id='workflow', user_id='user')


def envelope(resource, identifier='123', **fields):
    return {'count': 1, 'results': [{'key': resource, 'id': identifier}], resource: {identifier: fields}}


@pytest.mark.asyncio
async def test_provider_projects_example_preserves_order_and_excludes_associations():
    with respx.mock(assert_all_called=True) as router:
        route = router.get(BASE_URL + '/workspaces').mock(return_value=httpx.Response(200, json=fixture('projects')))
        result = await node('list_projects', per_page=1).execute({})
    assert [r['id'] for r in result['items']] == ['10', '11']
    assert result['items'][0]['title'] == 'some project'
    assert 'users' not in result
    assert result['next_page'] == 2
    assert route.calls[0].request.headers['Authorization'] == 'Bearer personal-test-token'


@pytest.mark.asyncio
async def test_provider_post_example_returns_content_and_reply_ids():
    with respx.mock:
        respx.get(BASE_URL + '/posts/16270634').mock(return_value=httpx.Response(200, json=fixture('post')))
        result = await node('get_post', id=16270634).execute({})
    assert result['data']['message'] == 'Hello World'
    assert result['data']['user_id'] == '2'
    assert result['data']['workspace_id'] == '2249167'


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,values,method,path,resource,expected', [
    ('create_project', {'title': 'Delivery'}, 'POST', '/workspaces', 'workspaces', {'workspace': {'title': 'Delivery', 'budgeted': False}}),
    ('update_project', {'id': 123, 'archived': False, 'title': 'Reopened'}, 'PUT', '/workspaces/123', 'workspaces', {'workspace': {'title': 'Reopened', 'archived': False}}),
    ('create_task', {'workspace_id': 123, 'title': 'Review', 'assignee_ids': [9], 'percentage_complete': 0}, 'POST', '/stories', 'stories', {'story': {'workspace_id': 123, 'title': 'Review', 'assignee_ids': [9], 'percentage_complete': 0}}),
    ('update_task', {'id': 123, 'percentage_complete': 100}, 'PUT', '/stories/123', 'stories', {'story': {'percentage_complete': 100}}),
    ('create_time_entry', {'workspace_id': 123, 'date_performed': '2025-01-23', 'time_in_minutes': 60, 'billable': False}, 'POST', '/time_entries', 'time_entries', {'time_entry': {'workspace_id': 123, 'date_performed': '2025-01-23', 'time_in_minutes': 60, 'billable': False}}),
    ('update_time_entry', {'id': 123, 'time_in_minutes': 0}, 'PUT', '/time_entries/123', 'time_entries', {'time_entry': {'time_in_minutes': 0}}),
    ('create_post', {'workspace_id': 123, 'message': 'Post'}, 'POST', '/posts', 'posts', {'post': {'workspace_id': 123, 'message': 'Post'}}),
])
async def test_writes_send_the_typed_singular_body(operation, values, method, path, resource, expected):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, BASE_URL + path).mock(return_value=httpx.Response(200, json=envelope(resource)))
        result = await node(operation, **values).execute({})
    assert json.loads(route.calls[0].request.content) == expected
    assert result['data']['id'] == '123'


@pytest.mark.asyncio
async def test_connection_identity_and_delete_acknowledgement():
    with respx.mock:
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(200, json=envelope('users', full_name='Example User')))
        identity = await node('get_me').execute({})
        respx.delete(BASE_URL + '/time_entries/123').mock(return_value=httpx.Response(204))
        deleted = await node('delete_time_entry', id=123).execute({})
    assert identity['data']['full_name'] == 'Example User'
    assert deleted == {'deleted_id': '123', 'acknowledged': True}


@pytest.mark.asyncio
async def test_rejection_preserves_provider_message_and_hides_token():
    with respx.mock:
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(401, json={'errors': [{'type': 'oauth', 'message': 'Invalid OAuth 2 Request'}]}))
        with pytest.raises(ValueError, match='HTTP 401: Invalid OAuth 2 Request'):
            await node('get_me').execute({})
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(401, json={'errors': [{'message': 'Rejected personal-test-token'}]}))
        with pytest.raises(ValueError) as exc:
            await node('get_me').execute({})
    assert 'personal-test-token' not in str(exc.value)


@pytest.mark.asyncio
async def test_does_not_follow_redirect_or_acknowledge_error_envelope():
    with respx.mock:
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(302, headers={'Location': 'https://example.org'}))
        with pytest.raises(ValueError, match='HTTP 302'):
            await node('get_me').execute({})
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(200, json={'errors': [{'message': 'Rejected'}]}))
        with pytest.raises(ValueError, match='did not confirm'):
            await node('get_me').execute({})


@pytest.mark.parametrize('operation,values', [
    ('get_task', {'id': '../users/me'}),
    ('update_task', {'id': 1}),
    ('create_project', {'title': 'Budget', 'budgeted': True}),
    ('create_task', {'workspace_id': 1, 'title': 'Task', 'percentage_complete': 101}),
    ('create_time_entry', {'workspace_id': 1, 'date_performed': 'tomorrow', 'time_in_minutes': 60}),
    ('list_projects', {'per_page': 201}),
])
def test_invalid_configs_fail_before_request(operation, values):
    with pytest.raises(ValidationError):
        node(operation, **values)


def test_canonical_references_are_required():
    bad = fixture('post')
    bad['results'][0]['id'] = 'missing'
    with pytest.raises(ValueError, match='absent'):
        records(bad, 'posts')
    bad['results'][0]['key'] = 'users'
    with pytest.raises(ValueError, match='invalid result reference'):
        records(bad, 'posts')


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,example', [
    ('on_new_or_updated_project', 'projects'), ('on_new_or_updated_post', 'post'),
    ('on_new_or_updated_task', 'task-sdk'), ('on_new_or_updated_time_entry', 'time-entry-sdk'),
])
async def test_poll_provider_examples_baseline_repeat_and_changed_record(operation, example):
    # The provider examples predate updated_at. Changed content must still be noticed.
    n = node(operation)
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(copy.deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    n._update_node_state = update
    response = fixture(example)
    resource = {'post': 'posts', 'projects': 'workspaces', 'task-sdk': 'stories', 'time-entry-sdk': 'time_entries'}[example]
    path = '/' + resource
    with respx.mock:
        route = respx.get(BASE_URL + path).mock(return_value=httpx.Response(200, json=response))
        assert (await n.execute({}))['items'] == []
        assert (await n.execute({}))['items'] == []
        changed = copy.deepcopy(response)
        identifier = changed['results'][0]['id']
        changed[resource][identifier][{'posts': 'message', 'workspaces': 'title', 'stories': 'title', 'time_entries': 'notes'}[resource]] = 'Updated content'
        route.mock(return_value=httpx.Response(200, json=changed))
        result = await n.execute({})
        assert result['new_item_count'] == 1
        assert (await n.execute({}))['items'] == []
    event = KantataOXNode.resolve_agent_event(result)
    assert 'Updated content' in event['text']
    assert identifier in event['text']
    assert KantataOXNode.should_propagate_output(result, {'operation': operation})
    assert not KantataOXNode.should_propagate_output({'new_item_count': 0}, {'operation': operation})


@pytest.mark.asyncio
async def test_poll_reads_all_pages_and_does_not_consume_state_on_partial_response():
    n = node('on_new_or_updated_task', workspace_id=123)
    filtered = Mock()
    async def fresh(items, key):
        filtered(items)
        return items
    n._filter_unseen = fresh
    first = envelope('stories', '1', title='First', updated_at='2025-01-01T00:00:00Z')
    first['count'] = 201
    second = envelope('stories', '2', title='Second', updated_at='2025-01-02T00:00:00Z')
    second['count'] = 201
    with respx.mock:
        route = respx.get(BASE_URL + '/stories').mock(side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)])
        out = await n.execute({})
    assert len(out['items']) == 2
    assert route.calls[1].request.url.params['page'] == '2'
    assert route.calls[0].request.url.params['workspace_id'] == '123'
    assert route.calls[0].request.url.params['order'] == 'updated_at:desc'
    filtered.reset_mock()
    with respx.mock:
        respx.get(BASE_URL + '/stories').mock(side_effect=[httpx.Response(200, json=first), httpx.Response(503)])
        with pytest.raises(ValueError, match='HTTP 503'):
            await n.execute({})
    filtered.assert_not_called()


def test_poll_scope_uses_only_declared_watch_fields():
    one = {'operation': 'on_new_or_updated_task', 'workspace_id': 1}
    assert poll_scope(KantataOXNode, one) == poll_scope(KantataOXNode, {**one, 'label': 'Renamed', 'goal': 'Watch'})
    assert poll_scope(KantataOXNode, one) != poll_scope(KantataOXNode, {**one, 'workspace_id': 2})


def test_manual_credential_defaults_and_token_shape():
    assert KantataOXTokenCredential(api_token=' personal-test-token ').credential_type == 'kantataox_api_token'
    assert KantataOXTokenCredential(api_token=' personal-test-token ').api_token == 'personal-test-token'
    for value in ['Bearer token', 'https://example.com/token']:
        with pytest.raises(ValidationError):
            KantataOXTokenCredential(api_token=value)


@pytest.mark.asyncio
async def test_connection_evidence_names_the_token_owner(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    async def run(**kwargs):
        assert kwargs['operation'] == 'get_me'
        return {'data': {'id': '123', 'full_name': 'Example User'}}
    monkeypatch.setattr('nodes.core.run_op.run_node_operation', run)
    evidence = await collect_evidence(node_type='automation-kantataox', user_id='user',
        credential_data={'credential_type': 'kantataox_api_token', 'api_token': 'personal-test-token'})
    assert evidence.reachable is True
    assert evidence.account_label == 'Example User'


@pytest.mark.asyncio
async def test_async_acceptance_does_not_claim_deletion():
    with respx.mock:
        respx.delete(BASE_URL + '/time_entries/123').mock(return_value=httpx.Response(202))
        with pytest.raises(ValueError, match='HTTP 202'):
            await node('delete_time_entry', id=123).execute({})


@pytest.mark.asyncio
async def test_long_reflected_token_is_redacted_before_error_is_bounded():
    n = node('get_me')
    long_token = 'private-token-' + 's' * 2000
    n.config.credentials.api_token = long_token
    with respx.mock:
        respx.get(BASE_URL + '/users/me').mock(return_value=httpx.Response(401, json={'errors': [{'message': 'Rejected ' + long_token}]}))
        with pytest.raises(ValueError) as exc:
            await n.execute({})
    assert '[redacted]' in str(exc.value)
    assert long_token[:30] not in str(exc.value)
