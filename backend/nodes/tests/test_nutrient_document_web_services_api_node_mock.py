"""Provider route, bearer authentication, body, pagination and failure regressions."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import nutrient_document_web_services_api_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/nutrient-document-web-services-api/requests.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='nutrient-test', node_type=native.NutrientDocumentWebServicesApiNode.integration_type,
        node_data={'config': config, 'credentials': {'credential_type': 'nutrient_document_web_services_api_key', 'api_key': 'synthetic-api-key'}})


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_published_requests_and_lossless_responses(monkeypatch, case):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(case['status'], **({'json': case['response']} if case['status'] != 204 else {}))
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    result = await node(case['config']).execute({})
    assert result == ({'deleted': True} if case['status'] == 204 else case['response'])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url).startswith('https://api.nutrient.io/')
    assert request.url.path == case['path']
    assert request.headers['authorization'] == 'Bearer synthetic-api-key'
    assert request.headers['x-nutrient-api-version'] == '2026-05-25'
    if 'body' in case['config']:
        assert json.loads(request.content) == case['config']['body']
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_cursor_and_filters(monkeypatch):
    def respond(request):
        assert dict(request.url.params) == {'page_size': '25', 'cursor': 'opaque+cursor'}
        return httpx.Response(200, json={'runs': [], 'pagination': {'next_cursor': 'next-page'}})
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    result = await node({'operation': 'extraction_batches_list', 'page_size': 25, 'cursor': 'opaque+cursor'}).execute({})
    assert result['pagination']['next_cursor'] == 'next-page'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 404, 409, 429, 500])
async def test_provider_errors_are_not_success(monkeypatch, status):
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={'error': 'rejected'})), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_account_info'}).execute({})


def test_credential_has_manual_default_and_evidence_is_account_read():
    assert native.NutrientCredential(api_key='synthetic-api-key').credential_type == 'nutrient_document_web_services_api_key'
    assert native.NutrientDocumentWebServicesApiNode.connection_evidence.identity_operation == 'get_account_info'
