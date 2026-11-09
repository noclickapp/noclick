"""Exercise Serply through its registry factory with offline HTTP transport.
Published examples pin ten routes, path queries, JSON output and errors.
"""
import json
from pathlib import Path
from urllib.parse import unquote
import httpx
import pytest
from pydantic import ValidationError
from nodes import serply_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/serply/published.json').read_text())['operations']
TOKEN = 'serply-synthetic-key-42'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='serply-test', node_type='automation-serply',
        node_data={'config': config, 'credentials': {'credential_type': 'serply_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CASES))
async def test_published_route_query_and_response(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case['response'])
    assert await node({'operation': operation, 'query': case['query']}).execute({}) == {'status': 'success', 'data': case['response']}
    request, = requests
    assert request.method == 'GET' and request.url.host == 'api.serply.io'
    assert request.url.path == unquote(case['path'] + case['query'])
    assert request.url.query == b'' and request.content == b''
    assert request.headers['X-Api-Key'] == TOKEN and 'Authorization' not in request.headers

@pytest.mark.asyncio
async def test_headers_and_delimiters_stay_in_path(monkeypatch):
    requests = transport(monkeypatch, {'results': []})
    query = 'q=café+tools&website=https%3A%2F%2Fexample.com/a?b=1#frag'
    result = await node({'operation': 'search_google', 'query': query, 'device': 'mobile', 'proxy_location': 'GB'}).execute({})
    assert result['status'] == 'success'
    request, = requests
    assert request.url.query == b'' and request.url.fragment == ''
    assert request.headers['X-User-Agent'] == 'mobile' and request.headers['X-Proxy-Location'] == 'GB'
    assert b'%3F' in request.url.raw_path and b'%23' in request.url.raw_path

@pytest.mark.asyncio
async def test_jobs_do_not_send_undocumented_headers(monkeypatch):
    requests = transport(monkeypatch, {'jobs': []})
    await node({'operation': 'search_jobs', 'query': 'q=nurse+practitioner'}).execute({})
    assert 'X-User-Agent' not in requests[0].headers and 'X-Proxy-Location' not in requests[0].headers
    with pytest.raises(ValidationError):
        native.SerplySearchJobsConfig(query='q=nurse', device='mobile')

@pytest.mark.asyncio
async def test_default_probe_is_documented_and_reachability_only(monkeypatch):
    requests = transport(monkeypatch, {'results': []})
    assert (await node({'operation': 'search_google'}).execute({}))['status'] == 'success'
    assert requests[0].url.path == '/v1/search/q=search+api'
    assert native.SerplyNode.connection_evidence.proves == 'reachability'

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [201, 204, 301, 302, 401, 403, 404, 422, 429, 500])
async def test_http_errors_and_redirects_never_succeed_or_expose_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={'error': {'message': 'Rejected ' + TOKEN}}, headers={'Location': 'https://example.test'}))
    result = await node({'operation': 'search_google'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'error': 'invalid key'}, {'errors': ['denied']}, {'detail': 'bad request'}, [], {}, {'message': 'not authenticated'}])
async def test_error_envelopes_and_invalid_shapes(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation': 'search_google'}).execute({}))['status'] == 'error'

@pytest.mark.asyncio
async def test_non_json_and_transport_failures(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text='<html>not JSON</html>'))
    assert (await node({'operation': 'search_google'}).execute({}))['status'] == 'error'
    def fail(request):
        raise httpx.ReadTimeout('private ' + TOKEN)
    transport(monkeypatch, fail)
    result = await node({'operation': 'search_google'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)

def test_manual_credential_defaults_and_validation():
    assert native.SerplyApiKeyCredential(api_key=TOKEN).credential_type == 'serply_api_key'
    for key in ['', 'https://example.test/key', 'header with spaces', 'key\r\ninjected']:
        with pytest.raises((ValidationError, ValueError)):
            native.SerplyApiKeyCredential(api_key=key)
    assert len(native.ROUTES) == 10
    with pytest.raises(ValidationError):
        native.SerplySearchBingConfig(query='q=x', proxy_location='invalid')
    with pytest.raises(ValidationError):
        native.SerplySearchNewsConfig(query='q=x\n')
