"""Partner v2 request and credential tests without live accounts."""
import base64
import json
from pathlib import Path
import httpx
import pytest
from nodes import bigoven_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/bigoven/requests.json').read_text())
CREDENTIAL = {'credential_type': 'bigoven_api_key', 'api_key': 'synthetic-key', 'username': 'test-cook', 'password': 'synthetic-password'}


def node(config, credential=None):
    return NodeFactory.create_node(node_id='bigoven-test', node_type='automation-bigoven',
        node_data={'config': config, 'credentials': credential or CREDENTIAL})


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
async def test_partner_request(monkeypatch, case):
    reply = {'ResultCount': 1, 'Results': [{'RecipeID': 100, 'Title': 'Pasta'}]}
    requests = transport(monkeypatch, httpx.Response(200, json=reply))
    assert await node(case['config']).execute({}) == {'status': 'success', 'data': reply}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.scheme == 'https' and request.url.host == 'api2.bigoven.com'
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert request.headers['x-bigoven-api-key'] == CREDENTIAL['api_key']
    assert request.headers['authorization'] == 'Basic ' + base64.b64encode(b'test-cook:synthetic-password').decode()


@pytest.mark.asyncio
async def test_account_evidence_omits_auth_token(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'BOAuthToken': 'user-token', 'Profile': {'FullName': 'Example Cook', 'UserID': 123}}))
    result = await node({'operation': 'get_me'}).execute({})
    assert result['name'] == 'Example Cook' and result['id'] == 123
    assert 'BOAuthToken' not in result['data'] and 'user-token' not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 429, 500])
async def test_rejection_and_redaction(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, text='Rejected synthetic-key synthetic-password', headers={'Location': 'https://example.org'}))
    result = await node({'operation': 'get_me'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == code
    assert 'synthetic-key' not in str(result) and 'synthetic-password' not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_response_variants(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[{'ID': 1, 'Notes': 'Tasty'}]))
    assert (await node({'operation': 'list_notes', 'recipe_id': 100}).execute({}))['data'] == [{'ID': 1, 'Notes': 'Tasty'}]
    transport(monkeypatch, httpx.Response(204))
    assert (await node({'operation': 'delete_recipe', 'recipe_id': 100}).execute({}))['data'] is None
    for reply in (httpx.Response(200, text='<html>not JSON</html>'), httpx.Response(200, json={'Error': 'Rejected'})):
        transport(monkeypatch, reply)
        assert (await node({'operation': 'get_me'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('config', [
    {'operation': 'get_recipe', 'recipe_id': 0},
    {'operation': 'create_review', 'recipe_id': 100, 'StarRating': 6, 'Comment': 'Tasty'},
    {'operation': 'search_recipes', 'pg': 0},
    {'operation': 'add_recipe_to_grocery_list', 'recipe_id': 100, 'scale': 0},
    {'operation': 'add_grocery_item', 'name': ''},
])
def test_invalid_inputs(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_default_and_foreign_credential():
    assert native.BigOvenCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != 'credential_type'}).credential_type == 'bigoven_api_key'
    with pytest.raises(ValueError):
        node({'operation': 'get_me'}, dict(CREDENTIAL, credential_type='foreign_api_key'))
