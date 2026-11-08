"""Exercise HigherGov's actual factory, transport, pagination and connection read.

Contract-derived filter examples cover every published endpoint without an account.
Failure cases guard against exposing query credentials or following provider links.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import highergov_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/highergov/contract_cases.json').read_text())
TOKEN = 'synthetic-highergov+secret/42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='highergov-fixture', node_type='automation-highergov',
        node_data={'config': config, 'credentials': {'credential_type': 'highergov_api_key', 'api_key': TOKEN}})


def mock(monkeypatch, response):
    requests = []

    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)

    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def page(results=None, **counters):
    return {'results': [{'pursuit_name': 'Capture plan', 'unique_key': 'owned-pursuit'}] if results is None else results,
            'meta': {'pagination': {'page': 2, 'pages': 4, 'count': 89, **counters}},
            'links': {'next': 'https://evil.example.test/?api_key=' + TOKEN}}


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['operation'])
async def test_published_routes_and_filters(monkeypatch, case):
    requests = mock(monkeypatch, page())
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET' and request.url.host == 'www.highergov.com'
    assert request.url.path == case['path']
    assert dict(request.url.params) == {**case['query'], 'api_key': TOKEN}
    assert result['status'] == 'success' and result['next_page_number'] == 3
    assert result['results'][0]['pursuit_name'] == 'Capture plan'
    assert 'links' not in result and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_account_owned_pursuits_default_connection_read(monkeypatch):
    requests = mock(monkeypatch, page(page=1, pages=1))
    evidence = native.HigherGovNode.connection_evidence
    assert evidence.proves == 'account' and evidence.label_keys[0] == 'pursuit_name'
    result = await node({'operation': evidence.operation}).execute({})
    assert requests[0].url.path == '/api-external/pursuit/'
    assert dict(requests[0].url.params) == {'api_key': TOKEN, 'page_number': '1', 'page_size': '10'}
    assert result['next_page_number'] is None and result['pagination_known']


@pytest.mark.asyncio
async def test_empty_page_and_unknown_pagination(monkeypatch):
    mock(monkeypatch, {'results': []})
    result = await node({'operation': 'list_opportunities'}).execute({})
    assert result['status'] == 'success' and result['results'] == []
    assert result['pagination_known'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [204, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_are_not_success_and_redact_keys(monkeypatch, status):
    requests = mock(monkeypatch, lambda request: httpx.Response(status,
        text='Provider rejection: ' + str(request.url), headers={'Location': 'https://evil.example.test/'}))
    result = await node({'operation': 'list_pursuits'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert TOKEN not in str(result) and native.quote(TOKEN, safe='') not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'results': {}}, {'results': [1]},
    {'results': [], 'error': 'rejected'}, {'results': [], 'meta': []},
    {'results': [], 'meta': {'pagination': {'page': True}}}])
async def test_malformed_or_failed_envelopes(monkeypatch, body):
    mock(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_pursuits'}).execute({})


@pytest.mark.asyncio
async def test_transport_exception_never_discloses_authenticated_url(monkeypatch):
    def response(request):
        raise httpx.ConnectError(str(request.url), request=request)
    mock(monkeypatch, response)
    with pytest.raises(ValueError, match='request did not complete') as error:
        await node({'operation': 'list_pursuits'}).execute({})
    assert TOKEN not in str(error.value)


@pytest.mark.asyncio
async def test_json_content_type_and_recursive_secret_redaction(monkeypatch):
    mock(monkeypatch, lambda request: httpx.Response(200, text='<html>Login</html>', headers={'Content-Type': 'text/html'}))
    with pytest.raises(ValueError, match='non-JSON'):
        await node({'operation': 'list_pursuits'}).execute({})
    mock(monkeypatch, page([{'nested': {'api_key': TOKEN, 'url': 'https://www.highergov.com/?api_key=' + native.quote(TOKEN, safe='')}}]))
    result = await node({'operation': 'list_pursuits'}).execute({})
    assert TOKEN not in str(result) and native.quote(TOKEN, safe='') not in str(result)
    assert 'api_key' not in result['results'][0]['nested']


@pytest.mark.parametrize('config', [
    {'operation': 'list_documents'}, {'operation': 'create_pursuit'},
    {'operation': 'list_opportunities', 'page_size': 101},
    {'operation': 'list_opportunities', 'page_number': 0},
    {'operation': 'list_opportunities', 'ordering': 'made_up'},
    {'operation': 'list_opportunities', 'posted_date': '2026-02-30'},
    {'operation': 'list_pursuits', 'api_key': 'override'},
])
def test_invalid_config_fails_before_transport(config):
    assert native.HigherGovNode.validate_config({'config': config})['valid'] is False


@pytest.mark.parametrize('value', ['https://example.test/key', '<token>', 'has spaces'])
def test_manual_key_refuses_urls_placeholders_and_whitespace(value):
    with pytest.raises((ValueError, ValidationError)):
        native.HigherGovAPIKeyCredential(api_key=value)
