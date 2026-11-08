"""DNSFilter factory and wire-contract regressions without a live account.

Fixtures cover every operation and preserve explicit false and empty writes.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import dnsfilter_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/dnsfilter/operations.json').read_text())
TOKEN = 'synthetic-dnsfilter-token'
CREDENTIAL = {'credential_type': 'dnsfilter_api_token', 'api_token': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='dnsfilter-test', node_type='automation-dnsfilter',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_published_routes_auth_and_bodies(monkeypatch, case):
    listing = case['config']['operation'].startswith('list_')
    record = {'id': '7', 'type': 'networks', 'attributes': {'name': 'Owned office'}}
    body = {'data': [record] if listing else record, 'links': {'self': 'https://api.dnsfilter.com' + case['path']}}
    calls = transport(monkeypatch, lambda _: httpx.Response(204) if case['method'] == 'DELETE' else httpx.Response(200, json=body))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.host == 'api.dnsfilter.com' and request.url.scheme == 'https'
    assert request.url.path == case['path']
    assert request.headers['Authorization'] == TOKEN
    assert dict(request.url.params) == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    if listing:
        assert result['items'][0]['name'] == 'Owned office'
        assert result['page_scope'] == 'provider_default_page' and result['links'] == body['links']
    if case['method'] == 'DELETE':
        assert result['deletion_acknowledged'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_provider_failure_never_reports_success_or_retries(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, text='Provider refusal ' + TOKEN))
    result = await node({'operation': 'delete_network', 'network_id': 7}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'].startswith('Provider refusal ')
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': None}, {'data': []}, {'data': {}}, {'data': {}, 'errors': ['failed']}])
async def test_malformed_success_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    assert (await node({'operation': 'get_current_user'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_empty_account_specific_evidence_page(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json={'data': []}))
    result = await node({'operation': 'list_organizations'}).execute({})
    assert result['status'] == 'success' and result['items'] == []
    assert calls[0].url.path == '/v1/organizations'
    assert native.DNSFilterNode.connection_evidence.operation == 'list_organizations'


@pytest.mark.asyncio
async def test_success_response_does_not_echo_saved_token(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'data': {'id': '1', 'attributes': {'name': TOKEN}}}))
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['status'] == 'success' and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_uncertain_write_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('private detail ' + TOKEN, request=request)
    calls = transport(monkeypatch, fail)
    result = await node({'operation': 'create_policy', 'name': 'Office', 'organization_id': 42}).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unknown'
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'get_network', 'network_id': '../users'},
    {'operation': 'get_user_agent', 'user_agent_id': '../../users'},
    {'operation': 'add_allowlist_domain', 'policy_id': 1, 'domain': 'example.com'},
    {'operation': 'update_network', 'network_id': 1, 'name': 'Office'},
    {'operation': 'list_organizations', 'api_url': 'https://other.example'},
])
def test_bad_config_rejected_before_request(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.parametrize('value', ['Bearer abc', 'abc\r\nInjected: x', 'https://app.dnsfilter.com', '<token>', 'nonascii-é'])
def test_bad_token_rejected(value):
    with pytest.raises(ValidationError):
        native.DNSFilterAPITokenCredential(api_token=value)


def test_wrong_credential_family_rejected():
    with pytest.raises(ValidationError):
        native.DNSFilterAPITokenCredential(credential_type='other_api_token', api_token=TOKEN)
