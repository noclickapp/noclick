"""Peaka project requests and published response-example regressions; no live account."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import peaka_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/peaka/contract.json').read_text())
KEY = 'synthetic-peaka-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **credential):
    return NodeFactory.create_node(node_id='peaka-test', node_type='automation-peaka', node_data={
        'config': config, 'credentials': {'credential_type': 'peaka_api_key', 'api_key': KEY,
            'project_id': 'mtKDhe1U', **credential}})


def transport(monkeypatch, reply):
    seen = []
    def respond(request):
        seen.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_contract_routes_bodies_and_published_response_shapes(monkeypatch, operation):
    case = CASES[operation]
    seen = transport(monkeypatch, lambda _: httpx.Response(200, json=case['response']) if case['response'] is not None else httpx.Response(200))
    result = await node(case['config']).execute({})
    assert len(seen) == 1
    request = seen[0]
    assert request.url.host == 'partner.peaka.studio'
    assert request.url.path == case['path']
    assert request.method == case['method']
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    assert dict(request.url.params) == case['params']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert result['status'] == 'success'
    if case['method'] == 'DELETE':
        assert result['acknowledged'] is True
    else:
        assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_eu_path_encoding_and_empty_evidence(monkeypatch):
    seen = transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    assert (await node({'operation':'list_catalogs'}, region='eu').execute({}))['data'] == []
    assert seen[0].url.host == 'partner.eu.peaka.studio'
    encoded = transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    await node({'operation':'list_tables', 'catalog_id':'my/catalog', 'schema_name':'with space'}).execute({})
    assert b'/catalogs/my%2Fcatalog/schemas/with%20space/tables' in encoded[0].url.raw_path
    assert native.PeakaNode.connection_evidence.operation == 'list_catalogs'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_errors_preserve_provider_message_and_redact_key_without_retry(monkeypatch, status):
    seen = transport(monkeypatch, lambda _: httpx.Response(status, text='Provider rejected ' + KEY))
    result = await node({'operation':'list_catalogs'}).execute({})
    assert len(seen) == 1 and result['http_status'] == status
    assert result['status'] == 'error' and result['error'] == 'Provider rejected [redacted]'


@pytest.mark.asyncio
async def test_malformed_success_and_error_envelope(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text='<html>wrong host</html>'))
    with pytest.raises(ValueError, match='invalid JSON'):
        await node({'operation':'list_catalogs'}).execute({})
    transport(monkeypatch, lambda _: httpx.Response(200, json={'errorCode':100, 'message':'No access'}))
    assert (await node({'operation':'list_catalogs'}).execute({}))['status'] == 'error'


def test_manual_credential_defaults_and_validation():
    credential = native.PeakaAPIKeyCredential(api_key=KEY, project_id='mtKDhe1U')
    assert credential.credential_type == 'peaka_api_key'
    assert KEY not in repr(credential)
    for changes in ({'api_key':'Bearer bad'}, {'project_id':'https://peaka.com'}, {'region':'elsewhere'}):
        with pytest.raises(ValidationError):
            native.PeakaAPIKeyCredential.model_validate({'api_key':KEY, 'project_id':'mtKDhe1U', **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize('format', ['CELL_TYPED', 'SIMPLE', 'COMPACT'])
async def test_query_result_formats_preserve_published_envelopes(monkeypatch, format):
    examples = json.loads((Path(__file__).parent / 'fixtures/peaka/query_formats.json').read_text())
    seen = transport(monkeypatch, lambda _: httpx.Response(200, json=examples[format]))
    result = await node({'operation':'execute_query', 'statement':'SELECT 1', 'format':format}).execute({})
    assert result['data'] == examples[format]
    assert dict(seen[0].url.params) == {'format': format}
