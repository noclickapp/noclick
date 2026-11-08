"""Offline Smokeball transport, OAuth identity and asynchronous write contracts."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import smokeball_node as sb
from nodes.oauth import smokeball_oauth as oauth
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/smokeball/operations.json').read_text())

@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config, **changes):
    credentials = dict(credential_type='smokeball_oauth', access_token='access-test-secret',
                       refresh_token='refresh-test-secret', api_key='application-test-key',
                       expires_at='2099-01-01T00:00:00Z')
    credentials.update(changes)
    return NodeFactory.create_node(node_id='smokeball-test', node_type='automation-smokeball',
                                   node_data={'config': config, 'credentials': credentials})


def transport(monkeypatch, responder):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as c:
            yield c
    monkeypatch.setattr(sb, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_smokeball_transport(monkeypatch, operation):
    case = CASES[operation]
    requests = []
    def answer(request):
        requests.append(request)
        assert request.method == case['method']
        assert request.url.path == case['path']
        assert request.url.host == 'api.smokeball.com'
        assert request.headers['authorization'] == 'Bearer access-test-secret'
        assert request.headers['x-api-key'] == 'application-test-key'
        assert 'secret' not in str(request.url) + request.content.decode()
        if operation.startswith('list_'):
            return httpx.Response(200, json={'value': [{'id': 'record'}], 'offset': 500,
                    'limit': 2, 'size': 501, 'next': None})
        if case['method'] != 'GET':
            assert request.headers['content-type'] == 'application/json'
            return httpx.Response(202, json={'id': 'record', 'href': '/pending/record', 'method': 'GET'})
        return httpx.Response(200, json={'id': 'record', 'name': 'Brown LLC'})
    transport(monkeypatch, answer)
    output = await node(case['config']).execute({})
    assert output['status'] == 'success'
    assert len(requests) == 1  # never follow write links, retry writes or fetch extra pages
    request = requests[0]
    if case['method'] != 'GET':
        assert output['accepted'] is True and output['completed'] is False
        body = json.loads(request.content)
        if operation.endswith('contact'):
            assert body == {'person': case['config']['person'], 'externalSystemId': 'EXT01'}
        if operation.endswith('matter'):
            assert body['clientIds'] == ['832e778f-83df-454a-b344-768a862a7e67']
            assert body['matterTypeId'] == '009f778f-83df-454a-b344-768a862a7e55'
            assert 'matter_id' not in body
        if operation.endswith('task'):
            assert body['staffId'] == '750eb5c5-ac0b-7d11-4997-e0ce9d8896c8'
            assert body['isCompleted'] is True and body['dueDateOnly'] == '2020-02-15T13:00:00Z'
        if operation == 'create_event':
            assert body['type'] == 'Normal' and body['timeZone'] == 'Australia/Sydney'
        if operation == 'create_memo':
            assert body == {'title': 'Update', 'text': 'There has been a recent update on this matter.'}
    elif operation.startswith('list_'):
        assert request.url.params['Offset'] == str(case['config'].get('offset', 0))
        assert request.url.params['Limit'] == str(case['config'].get('limit', 100))
        assert output['next_offset'] is None


@pytest.mark.asyncio
async def test_smokeball_filters_and_continuation(monkeypatch):
    requests = []
    def answer(request):
        requests.append(request)
        return httpx.Response(200, json={'value': [{'id': 'a'}, {'id': 'b'}], 'size': 10,
            'offset': 4, 'limit': 2, 'next': {'href': 'https://evil.example/steal'}})
    transport(monkeypatch, answer)
    output = await node({'operation': 'list_tasks', 'offset': 4, 'limit': 2, 'is_completed': False,
                         'matter_id': '1bf55840-cba3-4f8a-8c0f-66082692e493'}).execute({})
    assert output['next_offset'] == 6 and len(requests) == 1
    assert requests[0].url.params['IsCompleted'] == 'false'
    assert requests[0].url.params['MatterId'] == '1bf55840-cba3-4f8a-8c0f-66082692e493'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_smokeball_error_redacts_and_never_retries(monkeypatch, status):
    calls = []
    def answer(request):
        calls.append(request)
        return httpx.Response(status, text='Provider says access-test-secret refresh-test-secret application-test-key')
    transport(monkeypatch, answer)
    output = await node({'operation': 'get_firm'}).execute({})
    assert output['status'] == 'error' and output['http_status'] == status
    assert output['error'] == 'Provider says [redacted] [redacted] [redacted]'
    assert len(calls) == 1


@pytest.mark.parametrize('identifier', ['../firm', 'https://evil.example', '1', 'a/b', '..', '%2e'])
def test_smokeball_rejects_invalid_resource_ids(identifier):
    with pytest.raises(ValueError):
        node({'operation': 'get_contact', 'contact_id': identifier})


@pytest.mark.asyncio
async def test_smokeball_app_key_fallback(monkeypatch):
    monkeypatch.setenv('SMOKEBALL_API_KEY', 'configured-application-key')
    def answer(request):
        assert request.headers['x-api-key'] == 'configured-application-key'
        return httpx.Response(200, json={'name': 'Brown LLC'})
    transport(monkeypatch, answer)
    await node({'operation': 'get_firm'}, api_key=None).execute({})


@pytest.mark.asyncio
async def test_smokeball_oauth_pkce_identity_and_refresh(monkeypatch):
    for key, value in dict(SMOKEBALL_CLIENT_ID='client', SMOKEBALL_CLIENT_SECRET='secret',
          SMOKEBALL_API_KEY='application-key', SMOKEBALL_REDIRECT_URI='https://app.example/callback').items():
        monkeypatch.setenv(key, value)
    requests = []
    def answer(request):
        requests.append(request)
        if request.url.path == '/firm':
            assert request.headers['x-api-key'] == 'application-key'
            assert request.headers['Authorization'] == 'Bearer new-access'
            return httpx.Response(200, json={'name': 'Brown LLC'})
        assert request.url == 'https://auth.smokeball.com/oauth2/token'
        assert request.headers['Authorization'] == 'Basic Y2xpZW50OnNlY3JldA=='
        return httpx.Response(200, json={'access_token': 'new-access', 'refresh_token': 'new-refresh',
            'expires_in': 3600, 'token_type': 'Bearer', 'scope': ' '.join(sb.SMOKEBALL_SCOPES.declared_scopes())})
    @asynccontextmanager
    async def client(self, url):
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as c:
            yield c
    monkeypatch.setattr(oauth.SmokeballOAuthProviderSpec, '_client', client)
    provider = oauth.OAUTH_PROVIDER
    tokens, name = await provider.exchange('code', 'https://app.example/callback', 'a' * 43)
    assert name == 'Brown LLC' and tokens.access_token == 'new-access'
    assert parse_qs(requests[0].content.decode())['code_verifier'] == ['a' * 43]
    assert provider.public_metadata()['provider'] == 'smokeball'
    await provider.refresh('old-refresh')
    assert parse_qs(requests[-1].content.decode())['grant_type'] == ['refresh_token']


@pytest.mark.asyncio
async def test_smokeball_refresh_uses_shared_choke_point(monkeypatch):
    import nodes.core.oauth_refresh as shared
    fresh = AsyncMock(return_value='fresh')
    monkeypatch.setattr(shared, 'ensure_fresh_oauth_token', fresh)
    n = node({'operation': 'get_firm'})
    assert await n._access_token(n.config.credentials) == 'fresh'
    assert fresh.call_args.kwargs['provider'] == 'smokeball'
    freshen = AsyncMock(return_value={'access_token': 'new'})
    monkeypatch.setattr(shared, 'freshen_oauth_credential', freshen)
    await sb.SmokeballNode.freshen_credential({'refresh_token': 'old'}, credential_id='saved')
    assert freshen.call_args.kwargs['credential_id'] == 'saved'


@pytest.mark.asyncio
async def test_smokeball_connection_names_the_firm(monkeypatch):
    import nodes.core.run_op as runner
    from nodes.core.connection_evidence import collect_evidence
    def answer(request):
        assert request.method == 'GET' and request.url.path == '/firm'
        return httpx.Response(200, json={'id': 'firm-id', 'name': 'Brown LLC'})
    transport(monkeypatch, answer)
    async def run(**kwargs):
        return await node({'operation': kwargs['operation']}).execute({})
    execute = AsyncMock(side_effect=run)
    monkeypatch.setattr(runner, 'run_node_operation', execute)
    result = await collect_evidence(node_type='automation-smokeball', user_id='test', pool=None,
                                     credential_data=node({'operation': 'get_firm'}).config.credentials.model_dump())
    assert result.reachable is True and result.account_label == 'Brown LLC'
    execute.assert_awaited_once()
