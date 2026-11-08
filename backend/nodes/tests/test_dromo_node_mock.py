"""Offline contract regressions for Dromo v1; no account is used."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import TypeAdapter

from nodes import dromo_node as dromo
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/dromo/contract_cases.json').read_text())['cases']
TOKEN = 'synthetic-dromo-backend-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    n = NodeFactory.create_node(node_id='dromo-test', node_type='automation-dromo', node_data={
        'config':config, 'credentials':{'credential_type':'dromo_api_key','api_key':TOKEN}})
    n.emit = AsyncMock()
    return n


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr(dromo, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_one_published_request_and_response(monkeypatch, operation):
    case = CASES[operation]
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == 'app.dromo.io'
        assert request.headers['X-Dromo-License-Key'] == TOKEN
        assert request.method == case['method']
        assert request.url.path == case['path']
        assert (json.loads(request.content) if request.content else None) == case['body']
        params = {'start':'0','end':'100'} if operation == 'list_uploads' else {'offset':'0','limit':'100'} if operation == 'list_headless_imports' else {}
        assert dict(request.url.params) == params
        return httpx.Response(case['status'], json=case['response']) if case['response'] is not None else httpx.Response(case['status'])
    transport(monkeypatch, handler)
    n = node(case['config'])
    out = await n.execute({})
    assert out['status'] == 'success'
    assert out['http_status'] == case['status']
    assert len(seen) == 1
    if operation.startswith('delete_'):
        assert out['data'] == {'id':case['config']['id'], 'deletion_acknowledged':True}
    else:
        assert out['data'] == case['response']
    n.emit.assert_awaited_once_with(out)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401,403,404,429,500])
async def test_errors_preserve_provider_text_without_secrets(monkeypatch, status):
    transport(monkeypatch, lambda r: httpx.Response(status, text='Rejected '+TOKEN))
    out = await node({'operation':'list_schemas'}).execute({})
    assert out == {'status':'error','http_status':status,'message':'Rejected [redacted]'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(302,b'{}'),(200,b'not-json'),(200,b'{}'),(200,b'[{}]')])
async def test_bad_connection_response_cannot_succeed(monkeypatch,status,body):
    transport(monkeypatch, lambda r: httpx.Response(status, content=body))
    with pytest.raises(ValueError):
        await node({'operation':'list_schemas'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation':'get_schema','id':'../other'},
    {'operation':'list_uploads','start':100,'end':99},
    {'operation':'list_uploads','end':10001},
    {'operation':'list_headless_imports','limit':1001},
    {'operation':'create_schema','name':'Bad','fields_json':'[{}]'},
    {'operation':'create_schema','name':'Bad','fields_json':'[]','settings_json':'{"not_supported":true}'},
    {'operation':'create_headless_import','initial_data_json':'[]'},
    {'operation':'create_headless_import','schema_id':'66d6300d-1414-4655-83b4-8c80fc527315','fields_json':'[]','initial_data_json':'[]'},
    {'operation':'create_headless_import','fields_json':'[]','initial_data_json':'{}'},
])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        TypeAdapter(dromo.Operation).validate_python(config)


@pytest.mark.asyncio
async def test_explicit_pages_preserve_pagination_without_following_urls(monkeypatch):
    payload={'count':75,'next':'https://app.dromo.io/api/v1/headless/imports/?offset=10&limit=10','previous':None,'results':[]}
    seen=[]
    def handler(request):
        seen.append(request)
        assert dict(request.url.params) == {'offset':'0','limit':'10'}
        return httpx.Response(200,json=payload)
    transport(monkeypatch,handler)
    out=await node({'operation':'list_headless_imports','limit':10}).execute({})
    assert out['data']==payload
    assert len(seen)==1


def test_saved_schema_headless_override():
    op=TypeAdapter(dromo.Operation).validate_python({'operation':'create_headless_import',
        'schema_id':'4eefe3fe-7181-4562-aa28-8cfe1c5bdf1b', 'settings_json':'{"allowInvalidSubmit":true}',
        'initial_data_json':'[{"product":"widget1","transaction":"foo123"}]'})
    assert dromo.request_parts(op)[3] == {'schema_id':'4eefe3fe-7181-4562-aa28-8cfe1c5bdf1b',
        'settings':{'allowInvalidSubmit':True}, 'initial_data':[{'product':'widget1','transaction':'foo123'}]}


def test_nullable_settings_are_preserved_for_clearing():
    config={**CASES['update_schema']['config'], 'settings_json':'{"webhookUrl":null,"maxRecords":null}'}
    op=TypeAdapter(dromo.Operation).validate_python(config)
    assert dromo.request_parts(op)[3]['settings'] == {'webhookUrl':None,'maxRecords':None}


@pytest.mark.parametrize('value', ['{"title":null}', '{"developmentMode":null}'])
def test_nonnullable_settings_reject_explicit_null(value):
    with pytest.raises(ValueError):
        dromo.SchemaWrite.settings(value)
