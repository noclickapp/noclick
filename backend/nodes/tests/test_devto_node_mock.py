"""Offline request contracts for DEV's Forem API v1."""
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import devto_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-devto-api-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {'credential_type': 'devto_api_key', 'api_key': TOKEN}


def node(config):
    return NodeFactory.create_node(node_id='devto-fixture', node_type='automation-devto',
        node_data={'config': config, 'credentials': credential()})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs == {'timeout': 30, 'trust_env': False, 'follow_redirects': False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ({'operation': 'get_me'}, 'GET', '/api/users/me', {}, {'id': 1, 'username': 'ben'}),
    ({'operation': 'list_articles', 'tag': 'discuss', 'top': 2, 'page': 2}, 'GET', '/api/articles', {'page': '2', 'per_page': '30', 'tag': 'discuss', 'top': '2'}, []),
    ({'operation': 'list_latest_articles'}, 'GET', '/api/articles/latest', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'get_article', 'article_id': 123}, 'GET', '/api/articles/123', {}, {'id': 123}),
    ({'operation': 'get_article_by_path', 'username': 'ben', 'slug': 'my-first-post-1234'}, 'GET', '/api/articles/ben/my-first-post-1234', {}, {'id': 123}),
    ({'operation': 'list_my_articles'}, 'GET', '/api/articles/me', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'list_my_published_articles'}, 'GET', '/api/articles/me/published', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'list_my_unpublished_articles'}, 'GET', '/api/articles/me/unpublished', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'list_all_my_articles'}, 'GET', '/api/articles/me/all', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'create_article', 'title': 'Hello, World!', 'body_markdown': 'Hello DEV', 'tags': 'discuss,python'}, 'POST', '/api/articles', {}, {'id': 123, 'published': False}),
    ({'operation': 'update_article', 'article_id': 123, 'published': True}, 'PUT', '/api/articles/123', {}, {'id': 123, 'published': True}),
    ({'operation': 'list_comments', 'a_id': '321'}, 'GET', '/api/comments', {'page': '1', 'per_page': '30', 'a_id': '321'}, []),
    ({'operation': 'get_comment', 'comment_id': '2g7'}, 'GET', '/api/comments/2g7', {}, {'id_code': '2g7', 'children': []}),
    ({'operation': 'list_tags'}, 'GET', '/api/tags', {'page': '1', 'per_page': '10'}, []),
    ({'operation': 'list_followed_tags'}, 'GET', '/api/follows/tags', {}, []),
    ({'operation': 'list_followers', 'sort': '-created_at'}, 'GET', '/api/followers/users', {'page': '1', 'per_page': '30', 'sort': '-created_at'}, []),
    ({'operation': 'get_reading_list'}, 'GET', '/api/readinglist', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'get_organization', 'organization_id': 1}, 'GET', '/api/organizations/1', {}, {'id': 1, 'username': 'github'}),
    ({'operation': 'list_organization_articles', 'organization_id_or_username': 'github'}, 'GET', '/api/organizations/github/articles', {'page': '1', 'per_page': '30'}, []),
    ({'operation': 'get_user', 'user_id': 'ben'}, 'GET', '/api/users/ben', {}, {'id': 1, 'username': 'ben'}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,query,response', CASES)
async def test_each_operation_is_one_published_request(monkeypatch, config, method, path, query, response):
    requests = transport(monkeypatch, response, 201 if method == 'POST' else 200)
    output = await node(config).execute({})
    assert output['status'] == 'success' and output['data'] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path and request.url.host == 'dev.to'
    assert dict(request.url.params) == query
    assert request.headers['api-key'] == TOKEN
    assert request.headers['accept'] == 'application/vnd.forem.api-v1+json'
    if method == 'POST':
        assert json.loads(request.content) == {'article': {'title': 'Hello, World!', 'body_markdown': 'Hello DEV', 'published': False, 'tags': 'discuss,python'}}
    elif method == 'PUT':
        assert json.loads(request.content) == {'article': {'published': True}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,valid', [(401, False), (403, False), (429, None), (500, None)])
async def test_connect_auth_refusals_redact_secrets(monkeypatch, status, valid):
    requests = transport(monkeypatch, {'error': 'Rejected ' + TOKEN}, status)
    result = await native.DevtoNode.validate_credential_access(credential())
    assert result['valid'] is valid and TOKEN not in str(result)
    assert len(requests) == 1 and requests[0].url.path == '/api/users/me'


@pytest.mark.asyncio
async def test_account_identity_and_empty_account_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    transport(monkeypatch, {'id': 1, 'username': 'ben', 'name': 'Ben'})
    assert (await native.DevtoNode.validate_credential_access(credential()))['identity_verified'] is True
    async def run_operation(**kwargs):
        return await node({'operation': kwargs['operation'], **kwargs['arguments']}).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run_operation)
    def client(**kwargs):
        def respond(request):
            body = {'id': 1, 'username': 'ben', 'name': 'Ben'} if request.url.path.endswith('/users/me') else []
            return httpx.Response(200, json=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await collect_evidence(node_type='automation-devto', user_id='fixture', credential_data=credential())
    assert result.reachable is True and result.account_label == 'Ben'


@pytest.mark.asyncio
async def test_empty_write_acknowledgement_and_error_body(monkeypatch):
    requests = transport(monkeypatch, None, 201)
    result = await node({'operation': 'create_article', 'title': 'Hello', 'body_markdown': 'Hi'}).execute({})
    assert result['data'] is None and result['http_status'] == 201 and len(requests) == 1
    requests = transport(monkeypatch, {'error': TOKEN})
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'update_article', 'article_id': 123, 'title': 'Hi'}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1
    transport(monkeypatch, {'unexpected': 'not a list'})
    with pytest.raises(ValueError):
        await node({'operation': 'list_my_articles'}).execute({})


@pytest.mark.asyncio
async def test_network_failure_does_not_retry_a_write(monkeypatch):
    requests = []
    def client(**kwargs):
        def respond(request):
            requests.append(request)
            raise httpx.ReadTimeout('timeout ' + TOKEN, request=request)
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'create_article', 'title': 'Hello', 'body_markdown': 'Hi'}).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize('value', ['api-key: abc', 'a\nb', 'https://dev.to/settings/extensions', '<token>'])
def test_paste_errors(value):
    with pytest.raises(ValueError):
        native.DevtoAPIKeyCredential(api_key=value)


@pytest.mark.parametrize('config', [
    {'operation': 'get_article', 'article_id': -1},
    {'operation': 'get_article_by_path', 'username': '../users', 'slug': 'a'},
    {'operation': 'get_user', 'user_id': 'https://elsewhere.invalid'},
    {'operation': 'update_article', 'article_id': 123},
    {'operation': 'list_articles', 'per_page': 1001},
])
def test_invalid_inputs_cannot_change_route_or_write_empty_patch(config):
    with pytest.raises(ValueError):
        node(config)


def test_schema_factory_and_manual_connect_defaults():
    assert len(native.ROUTES) == len(CASES) == 20
    assert native.DevtoAPIKeyCredential(api_key=TOKEN).credential_type == 'devto_api_key'
    parsed = native.DevtoNode.parse_config({'config': {'operation': 'list_articles', 'page': ''}, 'credentials': credential()})
    assert parsed.config.page == 1
    with pytest.raises(ValidationError):
        native.DevtoAPIKeyCredential(credential_type='other', api_key=TOKEN)
