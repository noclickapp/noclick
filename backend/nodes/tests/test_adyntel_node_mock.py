"""Adyntel wire regressions using the provider's pinned response examples."""
from contextlib import asynccontextmanager
import json
from pathlib import Path

import httpx
import pytest
from nodes import adyntel_node as module
from nodes.core.registry import NodeFactory

KEY = 'adyntel-fixture-secret-8241'
CREDENTIAL = {'credential_type': 'adyntel_api_key', 'email': 'owner@example.com', 'api_key': KEY}
EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/adyntel/responses.json').read_text())
JOBS = json.loads((Path(__file__).parent / 'fixtures/adyntel/documented_jobs.json').read_text())
# Independent of the implementation route table, so a wiring error fails.
CASES = {
    'search_facebook_ads': ('/facebook', {'company_domain': 'zoom.com', 'country_code': 'US', 'media_type': 'video', 'active_status': 'all', 'continuation_token': 'next-facebook'}),
    'search_google_ads': ('/google', {'company_domain': 'tesla.com', 'media_type': 'text', 'extract_text': False, 'continuation_token': 'next-google', 'data_provider': 'apify'}),
    'search_linkedin_ads': ('/linkedin', {'company_domain': 'tesla.com', 'live_ads': True, 'extract': 'number_of_ads', 'continuation_token': '0#24'}),
    'search_linkedin_keywords': ('/linkedin-keyword-search', {'keyword': 'webinar', 'country': 'US', 'dateOption': 'custom-date-range', 'startDate': '2026-01-01', 'endDate': '2026-01-31', 'continuation_token': '0#24'}),
    'search_meta_keywords': ('/facebook_ad_search', {'keyword': 'shopify', 'country_code': 'US', 'all_ads': False, 'continuation_token': 'next-meta'}),
    'create_google_shopping_search': ('/google_shopping', {'company_domain': 'tesla.com', 'shopping': False}),
    'get_google_shopping_status': ('/google_shopping_status', {'id': '04092348-9321-0066-0000-c99a6273cf86'}),
    'search_tiktok_ads': ('/tiktok_search', {'keyword': 'toys', 'country_code': 'DE'}),
    'get_tiktok_ad_details': ('/tiktok_ad_details', {'id': '1861945277706417'}),
    'get_domain_keywords': ('/domain-keywords', {'company_domain': 'lokalise.com', 'language': 'English', 'limit': 1}),
}


def node(operation, config=None):
    return NodeFactory.create_node(node_id='adyntel-test', node_type='automation-adyntel',
        node_data={'config': {'operation': operation, **(config or {})}, 'credentials': CREDENTIAL})


def transport(monkeypatch, handler):
    calls = []
    def handle(request):
        calls.append(request)
        return handler(request)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance:
            yield instance
    monkeypatch.setattr(module, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_documented_response_and_exact_wire(monkeypatch, operation):
    path, config = CASES[operation]
    def handler(request):
        assert request.method == 'POST'
        assert str(request.url) == 'https://api.adyntel.com' + path
        assert 'authorization' not in request.headers
        assert request.headers['content-type'] == 'application/json'
        assert json.loads(request.content) == {**config, 'email': CREDENTIAL['email'], 'api_key': KEY}
        return httpx.Response(200, json=EXAMPLES[operation]['body'])
    calls = transport(monkeypatch, handler)
    result = await node(operation, config).execute({})
    assert len(calls) == 1
    assert result == {'status': 'success', 'http_status': 200, 'data': EXAMPLES[operation]['body']}
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['search_facebook_ads', 'search_google_ads', 'search_linkedin_ads'])
async def test_async_webhook_all_ads_is_one_explicit_request(monkeypatch, operation):
    config = {'company_domain': 'tesla.com', 'all_ads': True, 'webhook_url': 'https://example.com/hook'}
    reply = JOBS[operation]['body']
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json=reply))
    result = await node(operation, config).execute({})
    assert result['data'] == reply and len(calls) == 1
    assert json.loads(calls[0].content) == {**config, 'email': CREDENTIAL['email'], 'api_key': KEY}


@pytest.mark.asyncio
async def test_linkedin_batch_and_page_id(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json=EXAMPLES['search_linkedin_ads']['body']))
    for config in ({'linkedin_page_id': '15564'}, {'linkedin_page_ids': ['15564', '2048']}, {'company_domains': ['tesla.com', 'zoom.com']}):
        await node('search_linkedin_ads', config).execute({})
        assert json.loads(calls[-1].content) == {**config, 'email': CREDENTIAL['email'], 'api_key': KEY}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,code,reply', [
    ('create_google_shopping_search', 202, {'id': '04092348-9321-0066-0000-c99a6273cf86'}),
    ('get_google_shopping_status', 202, {'status': 'processing', 'message': 'Task still in queue, try again later'}),
    ('get_google_shopping_status', 204, None),
])
async def test_shopping_job_lifecycle_without_polling(monkeypatch, operation, code, reply):
    calls = transport(monkeypatch, lambda r: httpx.Response(code, **({'json': reply} if reply else {})))
    result = await node(operation, CASES[operation][1]).execute({})
    assert result['status'] == 'success' and result['http_status'] == code
    assert result['data'] == (reply if reply else {'ads': []})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [200, 400, 401, 402, 403, 429, 500])
async def test_rejections_are_verbatim_and_redact_secrets(monkeypatch, code):
    reply = {'detail': 'Invalid username and api key', 'echo': {KEY: [KEY]}}
    calls = transport(monkeypatch, lambda r: httpx.Response(code, json=reply))
    result = await node('search_tiktok_ads', {'keyword': 'toys'}).execute({})
    assert result['status'] == 'error'
    assert result['error']['detail'] == 'Invalid username and api key'
    assert result['error']['echo'] == {'[redacted]': ['[redacted]']}
    assert KEY not in json.dumps(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reply', [[], 'hello'])
async def test_unexpected_envelope_is_not_success(monkeypatch, reply):
    transport(monkeypatch, lambda r: httpx.Response(200, json=reply))
    with pytest.raises(ValueError, match='unexpected JSON envelope'):
        await node('search_tiktok_ads', {'keyword': 'toys'}).execute({})


@pytest.mark.asyncio
async def test_non_json_error_does_not_echo_response(monkeypatch):
    calls = transport(monkeypatch, lambda r: httpx.Response(502, text='<html>' + KEY + '</html>'))
    with pytest.raises(ValueError, match='non-JSON') as error:
        await node('search_tiktok_ads', {'keyword': 'toys'}).execute({})
    assert KEY not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_tiktok_failure_code_is_not_success(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={'code': 1, 'message': 'Search failed'}))
    result = await node('search_tiktok_ads', {'keyword': 'toys'}).execute({})
    assert result['status'] == 'error' and result['error']['message'] == 'Search failed'


@pytest.mark.asyncio
async def test_unknown_tiktok_shape_cannot_verify_connection(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, lambda r: httpx.Response(200, json={}))
    evidence = await collect_evidence(node_type='automation-adyntel', user_id='fixture-user', credential_data=CREDENTIAL)
    assert evidence.reachable is None


@pytest.mark.parametrize('operation,config', [
    ('search_facebook_ads', {}), ('search_linkedin_ads', {}),
    ('search_google_ads', {'company_domain': 'https://tesla.com'}),
    ('search_google_ads', {'company_domain': 'www.tesla.com'}),
    ('search_google_ads', {'company_domain': 'tesla.com', 'all_ads': True}),
    ('search_facebook_ads', {'company_domain': 'tesla.com', 'all_ads': True}),
    ('search_linkedin_ads', {'company_domain': 'tesla.com', 'all_ads': True}),
    ('search_google_ads', {'company_domain': 'tesla.com', 'webhook_url': 'file:///tmp/hook'}),
    ('search_linkedin_keywords', {'keyword': 'webinar', 'dateOption': 'custom-date-range'}),
    ('search_linkedin_keywords', {'keyword': 'webinar', 'startDate': '2026-02-30'}),
    ('search_linkedin_keywords', {'keyword': 'webinar', 'startDate': '2026-02-01', 'endDate': '2026-01-01'}),
    ('search_tiktok_ads', {'keyword': 'toys', 'api_key': 'override'}),
])
def test_invalid_inputs(operation, config):
    with pytest.raises(ValueError):
        module.AdyntelFullConfig.model_validate({'config': {'operation': operation, **config}})


@pytest.mark.asyncio
async def test_connection_evidence_is_only_reachability(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    calls = transport(monkeypatch, lambda r: httpx.Response(200, json=EXAMPLES['search_tiktok_ads']['body']))
    evidence = await collect_evidence(node_type='automation-adyntel', user_id='fixture-user', credential_data=CREDENTIAL)
    assert evidence.reachable is True
    assert module.AdyntelNode.connection_evidence.proves == 'reachability'
    assert len(calls) == 1
    assert json.loads(calls[0].content) == {'keyword': 'toys', 'api_key': KEY, 'email': CREDENTIAL['email']}
