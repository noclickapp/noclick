"""Offline HTTP contract checks; fixtures copy the provider's published examples."""
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError
from nodes import webscraping_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-wsai-token+42"
FIXTURES = Path(__file__).parent / "fixtures" / "webscraping-ai"
EXAMPLES = json.loads((FIXTURES / "responses.json").read_text())
CONFIGS = {
    "ask_question": {"url": "https://example.com", "question": "What is this page about?"},
    "extract_fields": {"url": "https://example.com", "fields_json": '{"title":"Product title","price":"Current price with currency"}'},
    "get_html": {"url": "https://example.com"},
    "get_text": {"url": "https://example.com"},
    "get_selected_html": {"url": "https://example.com", "selector": "h1"},
    "get_multiple_selected_html": {"url": "https://example.com", "selectors": ["h1", "p"]},
    "search": {"q": "coffee machines"}, "list_search_locations": {"q": "Austin"},
    "get_structured_data": {"url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"},
    "get_account": {},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="wsai-test", node_type="automation-webscraping-ai", node_data={
        "config": {"operation": operation, **CONFIGS[operation], **config},
        "credentials": {"credential_type": "webscraping_ai_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(response, Exception): raise response
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_published_responses_and_one_exact_get(monkeypatch, operation):
    body = EXAMPLES[native.ROUTES[operation]]
    response = httpx.Response(200, json=body) if not isinstance(body, str) else httpx.Response(200, text=body)
    requests = transport(monkeypatch, response)
    result = await node(operation).execute({})
    assert result == {"status": "success", "operation": operation, "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "api.webscraping.ai"
    assert request.url.path == native.ROUTES[operation]
    assert request.url.params['api_key'] == TOKEN
    assert not request.content and 'authorization' not in request.headers
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_deep_objects_repeated_arrays_and_false_flags(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json=EXAMPLES['/ai/fields']))
    await node('extract_fields', headers_json='{"Accept-Language":"en + fr"}', js=False, proxy="auto").execute({})
    params = requests[0].url.params
    assert params['fields[title]'] == 'Product title'
    assert params['fields[price]'] == 'Current price with currency'
    assert params['headers[Accept-Language]'] == 'en + fr'
    assert params['js'] == 'false' and params['proxy'] == 'auto'
    assert 'fields_json' not in params and 'headers_json' not in params
    requests = transport(monkeypatch, httpx.Response(200, json=EXAMPLES['/selected-multiple']))
    await node('get_multiple_selected_html').execute({})
    assert requests[0].url.params.get_list('selectors') == ['h1', 'p']


@pytest.mark.asyncio
async def test_formats_script_parameters_and_search_pagination(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={'title':'Example','content':'# Example'}))
    result = await node('get_text', text_format='json', return_links=True).execute({})
    assert result['data']['title'] == 'Example'
    assert requests[0].url.params['return_links'] == 'true'
    requests = transport(monkeypatch, httpx.Response(200, text='Example'))
    await node('get_html', js_script='document.title', return_script_result=True).execute({})
    assert requests[0].url.params['js_script'] == 'document.title'
    requests = transport(monkeypatch, httpx.Response(200, json=EXAMPLES['/serp']))
    result = await node('search', page=2, pages=3).execute({})
    assert requests[0].url.params['page'] == '2' and requests[0].url.params['pages'] == '3'
    assert len(requests) == 1 and result['data']['pagination']['next'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 402, 403, 429, 500, 503, 504])
async def test_errors_redact_key_preserve_provider_message_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, json={'message':f'Quota denied {TOKEN} {quote(TOKEN, safe="")}', 'error_code':'rate_limited', 'retry_after':30}))
    result = await node('get_account').execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'].startswith('Quota denied') and result['retry_after'] == 30
    assert TOKEN not in str(result) and quote(TOKEN, safe='') not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'message':'bad key'}, {'error_code':'bad_key'}])
async def test_account_evidence_refuses_unrecognizable_or_error_envelope(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    assert (await node('get_account').execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_timeout_and_html_errors_hide_request_url(monkeypatch):
    transport(monkeypatch, httpx.ReadTimeout(f'https://api.webscraping.ai/account?api_key={TOKEN}'))
    result = await node('get_account').execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)
    transport(monkeypatch, httpx.Response(403, text=f'<html>{TOKEN}</html>'))
    result = await node('get_account').execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)


@pytest.mark.parametrize('operation,config', [
    ('get_html', {'url':'file:///etc/passwd'}), ('search', {'page':0}),
    ('search', {'pages':6}), ('get_html', {'timeout':25001}),
    ('get_multiple_selected_html', {'selectors':[]}),
    ('extract_fields', {'fields_json':'[]'}), ('extract_fields', {'fields_json':'{"title":42}'}),
    ('get_html', {'headers_json':'{"Bad\\nHeader":"value"}'}),
])
def test_invalid_config_is_rejected(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **config)


def test_evidence_uses_authenticated_account_not_static_locations():
    assert native.WebscrapingAiNode.connection_evidence.identity_operation == 'get_account'
