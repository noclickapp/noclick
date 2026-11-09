"""Exercise PreciseFP against examples copied from its published API reference.

The cases cover every route and write payload, plus failures that could otherwise
misrepresent an account connection or repeat an uncertain financial-data write.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import precisefp_node as module
from nodes.core.registry import NodeFactory
from nodes.oauth.precisefp_oauth import OAUTH_PROVIDER
from nodes.scopes.precisefp import PRECISEFP_SCOPES

CASES = json.loads((Path(__file__).parent / 'fixtures/precisefp/requests.json').read_text())
CREDENTIAL = {'credential_type': 'precisefp_oauth', 'access_token': 'precisefp-test-secret'}


def node(config):
    return NodeFactory.create_node(node_id='precisefp-test', node_type='automation-precisefp',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, callback):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(callback)) as session:
            yield session
    monkeypatch.setattr(module, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_precisefp_documented_requests_and_responses(monkeypatch, case):
    seen = []
    def request(req):
        seen.append(req)
        assert req.method == case['method']
        assert req.url.host == 'four.precisefp.com'
        assert req.url.path == '/api' + case['path']
        assert req.headers['authorization'] == 'Bearer precisefp-test-secret'
        assert (json.loads(req.content) if req.content else None) == case['body']
        assert dict(req.url.params) == ({'limit': '100', 'offset': '0'} if case['operation'] == 'list_accounts' else {})
        return httpx.Response(case['status'], **({'json': case['response']} if case['response'] is not None else {}))
    transport(monkeypatch, request)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(seen) == 1
    assert result.get('write_acknowledged', False) == (case['method'] != 'GET')
    if case['response'] is not None: assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_precisefp_accounts_pagination_and_filters(monkeypatch):
    def request(req):
        assert dict(req.url.params) == {'type': 'prospects', 'limit': '10', 'offset': '10'}
        return httpx.Response(200, json={'items': [{'id': 100}], 'total': 20, 'offset': 10, 'limit': 10})
    transport(monkeypatch, request)
    result = await node({'operation': 'list_accounts', 'type': 'prospects', 'limit': 10, 'offset': 10}).execute({})
    assert result['next_offset'] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, [], {'error': 'Bad token'}, {'status': 'error', 'messages': ['Invalid']}])
async def test_precisefp_bad_identity_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    assert (await node({'operation': 'get_current_user'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_precisefp_provider_rejection_preserves_text_and_redacts_secrets(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(401, json={'messages': 'Rejected precisefp-test-secret'}))
    result = await node({'operation': 'get_current_user'}).execute({})
    assert result['http_status'] == 401
    assert result['error'] == 'Rejected [redacted]'


@pytest.mark.asyncio
async def test_precisefp_ambiguous_write_is_not_retried(monkeypatch):
    seen = []
    def request(req):
        seen.append(req)
        raise httpx.ReadTimeout('timed out', request=req)
    transport(monkeypatch, request)
    case = next(c for c in CASES if c['operation'] == 'create_account')
    result = await node(case['config']).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unverified'
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'items': []}, {'items': [{'id': 'a|b'}]}])
async def test_precisefp_legacy_list_wrappers(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    result = await node({'operation': 'list_contacts', 'account_id': 100}).execute({})
    assert result['status'] == 'success' and result['items'] == body['items']


@pytest.mark.asyncio
async def test_precisefp_refresh_uses_shared_hooks(monkeypatch):
    from nodes.core import oauth_refresh
    refresh = AsyncMock(return_value='fresh-token')
    monkeypatch.setattr(oauth_refresh, 'ensure_fresh_oauth_token', refresh)
    transport(monkeypatch, lambda req: httpx.Response(200, json={'email': 'williamblack@precisefp.com'}))
    assert (await node({'operation': 'get_current_user'}).execute({}))['status'] == 'success'
    assert refresh.await_args.kwargs['provider'] == 'precisefp'
    freshen = AsyncMock(return_value=CREDENTIAL)
    monkeypatch.setattr(oauth_refresh, 'freshen_oauth_credential', freshen)
    await module.PreciseFPNode.freshen_credential(CREDENTIAL)
    assert freshen.await_args.kwargs['provider'] == 'precisefp'


@pytest.mark.parametrize('config', [
    {'operation': 'get_account', 'account_id': '../user'},
    {'operation': 'get_contact', 'account_id': 100, 'contact_id': '../user'},
    {'operation': 'create_account', 'type': 'clients'},
    {'operation': 'update_account', 'account_id': 100},
    {'operation': 'create_contact', 'account_id': 100, 'type': 'wrong'},
])
def test_precisefp_rejects_invalid_identifiers_and_incomplete_writes(config):
    with pytest.raises((ValidationError, ValueError)): node(config)


def test_precisefp_oauth_scopes_and_manual_credential():
    assert set(PRECISEFP_SCOPES) == set(module.OPERATIONS)
    assert set(PRECISEFP_SCOPES.declared_scopes()) == {'accounts', 'login'}
    assert OAUTH_PROVIDER.identity_url == module.BASE + '/user'
    assert OAUTH_PROVIDER.name_field == 'email'
    assert module.PreciseFPOAuthCredential(access_token='valid-token').credential_type == 'precisefp_oauth'
