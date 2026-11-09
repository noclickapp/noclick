"""Exercise Ignition's wire requests against provider-authored Core API examples.

These tests pin routes, bodies, pagination and failure behavior without an
Ignition account, and preserve the documented distinction between omitted and cleared fields.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.ignition_node import IgnitionNode, IgnitionAPIKeyCredential

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/ignition/operations.json').read_text())
CASES = FIXTURE['cases']
KEY = 'ignpk_live_unit_test_key'


def node(config):
    data = {'config': config, 'credentials': {'credential_type': 'ignition_api_key', 'api_key': KEY}}
    return IgnitionNode('ignition-test', 'automation-ignition', data, config=IgnitionNode.parse_config(data))


def intercept(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr('nodes.ignition_node.httpx.AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_documented_requests(monkeypatch, case):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.ignitionapp.com'
        assert request.url.path == '/rest/v1' + case['path']
        assert request.headers['Authorization'] == 'Bearer ' + KEY
        if case['body'] is not None:
            assert json.loads(request.content) == case['body']
            assert request.headers['Idempotency-Key'] == 'test-request-001'
        else:
            assert not request.content
        if case['operation'].startswith('list_'):
            assert request.url.params['limit'] == '100'
        return httpx.Response(case['status'], json=case['response'])

    intercept(monkeypatch, handler)
    config = {'operation': case['operation'], **case['config']}
    if case['body'] is not None:
        config['idempotency_key'] = 'test-request-001'
    result = await node(config).execute({})
    assert len(calls) == 1
    assert result['status'] == 'success'
    expected = case['response']['data'] if case['operation'].startswith('list_') else case['response']
    assert result['data'] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('backwards', [False, True])
async def test_page_cursors_and_filters(monkeypatch, backwards):
    def handler(request):
        assert request.url.params['external_id'] == 'crm-4821'
        assert request.url.params['ending_before' if backwards else 'starting_after'] == 'cli_previous'
        return httpx.Response(200, json={'object': 'list', 'has_more': True, 'data': [
            {'object': 'client', 'slug': 'cli_first'}, {'object': 'client', 'slug': 'cli_last'}]})
    intercept(monkeypatch, handler)
    result = await node({'operation': 'list_clients', 'external_id': 'crm-4821',
        'ending_before' if backwards else 'starting_after': 'cli_previous'}).execute({})
    assert result['next_starting_after'] == (None if backwards else 'cli_last')
    assert result['next_ending_before'] == ('cli_first' if backwards else None)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,slug,data', [
    ('update_client', 'client_slug', {'phone': None, 'external_id': ''}),
    ('update_contact', 'contact_slug', {'name': 'Aria Example', 'external_id': None}),
    ('update_proposal', 'proposal_slug', {'name': '', 'terms_template_slug': ''}),
])
async def test_explicit_clears_and_omissions(monkeypatch, operation, slug, data):
    kind = operation.removeprefix('update_')
    def handler(request):
        assert json.loads(request.content) == data
        return httpx.Response(200, json={'object': kind, 'slug': 'example'})
    intercept(monkeypatch, handler)
    assert (await node({'operation': operation, slug: 'example', 'data': data}).execute({}))['status'] == 'success'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401, 'invalid_token'), (403, 'missing_scope'), (409, 'ambiguous_external_id'), (422, 'unprocessable_entity'), (429, 'quota_exceeded'), (500, 'internal_error')])
async def test_provider_failure_is_not_success_or_retried(monkeypatch, status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'code': code, 'message': 'Provider rejected ' + KEY}}, headers={'Retry-After': '12'})
    intercept(monkeypatch, handler)
    result = await node({'operation': 'get_practice'}).execute({})
    assert result['status'] == 'error'
    assert result['http_status'] == status
    assert result['code'] == code
    assert result['retry_after'] == '12'
    assert KEY not in json.dumps(result)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [[], {'object': 'client', 'slug': 'wrong'}, {'object': 'practice'}, {'error': {'message': 'error'}}])
async def test_malformed_response_cannot_prove_connection(monkeypatch, payload):
    intercept(monkeypatch, lambda r: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node({'operation': 'get_practice'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_client', 'client_slug': '../practice'},
    {'operation': 'list_clients', 'limit': 101},
    {'operation': 'list_clients', 'starting_after': 'a', 'ending_before': 'b'},
    {'operation': 'create_client', 'data': {'name': 'Example', 'contacts': []}},
    {'operation': 'update_contact', 'contact_slug': 'x', 'data': {'email': 'aria@example.test'}},
    {'operation': 'create_service', 'data': {'name': 'Example', 'price_type': 'fixed'}},
    {'operation': 'create_proposal', 'data': {'template_slug': 'x', 'client_slug': 'y', 'contract_term': 'fixed'}},
    {'operation': 'update_proposal', 'proposal_slug': 'x', 'data': {'name': None}},
    {'operation': 'update_client', 'client_slug': 'x', 'data': {'address': None}},
    {'operation': 'send_proposal', 'proposal_slug': 'x', 'idempotency_key': 'bad\r\nheader'},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_whitespace():
    cred = IgnitionAPIKeyCredential(api_key='  ' + KEY + '  ')
    assert cred.credential_type == 'ignition_api_key'
    assert cred.api_key == KEY
    with pytest.raises(ValidationError):
        IgnitionAPIKeyCredential(api_key='Bearer ' + KEY)
