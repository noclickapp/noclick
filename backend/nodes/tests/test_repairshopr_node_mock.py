"""Exercise RepairShopr's real factory, parser and HTTP request construction.

Responses are the provider's pinned examples; transport interception keeps all
25 operations offline while checking exact routes, payloads and authentication.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import repairshopr_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/repairshopr/operations.json').read_text())
TOKEN = 'synthetic-repairshopr-token-42'
CREDENTIAL = {'credential_type': 'repairshopr_api_token', 'subdomain': 'testsubdomainwi1', 'api_token': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='repairshopr-test', node_type='automation-repairshopr',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})


def intercept(monkeypatch, response):
    calls = []
    def handler(request):
        calls.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_repairshopr_documented_operations(monkeypatch, operation):
    fixture = FIXTURES[operation]
    calls = intercept(monkeypatch, httpx.Response(200, json=fixture['response']))
    result = await node(fixture['config']).execute({})
    assert result == {'status': 'success', 'data': fixture['response']}
    assert len(calls) == 1
    req = calls[0]
    assert req.method == fixture['method']
    assert req.url.host == 'testsubdomainwi1.repairshopr.com'
    assert req.url.path == fixture['path']
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(req.url)
    if fixture['method'] == 'GET':
        assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k,v in fixture['values'].items()}
        assert not req.content
    else:
        assert json.loads(req.content) == fixture['values']
        assert not req.url.query


@pytest.mark.parametrize('value', ['https://evil.test', 'https://tenant.repairshopr.com.evil.test', 'https://user:pass@tenant.repairshopr.com', 'http://tenant.repairshopr.com', 'https://tenant.repairshopr.com:444', 'a/b', '../admin'])
def test_repairshopr_bad_tenant_rejected(value):
    with pytest.raises(ValidationError):
        native.RepairshoprAPITokenCredential(**{**CREDENTIAL, 'subdomain': value})


def test_repairshopr_paste_normalization_and_invalid_token():
    credential = native.RepairshoprAPITokenCredential(**{**CREDENTIAL, 'subdomain': ' https://Example.repairshopr.com/customers ', 'api_token': ' '+TOKEN+'\n'})
    assert credential.subdomain == 'example'
    assert credential.api_token == TOKEN
    for token in ['Bearer '+TOKEN, 'https://repairshopr.com', 'bad\nheader', '<token>']:
        with pytest.raises(ValidationError):
            native.RepairshoprAPITokenCredential(**{**CREDENTIAL, 'api_token': token})


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'error':'Unauthorized'}), (403, {'error':'Forbidden'}), (302, {'redirect':'https://evil.test'}), (429, {'error':'Rate limited'}), (500, {'error':'Server error'})])
async def test_repairshopr_http_errors_are_failures(monkeypatch, status, body):
    calls = intercept(monkeypatch, httpx.Response(status, json={**body, 'echo':TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({'operation':'get_current_user'}).execute({})
    assert TOKEN not in str(error.value)
    assert str(status) in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>Login</html>'), httpx.Response(200, json={'success':False,'message':'Rejected'}), httpx.Response(200, json={'errors':['No access']}), httpx.Response(200, json='unexpected'), httpx.Response(200, json={})])
async def test_repairshopr_non_api_responses_rejected(monkeypatch, response):
    intercept(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({'operation':'get_current_user'}).execute({})


def test_repairshopr_schema_rejects_invalid_ids_and_untyped_fields():
    for config in [{'operation':'get_customer','id':-1}, {'operation':'get_customer','id':'../settings'}, {'operation':'list_customers','page':0}, {'operation':'update_customer','id':1}, {'operation':'create_customer','firstname':'Joe','url':'https://evil.test'}]:
        with pytest.raises(ConfigValidationError):
            node(config)


@pytest.mark.asyncio
async def test_repairshopr_paginated_customer_filters_and_explicit_false(monkeypatch):
    calls=intercept(monkeypatch,httpx.Response(200,json={'invoices':[], 'meta':{'page':3,'total_pages':3}}))
    result=await node({'operation':'list_invoices','page':3,'paid':False,'unpaid':True}).execute({})
    assert dict(calls[0].url.params)=={'page':'3','paid':'false','unpaid':'true'}
    assert result['data']['meta']['page']==3


@pytest.mark.asyncio
async def test_repairshopr_partial_update_keeps_unspecified_fields_omitted(monkeypatch):
    response = FIXTURES['update_customer']['response']
    calls = intercept(monkeypatch, httpx.Response(200, json=response))
    await node({'operation':'update_customer', 'id':1, 'email':'walkin@somedomain.com'}).execute({})
    assert json.loads(calls[0].content) == {'email':'walkin@somedomain.com'}
