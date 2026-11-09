"""Exercise native Quiltt requests with published REST response examples.

These tests use an offline transport and never sign in or contact an account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import quiltt_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/quiltt/rest_examples.json').read_text())
KEY = 'quiltt-offline-fixture-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='quiltt-fixture', node_type='automation-quiltt', node_data={
        'config': config, 'credentials': {'credential_type': 'quiltt_api_key', 'api_key': KEY},
    })


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('row', EXAMPLES, ids=lambda row: row['operation'])
async def test_published_examples_and_exact_request(monkeypatch, row):
    def reply(request):
        if row['body'] is None:
            return httpx.Response(row['status'])
        return httpx.Response(row['status'], json=row['body'], headers={'current-page': '1', 'total-pages': '4'})
    requests = transport(monkeypatch, reply)
    result = await node(row['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == row['method']
    assert request.url.host == 'api.quiltt.io' and request.url.path == row['path']
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    if row['body'] is not None:
        assert result['data'] == row['body']
    else:
        assert result['accepted'] is True and result['http_status'] == row['status']
    if row['method'] in {'POST', 'PATCH'}:
        expected = {k: v for k, v in row['config'].items() if k not in {'operation', 'profile_id', 'connection_id', 'account_id', 'subscription_id'}}
        if row['operation'] == 'import_plaid_connection':
            expected = {'mode': 'REALTIME', 'migrateWebhook': True, **expected}
        if expected:
            assert json.loads(request.content) == expected
        else:
            assert not request.content
    if row['operation'] in {'list_profiles', 'list_subscriptions'}:
        assert dict(request.url.params) == {'page': '1', 'limit': '25'}
        assert result['pagination'] == {'current-page': '1', 'total-pages': '4'}
    if row['operation'] == 'search_institutions':
        assert request.url.params['routingNumber'] == '021000021'
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_errors_do_not_succeed_or_follow_redirects(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={'message': 'Rejected', 'instruction': KEY}, headers={'Location': 'https://example.com'}))
    result = await node({'operation': 'list_profiles'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert KEY not in str(result) and 'Rejected' in result['error'] and len(requests) == 1


@pytest.mark.asyncio
async def test_selected_page_and_empty_list_are_preserved(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json=[]))
    result = await node({'operation': 'list_profiles', 'page': 3, 'limit': 10}).execute({})
    assert result['data'] == [] and result['status'] == 'success'
    assert dict(requests[0].url.params) == {'page': '3', 'limit': '10'}


@pytest.mark.asyncio
async def test_bad_list_shape_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'unexpected': True}))
    with pytest.raises(ValueError, match='list response'):
        await node({'operation': 'list_profiles'}).execute({})


def test_manual_credential_default_and_operation_validation():
    credential = native.QuilttApiKeyCredential(api_key=KEY)
    assert credential.credential_type == 'quiltt_api_key'
    assert native.QuilttNode.connection_evidence.operation == 'list_profiles'
    for config in [
        {'operation': 'get_profile', 'profile_id': '../other'},
        {'operation': 'get_profile', 'profile_id': 'p_x?admin=true'},
        {'operation': 'list_profiles', 'page': 0},
        {'operation': 'create_profile', 'email': 'invalid'},
        {'operation': 'create_subscription', 'name': 'fixture', 'targetUrl': 'http://example.com', 'eventTypes': ['profile.created']},
        {'operation': 'create_subscription', 'name': 'fixture', 'targetUrl': 'https://example.com', 'eventTypes': ['invalid']},
        {'operation': 'import_plaid_connection', 'profile_id': 'p_x'},
    ]:
        with pytest.raises(ValueError):
            native.QuilttNode.parse_config({'config': config})
    with pytest.raises(ValidationError):
        native.QuilttApiKeyCredential(api_key='Bearer invalid')


@pytest.mark.asyncio
async def test_patch_omits_unsupplied_attributes(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(200, json={'id': 'p_fixture', 'name': 'Updated'}))
    await node({'operation': 'update_profile', 'profile_id': 'p_fixture', 'name': 'Updated'}).execute({})
    assert json.loads(requests[0].content) == {'name': 'Updated'}
