"""Replay CINC's published examples through the real factory and HTTP transport."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import cinc_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/cinc/documented_examples.json').read_text())
TOKEN = 'cinc-test-access-5db7d9c0'


def node(config):
    return NodeFactory.create_node(node_id='cinc-test', node_type='automation-cinc', node_data={
        'config': config, 'credentials': {'credential_type': 'cinc_oauth', 'access_token': TOKEN}})


def transport(monkeypatch, body, status=200):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(EXAMPLES))
async def test_cinc_published_examples(operation, monkeypatch):
    example = EXAMPLES[operation]
    calls = transport(monkeypatch, example['response'], example['status'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example['method']
    assert request.url.host == 'public.cincapi.com'
    assert request.url.path == '/v2' + example['path']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if 'body' in example['config']:
        assert json.loads(request.content) == example['config']['body']
    else:
        assert not request.content
    payload = example['response'].get('body', example['response'])
    key = {'list_agents': 'agents', 'list_leads': 'leads', 'list_lead_notes': 'notes', 'list_labels': 'labels',
           'get_agent': 'agent', 'get_lead': 'lead', 'get_lead_note': 'note', 'get_label': 'label'}.get(operation)
    assert result['data'] == (payload[key] if key else payload)
    if operation in {'list_agents', 'list_leads'}:
        assert dict(request.url.params) == {'limit': '2', 'offset': '0'}
        assert result['next_page_token'] == payload['paging']['next']
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_cinc_cursor_is_opaque_and_no_automatic_follow(monkeypatch):
    calls = transport(monkeypatch, EXAMPLES['list_leads']['response'])
    result = await node({'operation': 'list_leads', 'next': '9 + next/cursor', 'limit': 2}).execute({})
    assert len(calls) == 1
    assert dict(calls[0].url.params) == {'next': '9 + next/cursor', 'limit': '2'}
    assert result['next_page_token'] == '9'


@pytest.mark.asyncio
async def test_cinc_bare_swagger_responses_and_empty_writes(monkeypatch):
    calls = transport(monkeypatch, [{'id': 'AGENT0', 'username': 'jane.doe@email.com'}])
    result = await node({'operation': 'list_agents'}).execute({})
    assert result['data'][0]['id'] == 'AGENT0' and result['pagination_available'] is False
    assert len(calls) == 1
    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)), **kw))
    result = await node(EXAMPLES['apply_lead_labels']['config']).execute({})
    assert result['data'] is None and result['http_status'] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'error': 'rejected'}, {'body': {'errors': ['rejected']}}, {'body': []}, {'body': {'agents': {}}}])
async def test_cinc_error_and_malformed_envelopes_fail(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_agents'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_cinc_http_failures_never_report_success(monkeypatch, status):
    calls = transport(monkeypatch, {'message': 'Provider refusal'}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_me'}).execute({})
    assert len(calls) == 1


@pytest.mark.parametrize('identifier', ['../leads', 'agent?x=y', 'a/b', 'x#frag', ''])
def test_cinc_path_segments_reject_route_changes(identifier):
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS['get_agent'](agent_id=identifier)


def test_cinc_contract_body_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        native.LeadRequest(info={'contact': {'email': 'jane.doe@email.com', 'made_up': 'value'}})
    assert native.CINCOAuthCredential(access_token=TOKEN).credential_type == 'cinc_oauth'


@pytest.mark.asyncio
async def test_cinc_refresh_uses_shared_choke_point(monkeypatch):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value=TOKEN)
    monkeypatch.setattr(oauth_refresh, 'ensure_fresh_oauth_token', refresh)
    transport(monkeypatch, EXAMPLES['get_me']['response'])
    await node({'operation': 'get_me'}).execute({})
    assert refresh.await_args.kwargs['provider'] == 'cinc'
    assert refresh.await_args.kwargs['caller_path'] == 'execute'


def test_cinc_oauth_declaration_and_scope_permissions():
    from nodes.oauth.cinc_oauth import OAUTH_PROVIDER
    assert OAUTH_PROVIDER.name_field == 'body.username'
    assert OAUTH_PROVIDER.identity_url == 'https://public.cincapi.com/v2/site/me'
    assert OAUTH_PROVIDER.token_url == 'https://authv2.cincapi.com/integrator/token'
    assert set(native.CINC_SCOPES.declared_scopes()) == {'api:read', 'api:create', 'api:update', 'api:delete'}
