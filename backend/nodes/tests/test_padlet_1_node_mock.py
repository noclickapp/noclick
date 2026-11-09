"""Wire contracts and polling behavior; no live credentials or writes."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import padlet_1_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

ROSTER = json.loads((Path(__file__).parent / 'fixtures/padlet-1/roster-ready.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='padlet-test', node_type='automation-padlet-1', node_data={
        'config': config, 'credentials': {'api_key': 'padlet-test-secret-key'},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ({'operation': 'get_current_user'}, 'GET', '/me', {'include': 'boards,organizations'}, None),
    ({'operation': 'get_board', 'board_id': 'abcd1234efgh5678x'}, 'GET', '/boards/abcd1234efgh5678x', {'include': 'posts,sections,comments'}, None),
    ({'operation': 'get_post_attachment_data', 'post_id': 'post_123'}, 'GET', '/posts/post_123/attachmentData', {}, None),
    ({'operation': 'get_organization', 'org_id': 'wksp_abcd1234efgh5678'}, 'GET', '/organizations/wksp_abcd1234efgh5678', {'include': 'users'}, None),
    ({'operation': 'get_user_boards', 'org_id': 'wksp_abcd1234efgh5678', 'user_id': 'user_abcd1234efgh5678'}, 'GET', '/organizations/wksp_abcd1234efgh5678/users/user_abcd1234efgh5678', {'include': 'boards'}, None),
    ({'operation': 'create_post', 'board_id': 'abcd1234efgh5678x', 'subject': 'Hello', 'body': 'Hello is a way of greeting', 'section_id': 'abcd1234efgh5678x', 'custom_fields': {'field_abc123': 'High Priority'}}, 'POST', '/boards/abcd1234efgh5678x/posts', {}, {'data': {'type': 'post', 'attributes': {'content': {'subject': 'Hello', 'body': 'Hello is a way of greeting'}, 'customFields': {'field_abc123': 'High Priority'}}, 'relationships': {'section': {'data': {'id': 'abcd1234efgh5678x'}}}}}),
    ({'operation': 'create_reaction', 'post_id': 'post_123', 'value': 5, 'reaction_type': 'star'}, 'POST', '/posts/post_123/reactions', {}, {'data': {'type': 'reaction', 'attributes': {'value': 5, 'reactionType': 'star'}}}),
    ({'operation': 'create_comment', 'post_id': 'post_123', 'html_content': '<p>Great point, thanks for sharing!</p>', 'attachment_url': 'https://cdn.padlet.dev/uploads/image.png'}, 'POST', '/posts/post_123/comments', {}, {'data': {'type': 'comment', 'attributes': {'htmlContent': '<p>Great point, thanks for sharing!</p>', 'attachment': {'url': 'https://cdn.padlet.dev/uploads/image.png'}}}}),
    ({'operation': 'create_ai_recipe_board', 'board_creation_instructions': 'Plan a lesson', 'role': 'teacher', 'workspace_id': 'wksp_abcd1234efgh5678'}, 'POST', '/ai-recipe-boards', {}, {'data': {'type': 'ai_recipe_board', 'attributes': {'boardCreationInstructions': 'Plan a lesson', 'role': 'teacher', 'workspaceId': 'wksp_abcd1234efgh5678'}}}),
    ({'operation': 'get_ai_recipe_board_status', 'status_key': 'key_123'}, 'GET', '/ai-recipe-boards/status/key_123', {}, None),
    ({'operation': 'read_organization_analytics', 'org_id': 'wksp_abcd1234efgh5678', 'metrics': [{'name': 'postCount'}], 'dimensions': ['month'], 'from_date': '2026-01-01', 'to_date': '2026-03-31'}, 'POST', '/organizations/wksp_abcd1234efgh5678/analytics', {}, {'metrics': [{'name': 'postCount'}], 'dimensions': ['month'], 'from': '2026-01-01', 'to': '2026-03-31'}),
    ({'operation': 'read_organization_users', 'org_id': 'wksp_abcd1234efgh5678', 'status': ['active', 'inactive'], 'user_type': ['teacher'], 'q': 'Ada'}, 'GET', '/organizations/wksp_abcd1234efgh5678/analytics/users', {'status[]': ['active', 'inactive'], 'userType[]': ['teacher'], 'q': 'Ada', 'sort': 'name', 'order': 'asc', 'page': '1', 'perPage': '25'}, None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,params,body', CASES, ids=['padlet-1:' + v[0]['operation'] for v in CASES])
async def test_padlet_1_wire_operations(monkeypatch, config, method, path, params, body):
    response = {'data': {'type': 'test', 'id': '123'}}
    requests = transport(monkeypatch, response)
    assert await node(config).execute({}) == response
    request = requests[0]
    assert request.method == method and request.url.path == '/v1' + path
    assert request.url.host == 'api.padlet.dev'
    assert request.headers['X-Api-Key'] == 'padlet-test-secret-key'
    assert request.headers['Accept'] == native.MEDIA
    for key, value in params.items():
        assert request.url.params.get_list(key) == (value if isinstance(value, list) else [value])
    assert set(request.url.params) == set(params)
    if body is not None:
        assert request.headers['Content-Type'] == native.MEDIA
        assert json.loads(request.content) == body


@pytest.mark.asyncio
async def test_padlet_1_documented_roster_payload_preserved(monkeypatch):
    transport(monkeypatch, ROSTER)
    assert await node({'operation': 'read_organization_users', 'org_id': 'wksp_abcd1234efgh5678'}).execute({}) == ROSTER


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_padlet_1_refusals_propagate(monkeypatch, status):
    transport(monkeypatch, {'errors': [{'detail': 'API key rejected'}]}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_current_user'}).execute({})


@pytest.mark.asyncio
async def test_padlet_1_error_envelope_not_success(monkeypatch):
    transport(monkeypatch, {'errors': [{'detail': 'API key rejected'}]})
    with pytest.raises(ValueError, match='API key rejected'):
        await node({'operation': 'get_current_user'}).execute({})


@pytest.mark.asyncio
async def test_padlet_1_recent_signup_window_and_human_event(monkeypatch):
    # The provider-authored first page is a bounded signup window.
    body = copy.deepcopy(ROSTER)
    requests = transport(monkeypatch, body)
    n = node({'operation': 'on_new_organization_user', 'org_id': 'wksp_abcd1234efgh5678'})
    n._filter_unseen = AsyncMock(return_value=body['data'])
    output = await n.execute({})
    n._filter_unseen.assert_awaited_once()
    assert output['users'] == ROSTER['data'] and output['new_user_count'] == 1
    assert dict(requests[0].url.params) == {'sort': 'signupDate', 'order': 'desc', 'page': '1', 'perPage': '25'}
    event = native.PadletNode.resolve_agent_event(output)
    assert all(value in event['text'] for value in ['Ada Lovelace', 'user_abcd1234efgh5678', 'wksp_abcd1234efgh5678', 'get_user_boards'])
    assert native.PadletNode.resolve_agent_event({'users': [], 'org_id': 'wksp_abcd1234efgh5678'}) is None


@pytest.mark.asyncio
async def test_padlet_1_poll_baseline_and_scope(monkeypatch):
    body = copy.deepcopy(ROSTER)
    transport(monkeypatch, body)
    n = node({'operation': 'on_new_organization_user', 'org_id': 'wksp_abcd1234efgh5678'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        new, result = mutator(state)
        if new is not None:
            state = new
        return result
    monkeypatch.setattr(n, '_update_node_state', update)
    assert (await n.execute({}))['users'] == []
    assert (await n.execute({}))['users'] == []
    body['data'][0]['id'] = 'new-user'
    # MockTransport encodes body each time, reflecting the new roster member.
    assert (await n.execute({}))['users'][0]['id'] == 'new-user'
    a = {'operation': 'on_new_organization_user', 'org_id': 'wksp_abcd1234efgh5678'}
    assert poll_scope(native.PadletNode, a) != poll_scope(native.PadletNode, {**a, 'org_id': 'wksp_efgh5678abcd1234'})
    assert poll_scope(native.PadletNode, a) != poll_scope(native.PadletNode, {**a, 'limit': 100})
    assert poll_scope(native.PadletNode, a) == poll_scope(native.PadletNode, {**a, 'schedule_id': 'changed'})


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'status': 'pending'}, {'status': 'failed'}, {'page': 2}])
async def test_padlet_1_incomplete_poll_never_updates_state(monkeypatch, change):
    body = copy.deepcopy(ROSTER)
    body['meta'].update(page=1, totalCount=1, totalPages=1, **{})
    body['meta'].update(change)
    transport(monkeypatch, body)
    n = node({'operation': 'on_new_organization_user', 'org_id': 'wksp_abcd1234efgh5678'})
    n._filter_unseen = AsyncMock()
    with pytest.raises(ValueError):
        await n.execute({})
    n._filter_unseen.assert_not_awaited()


def test_padlet_1_credential_default_and_connection_evidence():
    assert native.PadletAPIKey(api_key=' padlet-test-secret-key ').credential_type == 'padlet_1_api_key'
    assert native.PadletAPIKey(api_key=' padlet-test-secret-key ').api_key == 'padlet-test-secret-key'
    assert native.PadletNode.connection_evidence.identity_operation == 'get_current_user'


@pytest.mark.asyncio
async def test_padlet_1_one_request_per_tick_and_duplicates(monkeypatch):
    n = node({'operation': 'on_new_organization_user', 'org_id': 'wksp_abcd1234efgh5678'})
    n._request = AsyncMock(return_value=copy.deepcopy(ROSTER))
    n._filter_unseen = AsyncMock(return_value=ROSTER['data'])
    assert (await n.execute({}))['new_user_count'] == 1
    n._request.assert_awaited_once()
    assert n._request.await_args.kwargs['params'] == {'sort': 'signupDate', 'order': 'desc', 'page': 1, 'perPage': 25}
    duplicate = copy.deepcopy(ROSTER)
    duplicate['data'].append(copy.deepcopy(duplicate['data'][0]))
    n._request = AsyncMock(return_value=duplicate)
    n._filter_unseen.reset_mock()
    with pytest.raises(ValueError, match='duplicate users'):
        await n.execute({})
    n._filter_unseen.assert_not_awaited()


@pytest.mark.parametrize('config', [
    {'operation': 'get_board', 'board_id': '1'},
    {'operation': 'get_organization', 'org_id': '1'},
    {'operation': 'create_comment', 'post_id': 'post_123', 'html_content': 'Hi', 'attachment_url': '1'},
    {'operation': 'create_post', 'board_id': 'abcd1234efgh5678x', 'status': 'pending'},
])
def test_padlet_1_contract_constraints(config):
    assert native.PadletNode.validate_config({'config': config})['valid'] is False
