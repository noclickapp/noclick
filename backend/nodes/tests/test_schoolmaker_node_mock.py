"""Exercise real SchoolMaker nodes with an intercepted HTTP transport, no account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import schoolmaker_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-schoolmaker-key-42'
CREDENTIAL = {'credential_type': 'schoolmaker_api_key', 'api_key': TOKEN}

CASES = {
    'list_members': ({'page': 2, 'email': 'learner@example.com'}, {'page': '2', 'email': 'learner@example.com'}, None),
    'set_member_suspend': ({'email': 'learner@example.com', 'suspend': 'true'}, {'email': 'learner@example.com', 'suspend': 'true'}, None),
    'set_member_ban': ({'email': 'learner@example.com', 'ban': 'false'}, {'email': 'learner@example.com', 'ban': 'false'}, None),
    'get_member_accesses': ({'email': 'learner@example.com'}, {'email': 'learner@example.com'}, None),
    'list_programs': ({}, {}, None),
    'get_program': ({'id': 'program-42'}, {}, None),
    'create_program': ({'name': 'Orientation', 'is_published': False}, {}, {'name': 'Orientation', 'is_published': False}),
    'update_program': ({'id': 'program-42', 'is_published': False}, {}, {'is_published': False}),
    'delete_program': ({'id': 'program-42'}, {}, None),
    'list_offers': ({'published': False}, {'filters[is_published]': 'false'}, None),
    'get_offer': ({'id': 'offer-42'}, {}, None),
    'create_offer': ({'name': 'Starter', 'is_published': False}, {}, {'name': 'Starter', 'is_published': False}),
    'update_offer': ({'id': 'offer-42', 'title': 'New title'}, {}, {'title': 'New title'}),
    'delete_offer': ({'id': 'offer-42'}, {}, None),
    'set_offer_access': ({'id': 'offer-42', 'member_email': 'learner@example.com', 'status': True}, {}, {'member_email': 'learner@example.com', 'status': True}),
    'list_coaching_types': ({}, {}, None),
    'create_coaching_appointment': ({'type_id': 'coaching-42', 'date': '2026-11-10T10:00:00Z', 'duration_hours': 1, 'duration_minutes': 0, 'name': 'Review', 'description': 'Progress review', 'is_published': False, 'member_emails': ['learner@example.com'], 'user_emails': ['coach@example.com']}, {}, 'same'),
    'list_conversation_groups': ({'user_id': 'admin-42', 'page': 2, 'per_page': 20}, {'user_id': 'admin-42', 'page': '2', 'per_page': '20', 'archived': 'false', 'sort': 'last_activity_at'}, None),
    'create_conversation_group': ({'message': 'Welcome!', 'member_participants': ['learner@example.com']}, {}, {'message': 'Welcome!', 'member_participants': ['learner@example.com']}),
    'list_conversation_messages': ({'id': 'group-42', 'user_id': 'admin-42'}, {'user_id': 'admin-42', 'page': '1', 'per_page': '10'}, None),
    'send_conversation_message': ({'id': 'group-42', 'user_id': 'admin-42', 'message': 'Hello'}, {}, {'user_id': 'admin-42', 'message': 'Hello'}),
    'list_community_posts': ({'category_id': 'category-42'}, None, None),
    'create_community_post': ({'category_id': 'category-42', 'title': 'Welcome', 'body': '**Hello everyone**', 'body_format': 'markdown'}, {}, 'same'),
    'list_community_comments': ({'post_id': 'post-42'}, {'page': '1', 'per_page': '30', 'sort': 'oldest'}, None),
    'create_community_comment': ({'post_id': 'post-42', 'body': 'Thanks for sharing!'}, {}, {'body': 'Thanks for sharing!', 'body_format': 'html'}),
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='schoolmaker-test', node_type='automation-schoolmaker', node_data={'config': config, 'credentials': CREDENTIAL.copy()})


def transport(monkeypatch, *, status=200, body=None, raw=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body) if raw is None else httpx.Response(status, content=raw)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_one_published_request_per_operation(monkeypatch, operation):
    config, query, body = CASES[operation]
    fixture = json.loads((Path(__file__).parent / 'fixtures/schoolmaker/operations.json').read_text())[operation]
    response = {'products': [{'id': 'program-42', 'name': 'Orientation'}]} if operation == 'list_programs' else {'id': 'resource-42'}
    calls = transport(monkeypatch, body=response)
    result = await node({'operation': operation, **config}).execute({})
    assert result['status'] == 'success' and result['data'] == response
    assert len(calls) == 1
    request = calls[0]
    expected_path = fixture['path'].replace('{id}', config.get('id', '')).replace('{post_id}', config.get('post_id', ''))
    assert request.method == fixture['method']
    assert request.url.host == 'schoolmaker.co' and request.url.path == '/api/v1' + expected_path
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    if query is not None:
        assert dict(request.url.params) == query
    if body == 'same':
        body = {k: v for k, v in config.items() if k not in ['id', 'post_id']}
    if body is None:
        assert not request.content
    else:
        assert json.loads(request.content) == body
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_preserves_page_cursor_and_account_evidence(monkeypatch):
    payload = {'data': [{'id': 'group-42', 'title': 'Support'}], 'page': 2, 'next_page': 3}
    calls = transport(monkeypatch, body=payload)
    result = await node({'operation': 'list_conversation_groups', 'user_id': 'admin-42', 'page': 2}).execute({})
    assert result['data'] == payload and len(calls) == 1
    transport(monkeypatch, body={'products': [{'id': 'program-42', 'name': 'Orientation'}]})
    result = await node({'operation': native.SchoolMakerNode.connection_evidence.operation}).execute({})
    assert result['items'] == [{'id': 'program-42', 'name': 'Orientation'}]
    for config, payload in [({'operation': 'list_members'}, {'members': [{'id': 'member-42', 'email': 'learner@example.com'}], 'pagination': {'total_count': 1, 'total_pages': 1, 'current_page': 1}}), ({'operation': 'list_members', 'email': 'learner@example.com'}, {'id': 'member-42', 'email': 'learner@example.com'})]:
        transport(monkeypatch, body=payload)
        assert (await node(config).execute({}))['data'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_redacted_and_never_retried(monkeypatch, status):
    calls = transport(monkeypatch, status=status, body={'error': 'Rejected ' + TOKEN})
    result = await node({'operation': 'create_offer', 'name': 'Starter'}).execute({})
    assert len(calls) == 1 and result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('body,raw', [({'errors': ['Permission denied']}, None), (None, b'<html>Unexpected</html>'), ('unexpected scalar', None)])
async def test_error_envelope_or_invalid_success_never_claims_success(monkeypatch, body, raw):
    transport(monkeypatch, body=body, raw=raw)
    assert (await node({'operation': 'list_programs'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_no_content_delete(monkeypatch):
    calls = transport(monkeypatch, status=204, raw=b'')
    assert (await node({'operation': 'delete_offer', 'id': 'offer-42'}).execute({}))['data'] is None
    assert len(calls) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'update_offer', 'id': 'offer-42'},
    {'operation': 'update_program', 'id': 'program-42'},
    {'operation': 'get_offer', 'id': '../members'},
    {'operation': 'create_program', 'name': 'Orientation'},
    {'operation': 'set_offer_access', 'id': 'offer-42', 'status': True},
    {'operation': 'list_conversation_groups'},
    {'operation': 'list_members', 'unpublished_filter': 'anything'},
    {'operation': 'create_community_post', 'category_id': 'category-42', 'body': 'Hello'},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises((ValidationError, ValueError)):
        native.SchoolMakerNode.parse_config({'config': config, 'credentials': CREDENTIAL})


def test_pasted_key_default_and_secret_widget():
    assert native.SchoolMakerAPIKeyCredential(api_key=TOKEN).credential_type == 'schoolmaker_api_key'
    props = native.SchoolMakerAPIKeyCredential.model_json_schema()['properties']
    assert props['api_key']['ui:widget'] == 'password'
    for invalid in ['Bearer ' + TOKEN, 'https://schoolmaker.co/api/key']:
        with pytest.raises(ValueError):
            native.SchoolMakerAPIKeyCredential(api_key=invalid)


@pytest.mark.asyncio
async def test_published_response_envelopes_are_preserved(monkeypatch):
    examples = json.loads((Path(__file__).parent / 'fixtures/schoolmaker/provider_examples.json').read_text())
    routes = json.loads((Path(__file__).parent / 'fixtures/schoolmaker/operations.json').read_text())
    for operation, route in routes.items():
        key = route['method'] + ' ' + route['path']
        if key not in examples:
            continue
        transport(monkeypatch, body=examples[key])
        config = {'operation': operation, **CASES[operation][0]}
        result = await node(config).execute({})
        assert result['status'] == 'success' and result['data'] == examples[key], operation
