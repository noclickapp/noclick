"""Outseta request contracts; all keys and responses are synthetic, no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import outseta_node as native
from nodes.core.registry import NodeFactory

KEY = 'synthetic-outseta-key'
SECRET = 'synthetic-outseta-secret'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {'credential_type': 'outseta_api_key', 'subdomain': 'example', 'api_key': KEY, 'api_secret': SECRET, **changes}


def node(config):
    return NodeFactory.create_node(node_id='outseta-test', node_type='automation-outseta',
        node_data={'config': config, 'credentials': credential()})


def transport(monkeypatch, handler):
    requests = []
    def respond(request):
        requests.append(request)
        return handler(request)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CONTRACTS = json.loads((Path(__file__).parent / 'fixtures/outseta/requests.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CONTRACTS, ids=lambda c: c['config']['operation'])
async def test_every_operation_is_one_exact_contract_request(monkeypatch, case):
    cfg = case['config']
    def respond(request):
        if case['method'] == 'DELETE':
            return httpx.Response(204)
        if cfg['operation'].startswith('list_'):
            return httpx.Response(200, json={'items': [{'Uid': 'p123', 'Email': 'person@example.com'}],
                'metadata': {'limit': 25, 'offset': 0, 'total': 1}})
        return httpx.Response(200, json={'Uid': 'p123', 'Name': 'Fixture'})
    requests = transport(monkeypatch, respond)
    result = await node(cfg).execute({})
    assert result['status'] == 'success' and len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.host == 'example.outseta.com'
    assert request.url.path == '/api/v1/' + case['path']
    assert request.headers['Authorization'] == f'Outseta {KEY}:{SECRET}'
    assert dict(request.url.params) == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    if cfg['operation'].startswith('list_'):
        assert result['items'][0]['Email'] == 'person@example.com' and result['next_offset'] is None


@pytest.mark.asyncio
async def test_page_number_and_server_cap(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={
        'metadata': {'limit': 25, 'offset': 1, 'total': 80}, 'items': [{'Uid': 'abc'}]}))
    result = await node({'operation': 'list_people', 'limit': 100, 'offset': 1, 'q': 'A + B'}).execute({})
    assert result['has_more'] is True and result['next_offset'] == 2
    assert dict(requests[0].url.params) == {'limit': '100', 'offset': '1', 'q': 'A + B'}


@pytest.mark.asyncio
async def test_recursive_redaction_keeps_business_data(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={'Uid': 'p123', 'Email': 'p@example.com',
        'Password': SECRET, 'DiscordUser': {'DiscordOAuthRefreshToken': 'hidden'}, 'Name': KEY}))
    result = await node({'operation': 'get_person', 'person_uid': 'p123'}).execute({})
    assert result['item']['Email'] == 'p@example.com'
    assert not any(s in str(result) for s in (KEY, SECRET, 'hidden', 'Password', 'RefreshToken'))


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_provider_errors_are_redacted_and_not_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text='Rejected ' + SECRET))
    with pytest.raises(ValueError) as caught:
        await node({'operation': 'create_account', 'name': 'Fixture'}).execute({})
    assert str(status) in str(caught.value) and SECRET not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'error': 'bad'}, {'items': [], 'metadata': {}},
    {'items': [], 'metadata': {'limit': 0, 'offset': 0, 'total': 0}},
    {'items': [], 'metadata': {'limit': 25, 'offset': 3, 'total': 100}}])
async def test_bad_collection_is_not_success(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'list_people'}).execute({})


@pytest.mark.parametrize('subdomain', ['evil.com', 'https://example.outseta.com.evil.com', 'https://u:p@example.outseta.com',
    'http://example.outseta.com', 'https://example.outseta.com:8443', 'a/b', 'a.outseta.com.evil'])
def test_refuse_foreign_or_malformed_account_host(subdomain):
    with pytest.raises(ValidationError):
        native.OutsetaAPIKeyCredential.model_validate(credential(subdomain=subdomain))


def test_manual_credential_paste_and_default_type():
    shaped = native.OutsetaAPIKeyCredential(subdomain=' https://Example.outseta.com/#/settings ', api_key=' '+KEY+'\n', api_secret=SECRET)
    assert shaped.subdomain == 'example' and shaped.api_key == KEY
    assert shaped.credential_type == 'outseta_api_key'
    with pytest.raises(ValidationError):
        native.OutsetaAPIKeyCredential.model_validate(credential(api_secret='header:secret'))


@pytest.mark.asyncio
async def test_partial_person_update_and_refuse_empty_update(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={'Uid': 'p123', 'PhoneWork': '123'}))
    await node({'operation': 'update_person', 'person_uid': 'p123', 'phone_work': '123'}).execute({})
    assert json.loads(requests[0].content) == {'PhoneWork': '123'}
    with pytest.raises(ValueError, match='at least one field'):
        await node({'operation': 'update_person', 'person_uid': 'p123'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_html_success_is_not_a_connection(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text='<html>Sign in</html>', headers={'Content-Type': 'text/html'}))
    with pytest.raises(ValueError, match='JSON response'):
        await node({'operation': 'list_people'}).execute({})
