"""Snitcher native factory and public v1 request regressions; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import snitcher_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/snitcher/requests.json').read_text())
TOKEN = 'synthetic-snitcher-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='snitcher-test', node_type='automation-snitcher',
        node_data={'config': config, 'credentials': {'credential_type': 'snitcher_token', 'api_token': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_one_contract_request_per_operation(monkeypatch, case):
    response = httpx.Response(case['status'], json=case['response']) if case['status'] != 204 else httpx.Response(204)
    requests = transport(monkeypatch, response)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success', result
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.host, request.url.path) == (case['method'], 'api.snitcher.com', case['path'])
    assert dict(request.url.params) == case['params']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == case['body']
    if case['status'] == 204:
        assert result['deleted'] is True
    elif isinstance(case['response'], dict):
        for key, value in case['response'].items():
            assert result[key] == value
    else:
        assert result['data'] == case['response']


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 404, 422, 429, 500])
async def test_http_errors_preserve_status_redact_token_and_never_retry(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, json={'message': 'Rejected ' + TOKEN}, headers={'Location': 'https://example.test'}))
    result = await node({'operation': 'get_profile'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>bad</html>'), httpx.Response(200, json={'success': False, 'message': 'Denied'}), httpx.Response(200, json='bad')])
async def test_failed_and_malformed_envelopes_do_not_verify(monkeypatch, response):
    transport(monkeypatch, response)
    assert (await node({'operation': 'get_profile'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_pagination_truncation_and_explicit_null_are_retained(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'success': True, 'data': [], 'current_page': 1, 'last_page': 2, 'truncated': True}))
    result = await node({'operation': 'list_workspaces'}).execute({})
    assert result['has_more'] is True and result['next_page'] == 2 and result['truncated'] is True
    requests = transport(monkeypatch, httpx.Response(200, json={'field_key': 'industry', 'value': None}))
    cfg = next(c['config'] for c in CASES if c['config']['operation'] == 'set_organisation_custom_field')
    assert (await node({**cfg, 'value': None}).execute({}))['value'] is None
    assert json.loads(requests[0].content) == {'value': None}


@pytest.mark.parametrize('config', [
    {'operation': 'get_workspace', 'uuid': '../evil'},
    {'operation': 'list_sessions', 'workspaceUuid': '550e8400-e29b-41d4-a716-446655440000'},
    {'operation': 'list_workspaces', 'size': 1001},
    {'operation': 'list_workspaces', 'page': True},
    {'operation': 'list_workspaces', 'page': 251, 'size': 100},
    {'operation': 'list_workspaces', 'arbitrary_route': '/bad'},
])
def test_invalid_inputs_fail_before_network(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_evidence_contract():
    assert native.SnitcherTokenCredential(api_token=TOKEN).credential_type == 'snitcher_token'
    assert native.SnitcherNode.connection_evidence.identity_operation == 'get_profile'
    assert len(native.ROUTES) == 25


def test_session_url_filters_are_optional_and_dates_use_the_contract_format():
    workspace = '550e8400-e29b-41d4-a716-446655440000'
    native.SnitcherListSessionsConfig(workspaceUuid=workspace, date='2025-03-01')
    native.SnitcherListOrganisationSessionsConfig(workspaceUuid=workspace, organisationUuid=workspace)
    with pytest.raises(ValidationError):
        native.SnitcherListSessionsConfig(workspaceUuid=workspace, date='20250301')
