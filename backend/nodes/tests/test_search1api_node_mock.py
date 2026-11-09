"""Search1API endpoint, credential and response regressions.

Provider documentation examples are preserved in fixtures; the mock transport
never spends account credits or submits actual feedback.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import search1api_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'search1api'
TOKEN = 'synthetic-search1api-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='search1api-test', node_type='automation-search1api',
        node_data={'config': config, 'credentials': {'credential_type': 'search1api_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, code=200, mime='application/json'):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(code, json=body) if mime == 'application/json' else httpx.Response(code, content=body, headers={'content-type': mime})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ('search_web', {'query': 'artificial intelligence', 'page': 2, 'include_sites': ['example.com']}, '/search'),
    ('search_maps', {'query': 'coffee in Manhattan', 'page': 2, 'location': {'latitude': 40.7455, 'longitude': -74.0083, 'zoom': 15}}, '/maps'),
    ('search_news', {'query': 'AI', 'time_range': 'week'}, '/news'),
    ('ask', {'query': 'What are developers saying about Bun 1.3 this month?'}, '/ask'),
    ('crawl_page', {'url': 'https://example.com', 'enableFallback': False}, '/crawl'),
    ('get_sitemap', {'url': 'https://example.com', 'type': 'all'}, '/sitemap'),
    ('get_trending', {'search_service': 'github', 'max_results': 10}, '/trending'),
    ('extract_content', {'url': 'https://example.com', 'prompt': 'Extract titles', 'response_format': {'type': 'object'}}, '/extract'),
    ('start_deepcrawl', {'url': 'https://hono.dev/docs/', 'max_pages': 20, 'include_paths': ['/docs/'], 'format': 'json'}, '/deepcrawl'),
    ('get_usage', {'period': 'month'}, '/usage'),
    ('submit_feedback', {'message': 'Missing documentation', 'agent': {'name': 'NoClick'}}, '/feedback'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,path', CASES)
async def test_every_endpoint_exact_request_and_documented_response(monkeypatch, operation, config, path):
    body = json.loads((FIXTURES / (operation + '.json')).read_text())['body']
    # The docs use fb_... as an illustrative ID; real IDs follow the contract regex.
    if operation == 'submit_feedback':
        body = {'id': 'fb_example123', 'status': 'new'}
    requests = transport(monkeypatch, body, 202 if operation == 'start_deepcrawl' else 201 if operation == 'submit_feedback' else 200)
    result = await node({'operation': operation, **config}).execute({})
    assert result == {'status': 'success', 'operation': operation, 'data': body}
    assert len(requests) == 1
    req = requests[0]
    assert req.url.host == 'api.search1api.com' and req.url.path == path
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(req.url) and TOKEN not in str(result)
    if operation == 'get_usage':
        assert req.method == 'GET' and dict(req.url.params) == {'period': 'month'} and not req.content
    else:
        assert req.method == 'POST'
        payload = json.loads(req.content)
        assert 'operation' not in payload
        for key, value in config.items():
            assert payload[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['queued', 'waiting', 'processing', 'completed', 'failed', 'not_found'])
async def test_deepcrawl_status_separate_from_execution_status(monkeypatch, status):
    data = {'taskId': 'task-123', 'status': status}
    if status == 'completed':
        data.update(format='json', pages=[{'url': 'https://example.com', 'title': None, 'content': 'Hello'}])
    requests = transport(monkeypatch, data)
    result = await node({'operation': 'get_deepcrawl_status', 'taskId': 'task-123'}).execute({})
    assert result['status'] == 'success' and result['data'] == data
    assert requests[0].method == 'GET' and requests[0].url.path == '/deepcrawl/status/task-123'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401, 402, 422, 429, 500, 302])
async def test_provider_rejection_preserved_and_no_retry(monkeypatch, code):
    requests = transport(monkeypatch, {'ok': False, 'message': 'Provider rejected the request'}, code)
    result = await node({'operation': 'get_usage'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert result['error'] == 'Provider rejected the request' and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'usage': '12', 'credential_type': 'api_key'}, {'usage': -1, 'credential_type': 'api_key'}, {'usage': 1, 'credential_type': 'other'}])
async def test_connection_evidence_refuses_incomplete_usage(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'get_usage'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_html_and_success_error_envelope_rejected(monkeypatch):
    transport(monkeypatch, b'<html>Login</html>', mime='text/html')
    assert (await node({'operation': 'get_usage'}).execute({}))['status'] == 'error'
    transport(monkeypatch, {'success': False, 'extractParameters': {}, 'results': None})
    assert (await node({'operation': 'extract_content', 'url': 'https://example.com'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'search_maps', 'query': 'coffee', 'page': 2},
    {'operation': 'search_web', 'query': 'AI', 'max_results': 51},
    {'operation': 'start_deepcrawl', 'url': 'https://example.com', 'max_pages': 1001},
    {'operation': 'start_deepcrawl', 'url': 'https://example.com', 'include_paths': ['']},
    {'operation': 'crawl_page', 'url': 'file:///etc/passwd'},
    {'operation': 'get_deepcrawl_status', 'taskId': '..'},
])
def test_invalid_input_rejected_before_network(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_manual_credential_default_tag():
    key = native.Search1ApiKeyCredential(api_key='  '+TOKEN+'  ')
    assert key.credential_type == 'search1api_api_key' and key.api_key == TOKEN
    assert TOKEN not in repr(key)


@pytest.mark.asyncio
async def test_documented_deepcrawl_job_error_is_read_as_job_data(monkeypatch):
    body = json.loads((FIXTURES / 'get_deepcrawl_status.json').read_text())['body']
    transport(monkeypatch, body)
    result = await node({'operation': 'get_deepcrawl_status', 'taskId': 'string'}).execute({})
    assert result['status'] == 'success' and result['data'] == body
