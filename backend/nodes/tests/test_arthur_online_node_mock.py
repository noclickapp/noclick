"""Replay Arthur Online's own saved Postman responses through every action.

Poll tests preserve those payloads and verify baseline, deduplication and scope
changes. Separate negative cases exercise validation and failed-request behavior.
"""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
import nodes.arthur_online_node as mod
from nodes.oauth.arthur_online_oauth import OAUTH_PROVIDER
from nodes.core.poll_trigger import poll_scope

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/arthur-online/postman_examples.json').read_text())
CASES = FIXTURE['operations']
CREDENTIAL = {'credential_type': 'arthur_online_oauth', 'access_token': 'test-arthur-secret', 'entity_id': '123'}


def node(config, credential=None):
    parsed = mod.ArthurOnlineNode.parse_config({'config': config, 'credentials': credential or CREDENTIAL})
    return mod.ArthurOnlineNode('test', 'automation-arthur-online', {}, config=parsed)


def mock_http(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs.get('follow_redirects') is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session
    monkeypatch.setattr(mod, 'guarded_async_client', client)
    monkeypatch.setattr(mod, 'ensure_fresh_oauth_token', AsyncMock(return_value=CREDENTIAL['access_token']))
    return client


@pytest.mark.parametrize('operation', CASES)
@pytest.mark.asyncio
async def test_arthur_online_saved_example(monkeypatch, operation):
    case = CASES[operation]
    example = case['item']['response'][0]
    payload = json.loads(example['body'])
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.host == 'api.arthuronline.co.uk'
        assert request.headers['Authorization'] == 'Bearer test-arthur-secret'
        assert request.headers['X-EntityID'] == '123'
        assert request.method == case['item']['request']['method']
        expected = case['item']['request']['url']
        for field, value in case['config'].items():
            expected = expected.replace('{{' + field + '}}', str(value))
        assert str(request.url) == expected
        spec = mod.OPERATIONS[operation]
        if spec['body']:
            assert request.headers['Content-Type'] == 'application/json'
            assert json.loads(request.content) == {k: v for k, v in case['config'].items() if k in spec['body']}
        return httpx.Response(example.get('code', 200), json=payload)
    mock_http(monkeypatch, handle)
    result = await node(case['config']).execute({})
    assert result == {'operation': operation, **payload}
    assert len(calls) == 1


@pytest.mark.parametrize('trigger,base', [('on_new_property', 'list_properties'), ('on_new_certificate', 'list_certificates')])
@pytest.mark.asyncio
async def test_arthur_online_poll_saved_payload_baseline_dedup_and_scope(monkeypatch, trigger, base):
    payload = json.loads(CASES[base]['item']['response'][0]['body'])
    calls = []
    def handle(request):
        calls.append(request)
        assert not request.url.params
        return httpx.Response(200, json=payload)
    mock_http(monkeypatch, handle)
    n = node({'operation': trigger})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(copy.deepcopy(state))
        if changed is not None:
            state = changed
        return result
    n._update_node_state = update
    first = await n.execute({})
    assert first['records'] == []  # Existing provider records establish the baseline.
    assert n.trigger_produced_no_event(first)
    # Replaying the provider's exact example against an armed empty baseline
    # proves a new record can fire without inventing a provider payload.
    state['seen_ids'] = []
    second = await n.execute({})
    assert second['records'] == payload['data']
    assert n.trigger_emitted_event(second)
    event = mod.ArthurOnlineNode.resolve_agent_event(second)
    assert 'Arthur Online' in event['text']
    for row in payload['data']:
        assert str(row['id']) in event['text']
    assert mod.ArthurOnlineNode.should_propagate_output(second, {'operation': trigger})
    assert not (await n.execute({}))['records']
    state['scope'] = 'a-different-watch'
    assert not (await n.execute({}))['records']
    assert len(calls) == 4
    assert poll_scope(mod.ArthurOnlineNode, {'operation': 'on_new_property'}) != poll_scope(mod.ArthurOnlineNode, {'operation': 'on_new_certificate'})
    assert poll_scope(mod.ArthurOnlineNode, {'operation': trigger}) == poll_scope(mod.ArthurOnlineNode, {'operation': trigger, 'label': 'Cosmetic label'})


@pytest.mark.asyncio
async def test_arthur_online_poll_pagination_is_complete_before_state_changes(monkeypatch):
    payload = json.loads(CASES['list_properties']['item']['response'][0]['body'])
    calls = []
    def handle(request):
        calls.append(int(request.url.params.get('page', '1')))
        response = copy.deepcopy(payload)
        response['pagination']['pageCount'] = 2
        response['pagination']['page'] = calls[-1]
        if calls[-1] == 2:
            response['data'] = []
        return httpx.Response(200, json=response)
    mock_http(monkeypatch, handle)
    n = node({'operation': 'on_new_property'})
    n._filter_unseen = AsyncMock(return_value=payload['data'])
    await n.execute({})
    assert calls == [1, 2]
    n._filter_unseen.assert_awaited_once_with(payload['data'], n._filter_unseen.call_args.args[1])


@pytest.mark.asyncio
async def test_arthur_online_poll_incomplete_page_does_not_advance(monkeypatch):
    payload = json.loads(CASES['list_properties']['item']['response'][0]['body'])
    del payload['pagination']
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    n = node({'operation': 'on_new_property'})
    n._filter_unseen = AsyncMock()
    with pytest.raises(ValueError, match='pagination'):
        await n.execute({})
    n._filter_unseen.assert_not_awaited()


@pytest.mark.parametrize('status', [401, 403, 429, 500])
@pytest.mark.asyncio
async def test_arthur_online_write_errors_are_redacted_and_not_retried(monkeypatch, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': 'Rejected test-arthur-secret'})
    mock_http(monkeypatch, handle)
    with pytest.raises(ValueError, match='Rejected') as exc:
        await node(CASES['create_property']['config']).execute({})
    assert 'test-arthur-secret' not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'get_property', 'property_id': '../other'},
    {'operation': 'list_properties', 'limit': 101},
    {'operation': 'get_note', 'note_id': 0},
    {'operation': 'update_certificate', 'certificate_id': 123, 'type': 'Boiler Service', 'expiry_date': '2026-02-30'},
    {'operation': 'create_property', 'ref': 'A', 'address_line_1': 'A'},
    {'operation': 'create_unit', 'unit_ref': 'A'},
    {'operation': 'create_entity', 'first_name': 'A'},
])
def test_arthur_online_config_validation(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
async def test_arthur_online_oauth_entity_identity_and_token_wire(monkeypatch):
    # Copy the selected entity's saved response from the pinned collection.
    fixture = json.loads((Path(__file__).parent / 'fixtures/arthur-online/oauth_examples.json').read_text())
    identity = fixture['identity']
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://api.arthuronline.co.uk/v2/entities/123'
        assert request.headers['X-EntityID'] == '123'
        assert request.headers['Authorization'] == 'Bearer test-arthur-secret'
        return httpx.Response(200, json=json.loads(identity['response'][0]['body']))
    client = mock_http(monkeypatch, handle)
    monkeypatch.setattr(type(OAUTH_PROVIDER), '_client', lambda self, url: client(follow_redirects=False))
    name = await OAUTH_PROVIDER.account_name(CREDENTIAL['access_token'], context={'entity_id': '123'})
    assert name == 'Company'
    monkeypatch.setenv('ARTHUR_ONLINE_CLIENT_ID', 'test-client')
    monkeypatch.setenv('ARTHUR_ONLINE_CLIENT_SECRET', 'test-client-secret')
    for grant in [{'grant_type': 'authorization_code', 'code': 'test-code', 'redirect_uri': 'https://noclick.example/callback'}, {'grant_type': 'refresh_token', 'refresh_token': 'test-refresh'}]:
        request = OAUTH_PROVIDER.token_request(grant, context={'entity_id': '123'})
        assert request['url'] == 'https://auth.arthuronline.co.uk/oauth/token'
        assert request['auth'] is None
        assert request['data'] == {**grant, 'client_id': 'test-client', 'client_secret': 'test-client-secret'}
        assert request['headers']['Cache-Control'] == 'no-cache'
    assert not OAUTH_PROVIDER.pkce
    assert list(mod.ARTHUR_ONLINE_SCOPES.declared_scopes()) == []
    assert mod.ArthurOnlineOAuthCredential(access_token='key', entity_id='123').credential_type == 'arthur_online_oauth'
    assert mod.ArthurOnlineNode.connection_evidence.operation == 'list_properties'
    assert len(calls) == 1
