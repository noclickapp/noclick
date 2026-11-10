"""Requests and documented payload regressions; no live provider credentials."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import webscraper_io_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/webscraper-io/requests.json').read_text())
TOKEN = 'synthetic-webscraper-test-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='test', node_type='automation-webscraper-io',
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_token': TOKEN}})

def mock(monkeypatch, body=None, status=200, content=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if content is None else httpx.Response(status, content=content)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_every_operation_auth_method_route_query_and_body(monkeypatch, operation):
    config = CASES[operation]['config']
    expected = CASES[operation]['expected_request']
    data = [] if operation in {'list_sitemaps', 'list_scraping_jobs', 'list_tags', 'list_problematic_urls'} else {'id': 123}
    requests = mock(monkeypatch, {'success': True, 'data': data}, content=b'{"title":"Phone one","price":199}\n' if operation == 'download_data' else None)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'api.webscraper.io'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.method == expected['method']
    assert request.url.path == expected['path']
    assert dict(request.url.params) == expected['query']
    if expected['body'] is not None:
        assert json.loads(request.content) == expected['body']
    else:
        assert request.content == b''
    assert TOKEN not in str(result)

@pytest.mark.asyncio
async def test_optional_fields_are_omitted_and_false_is_preserved(monkeypatch):
    requests = mock(monkeypatch, {'success': True, 'data': []})
    await node({'operation': 'continue_scraping_job', 'scrapingJobId': 123, 'render_js': False}).execute({})
    assert json.loads(requests[0].content) == {'render_js': False}
    await node({'operation': 'list_sitemaps'}).execute({})
    assert not requests[1].url.query

@pytest.mark.asyncio
async def test_pagination_metadata_is_preserved(monkeypatch):
    response = {'success': True, 'data': [{'id': 123, 'name': 'webscraper-io-landing'}],
        'current_page': 1, 'last_page': 10, 'total': 1000, 'per_page': 100}
    mock(monkeypatch, response)
    result = await node({'operation': 'list_sitemaps', 'page': 1}).execute({})
    assert all(result[k] == v for k, v in response.items())

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 422, 429, 500])
async def test_errors_are_not_success_or_retried_and_token_is_redacted(monkeypatch, status):
    requests = mock(monkeypatch, {'success': False, 'error': 'rejected ' + TOKEN}, status)
    result = await node({'operation': 'get_account'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1

@pytest.mark.asyncio
async def test_provider_error_envelope_and_malformed_shape(monkeypatch):
    mock(monkeypatch, {'success': False, 'error': 'invalid token'})
    assert (await node({'operation': 'get_account'}).execute({})) == {'status': 'error', 'error': 'invalid token'}
    mock(monkeypatch, {'data': []})
    assert (await node({'operation': 'list_sitemaps'}).execute({}))['status'] == 'error'

@pytest.mark.asyncio
@pytest.mark.parametrize('extension,content,expected', [
    ('json', b'{"title":"Phone one","price":199}\n', '{"title":"Phone one","price":199}\n'),
    ('csv', b'title,price\n"Phone one","199"\n', 'title,price\n"Phone one","199"\n'),
    ('xlsx', b'PK\x03\x04', 'UEsDBA=='),
])
async def test_export_preserves_jsonl_csv_and_binary(monkeypatch, extension, content, expected):
    mock(monkeypatch, content=content)
    result = await node({'operation': 'download_data', 'scrapingJobId': 123, 'extension': extension}).execute({})
    assert result['content'] == expected
    assert result['encoding'] == ('base64' if extension == 'xlsx' else 'utf-8')

def test_credentials_default_supports_manual_connection():
    credential = native.WebscraperIoCredential(api_token=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert native.WebscraperIoCredential.model_fields['credential_type'].is_required() is False

@pytest.mark.parametrize('config', [
    {'operation': 'get_scraping_job', 'scrapingJobId': '../account'},
    {'operation': 'get_scraping_job', 'scrapingJobId': True},
    {'operation': 'get_scraping_job', 'scrapingJobId': 0},
    {'operation': 'download_data', 'scrapingJobId': 123, 'extension': '../account'},
    {'operation': 'create_scraping_job', 'sitemap_id': 123},
    {'operation': 'list_sitemaps', 'page': 0},
    {'operation': 'list_sitemaps', 'order_by': 'created'},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises(ValidationError):
        native.WebscraperIoConfig(config=config)
